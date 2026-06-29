"""Patcher — turn opportunities into concrete, comment-preserving YAML edits.

Only the changes that can be made as clean, *structured* edits are applied
automatically: caching, path filters, and cancel-superseded-runs. The
test-execution changes (running in parallel, splitting across machines) need
rewriting run-commands and adding plugins, which can't be done safely as a
one-shot YAML edit — so those are surfaced as manual suggestions instead.

Nothing here writes to disk. We load the workflow, edit an in-memory copy,
and hand back the before/after text so a diff can be shown.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError

from pipewright.models import Finding, ProjectInfo

# Rules we can apply automatically as structured YAML edits.
AUTO_FIXABLE = {"dependency-caching", "path-filters", "cancel-superseded-runs"}
# Rules that are real but better done by hand (run-command / plugin changes).
ADVISORY_ONLY = {"parallel-tests", "test-splitting"}

# setup-python's cache: option understands these; uv uses a separate action,
# so we don't pretend we can patch it here.
_SETUP_PY_CACHE = {"pip": "pip", "poetry": "poetry", "pipenv": "pipenv"}


def _rt_yaml() -> YAML:
    yaml = YAML()  # round-trip mode: keeps comments and formatting
    yaml.preserve_quotes = True
    yaml.width = 4096  # don't wrap long ${{ ... }} expressions
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def _get_on(doc: CommentedMap):
    """Return (key, value) for the workflow triggers, tolerating quirks."""
    if "on" in doc:
        return "on", doc["on"]
    if True in doc:  # some parsers turn `on:` into the boolean True
        return True, doc[True]
    return None, None


# --- individual patchers: each returns True if it changed the doc ------


def patch_caching(doc: CommentedMap, info: ProjectInfo) -> bool:
    cache_val = _SETUP_PY_CACHE.get(info.package_manager or "")
    if cache_val is None:
        return False  # uv / unknown — leave it for the manual list
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict):
        return False
    changed = False
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            uses = step.get("uses", "")
            if isinstance(uses, str) and uses.startswith("actions/setup-python"):
                with_block = step.get("with")
                if with_block is None:
                    with_block = CommentedMap()
                    step["with"] = with_block
                if isinstance(with_block, dict) and "cache" not in with_block:
                    with_block["cache"] = cache_val
                    changed = True
    return changed


def patch_path_filters(doc: CommentedMap, info: ProjectInfo) -> bool:
    key, on = _get_on(doc)
    if not isinstance(on, dict):
        return False  # `on: push` or `on: [push]` — converting is unsafe
    target = next((ev for ev in ("pull_request", "push") if ev in on), None)
    if target is None:
        return False
    cfg = on.get(target)
    if cfg is None:
        cfg = CommentedMap()
        on[target] = cfg
    if not isinstance(cfg, dict):
        return False  # e.g. a bare branch list — skip to stay safe
    if "paths" in cfg or "paths-ignore" in cfg:
        return False
    cfg["paths-ignore"] = CommentedSeq(["**.md", "docs/**"])
    return True


def patch_concurrency(doc: CommentedMap, info: ProjectInfo) -> bool:
    if "concurrency" in doc:
        return False
    block = CommentedMap()
    block["group"] = "${{ github.workflow }}-${{ github.ref }}"
    block["cancel-in-progress"] = True
    keys = list(doc.keys())
    pos = keys.index("jobs") if "jobs" in keys else len(keys)
    doc.insert(pos, "concurrency", block)
    return True


_PATCHERS = {
    "dependency-caching": patch_caching,
    "path-filters": patch_path_filters,
    "cancel-superseded-runs": patch_concurrency,
}


# --- target selection + assembling the result -------------------------


@dataclass
class PatchResult:
    target: Path | None
    original_text: str = ""
    new_text: str = ""
    applied: list[Finding] = field(default_factory=list)
    manual: list[Finding] = field(default_factory=list)
    note: str | None = None

    @property
    def changed(self) -> bool:
        return self.original_text != self.new_text


def primary_workflow(info: ProjectInfo, override: Path | None = None) -> Path | None:
    """Choose which workflow file to edit.

    With --workflow, honor it (by path or by bare filename). Otherwise prefer
    the file that looks like the test pipeline, then a conventionally named CI
    file, then just the first one.
    """
    if override is not None:
        if override.is_file():
            return override
        candidate = info.root / ".github" / "workflows" / override.name
        return candidate if candidate.is_file() else None

    if not info.workflows:
        return None

    def reads(p: Path) -> str:
        try:
            return p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""

    for wf in info.workflows:
        if "pytest" in reads(wf) or "test" in reads(wf).lower():
            return wf
    common = {"ci.yml", "ci.yaml", "main.yml", "test.yml", "tests.yml"}
    for wf in info.workflows:
        if wf.name in common:
            return wf
    return info.workflows[0]


def build_patch(
    info: ProjectInfo,
    findings: list[Finding],
    override: Path | None = None,
) -> PatchResult:
    """Apply every safe auto-patch to the target workflow; collect the rest."""
    by_id = {f.rule_id: f for f in findings}
    opportunities = {f.rule_id for f in findings if f.is_opportunity}

    target = primary_workflow(info, override)
    if target is None:
        note = (
            "Couldn't find that workflow file."
            if override is not None
            else "No GitHub Actions workflow found to edit."
        )
        manual = [by_id[r] for r in sorted(opportunities) if r in by_id]
        return PatchResult(target=None, manual=manual, note=note)

    original = target.read_text(encoding="utf-8", errors="ignore")
    yaml = _rt_yaml()
    try:
        doc = yaml.load(original)
    except YAMLError:
        return PatchResult(
            target=target,
            original_text=original,
            new_text=original,
            note=f"Couldn't parse {target.name} as YAML — skipping to stay safe.",
        )

    applied: list[Finding] = []
    if isinstance(doc, CommentedMap):
        for rule_id, patcher in _PATCHERS.items():
            if patcher(doc, info) and rule_id in by_id:
                applied.append(by_id[rule_id])

    buf = io.StringIO()
    yaml.dump(doc, buf)
    new_text = buf.getvalue()

    applied_ids = {f.rule_id for f in applied}
    # Opportunities we couldn't auto-apply (advisory rules, plus any auto rule
    # that didn't fit this file — e.g. caching on a uv project).
    manual_ids = (opportunities - applied_ids) - {"__none__"}
    manual = [by_id[r] for r in sorted(manual_ids) if r in by_id]

    return PatchResult(
        target=target,
        original_text=original,
        new_text=new_text,
        applied=applied,
        manual=manual,
    )
