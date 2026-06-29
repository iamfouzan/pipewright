"""Rules — read-only checks, one per opportunity.

Each rule answers a single question about the workflow files and tags its
finding with a category (speed/cost/security/reliability) and the smallest
pipeline tier the check is relevant for. Nothing here edits anything.
"""

from __future__ import annotations

import re

from pipewright.models import Finding, ProjectInfo, Tier
from pipewright.workflows import (
    LoadedWorkflow,
    jobs_of,
    load_workflows,
    triggers,
)


def _uses_pytest(info: ProjectInfo, loaded: list[LoadedWorkflow]) -> bool:
    if info.test_runner == "pytest":
        return True
    return any("pytest" in text for _, _, text in loaded)


# --- speed (starter) ---------------------------------------------------


def check_caching(loaded: list[LoadedWorkflow]) -> Finding:
    found = any(("actions/cache" in t) or ("cache:" in t) for _, _, t in loaded)
    return Finding(
        rule_id="dependency-caching",
        title="Cache dependencies",
        optimized=found,
        impact="high",
        category="speed",
        min_tier=Tier.STARTER,
        detail=(
            "Dependency caching is configured."
            if found
            else "No caching found — every run reinstalls from scratch. "
            "Add cache: 'pip' (or 'poetry'/'pipenv') to actions/setup-python."
        ),
    )


def check_concurrency(loaded: list[LoadedWorkflow]) -> Finding:
    found = False
    for _, data, text in loaded:
        conc = data.get("concurrency")
        if isinstance(conc, dict) and conc.get("cancel-in-progress"):
            found = True
        elif "cancel-in-progress: true" in text.replace("  ", " "):
            found = True
    return Finding(
        rule_id="cancel-superseded-runs",
        title="Cancel superseded runs",
        optimized=found,
        impact="medium",
        category="speed",
        min_tier=Tier.STARTER,
        detail=(
            "Old runs are cancelled when you push again."
            if found
            else "Pushing twice runs the pipeline twice. Add a concurrency "
            "group with cancel-in-progress: true."
        ),
    )


def check_path_filters(loaded: list[LoadedWorkflow]) -> Finding:
    found = False
    for _, data, _ in loaded:
        for cfg in triggers(data).values():
            if isinstance(cfg, dict) and ("paths" in cfg or "paths-ignore" in cfg):
                found = True
    return Finding(
        rule_id="path-filters",
        title="Skip docs-only changes",
        optimized=found,
        impact="medium",
        category="speed",
        min_tier=Tier.STARTER,
        detail=(
            "Path filters are in place."
            if found
            else "A README typo runs the whole suite. Add paths-ignore for "
            "'**.md' and 'docs/**'. (Watch out for required checks — keep a "
            "passing stub job with the same name.)"
        ),
    )


# --- cost (growing) ----------------------------------------------------


def check_timeouts(loaded: list[LoadedWorkflow]) -> Finding:
    all_jobs = [job for _, data, _ in loaded for job in jobs_of(data)]
    found = bool(all_jobs) and all("timeout-minutes" in job for job in all_jobs)
    return Finding(
        rule_id="job-timeouts",
        title="Set job timeouts",
        optimized=found,
        impact="medium",
        category="cost",
        min_tier=Tier.GROWING,
        detail=(
            "Jobs have timeout-minutes set."
            if found
            else "A job with no timeout-minutes can hang and burn the default "
            "6-hour limit. Add timeout-minutes (e.g. 15) to each job."
        ),
    )


def check_double_trigger(loaded: list[LoadedWorkflow]) -> Finding | None:
    flagged = any(
        "push" in triggers(data) and "pull_request" in triggers(data)
        for _, data, _ in loaded
    )
    if not flagged:
        return None  # not applicable — only surface when the pattern exists
    return Finding(
        rule_id="double-run-trigger",
        title="Avoid double CI runs",
        optimized=False,
        impact="medium",
        category="cost",
        min_tier=Tier.GROWING,
        detail="This workflow runs on both push and pull_request, so every PR "
        "commit triggers CI twice. Scope push to your main branch, or trigger "
        "on pull_request only.",
    )


# --- speed (growing / scale) -------------------------------------------


def check_parallel_tests(
    info: ProjectInfo, loaded: list[LoadedWorkflow]
) -> Finding | None:
    if not _uses_pytest(info, loaded):
        return None
    found = any(
        ("-n auto" in t) or ("-n=" in t) or ("--numprocesses" in t) or ("pytest-xdist" in t)
        for _, _, t in loaded
    )
    return Finding(
        rule_id="parallel-tests",
        title="Run tests in parallel",
        optimized=found,
        impact="high",
        category="speed",
        min_tier=Tier.GROWING,
        detail=(
            "Tests already use multiple cores (pytest-xdist)."
            if found
            else "Tests appear to run on a single core. Install pytest-xdist "
            "and run pytest -n auto to use every core on the runner."
        ),
    )


def check_test_splitting(
    info: ProjectInfo, loaded: list[LoadedWorkflow]
) -> Finding | None:
    if not _uses_pytest(info, loaded):
        return None
    found = any(
        ("--splits" in t) or ("--shard" in t) or ("pytest-split" in t)
        for _, _, t in loaded
    )
    return Finding(
        rule_id="test-splitting",
        title="Split tests across machines",
        optimized=found,
        impact="medium",
        category="speed",
        min_tier=Tier.SCALE,
        detail=(
            "Tests are split across runners."
            if found
            else "The suite runs on one machine. Use a matrix with "
            "pytest-split (--splits / --group) to run groups in parallel."
        ),
    )


def check_docker_cache(loaded: list[LoadedWorkflow]) -> Finding | None:
    has_docker = any(
        ("docker/build-push-action" in t) or ("docker build" in t)
        for _, _, t in loaded
    )
    if not has_docker:
        return None
    cached = any(("cache-from" in t) or ("type=gha" in t) for _, _, t in loaded)
    return Finding(
        rule_id="docker-layer-cache",
        title="Cache Docker layers",
        optimized=cached,
        impact="high",
        category="speed",
        min_tier=Tier.SCALE,
        detail=(
            "Docker layer caching is configured."
            if cached
            else "Docker images rebuild from scratch each run. Add "
            "cache-from/cache-to: type=gha to the build step."
        ),
    )


# --- security & reliability --------------------------------------------

_USES_RE = re.compile(r"uses:\s*([^\s#]+)", re.IGNORECASE)
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")

# High-confidence deprecated actions, runners, and workflow commands.
_DEPRECATED = [
    ("actions/checkout@v1", "actions/checkout@v1"),
    ("actions/checkout@v2", "actions/checkout@v2"),
    ("actions/setup-python@v1", "actions/setup-python@v1"),
    ("actions/setup-python@v2", "actions/setup-python@v2"),
    ("actions/upload-artifact@v1", "actions/upload-artifact@v1"),
    ("actions/upload-artifact@v2", "actions/upload-artifact@v2"),
    ("actions/upload-artifact@v3", "actions/upload-artifact@v3 (v4 required)"),
    ("actions/download-artifact@v1", "actions/download-artifact@v1"),
    ("actions/download-artifact@v2", "actions/download-artifact@v2"),
    ("actions/download-artifact@v3", "actions/download-artifact@v3 (v4 required)"),
    ("ubuntu-18.04", "the ubuntu-18.04 runner (end-of-life)"),
    ("ubuntu-16.04", "the ubuntu-16.04 runner (end-of-life)"),
    ("macos-10.15", "the macos-10.15 runner (end-of-life)"),
    ("macos-11", "the macos-11 runner (end-of-life)"),
    ("::set-output", "the deprecated ::set-output command"),
    ("::save-state", "the deprecated ::save-state command"),
]


def _external_action_refs(loaded: list[LoadedWorkflow]) -> list[str]:
    """Every `uses:` value that points at a third-party action (not local)."""
    refs: list[str] = []
    for _wf, _data, text in loaded:
        for m in _USES_RE.finditer(text):
            val = m.group(1).strip().strip("'\"")
            if val.startswith("./") or val.startswith("docker://"):
                continue
            refs.append(val)
    return refs


def check_action_pinning(loaded: list[LoadedWorkflow]) -> Finding | None:
    refs = _external_action_refs(loaded)
    if not refs:
        return None  # no third-party actions to pin

    def is_pinned(ref: str) -> bool:
        return "@" in ref and bool(_SHA_RE.match(ref.rsplit("@", 1)[1]))

    pinned = all(is_pinned(r) for r in refs)
    return Finding(
        rule_id="action-pinning",
        title="Pin actions to a SHA",
        optimized=pinned,
        impact="medium",
        category="security",
        min_tier=Tier.GROWING,
        detail=(
            "Third-party actions are pinned to a commit SHA."
            if pinned
            else "Actions are pinned to mutable tags (e.g. @v4), which a "
            "hijacked tag could exploit. Pin to a full commit SHA — "
            "uses: actions/checkout@<40-char-sha> # v4 — ideally with Dependabot."
        ),
    )


def check_token_permissions(loaded: list[LoadedWorkflow]) -> Finding | None:
    if not loaded:
        return None
    found = False
    for _wf, data, _ in loaded:
        if isinstance(data, dict) and "permissions" in data:
            found = True
        if any("permissions" in job for job in jobs_of(data)):
            found = True
    return Finding(
        rule_id="token-permissions",
        title="Limit GITHUB_TOKEN scope",
        optimized=found,
        impact="medium",
        category="security",
        min_tier=Tier.GROWING,
        detail=(
            "A permissions block restricts the GITHUB_TOKEN."
            if found
            else "No permissions block — the GITHUB_TOKEN may default to broad "
            "write access. Add permissions: contents: read at the top, and widen "
            "only where a job needs it."
        ),
    )


def check_deprecated(loaded: list[LoadedWorkflow]) -> Finding | None:
    if not loaded:
        return None
    hits: list[str] = []
    for _wf, _data, text in loaded:
        for needle, label in _DEPRECATED:
            if needle in text and label not in hits:
                hits.append(label)
    clean = not hits
    if clean:
        detail = "No deprecated actions, runners, or commands found."
    else:
        detail = (
            f"Found deprecated usage: {'; '.join(hits[:3])}. These will stop "
            "working — upgrade to current versions."
        )
    return Finding(
        rule_id="deprecated-actions",
        title="Replace deprecated actions/runners",
        optimized=clean,
        impact="high",
        category="reliability",
        min_tier=Tier.STARTER,
        detail=detail,
    )


def analyze(info: ProjectInfo) -> list[Finding]:
    """Run every applicable rule and return all findings (unfiltered)."""
    loaded = load_workflows(info)
    findings: list[Finding] = [
        check_caching(loaded),
        check_concurrency(loaded),
        check_path_filters(loaded),
        check_timeouts(loaded),
    ]
    conditional = (
        check_double_trigger(loaded),
        check_docker_cache(loaded),
        check_parallel_tests(info, loaded),
        check_test_splitting(info, loaded),
        check_action_pinning(loaded),
        check_token_permissions(loaded),
        check_deprecated(loaded),
    )
    findings.extend(f for f in conditional if f is not None)
    return findings
