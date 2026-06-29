"""Profiler — decide how mature a pipeline is, from the YAML alone.

This is what keeps pipewright from nagging a three-line workflow about
machinery meant for a monorepo. Each rule declares the smallest tier it's
relevant for; ``select_visible`` then shows only what fits.
"""

from __future__ import annotations

from pipewright.models import TIER_ORDER, Finding, ProjectInfo, Tier
from pipewright.workflows import LoadedWorkflow, jobs_of, load_workflows


def profile(info: ProjectInfo, loaded: list[LoadedWorkflow] | None = None) -> Tier:
    if loaded is None:
        loaded = load_workflows(info)

    n_files = len(info.workflows)
    n_jobs = 0
    has_matrix = has_needs = has_docker = self_hosted = reusable = False

    for _wf, data, text in loaded:
        for job in jobs_of(data):
            n_jobs += 1
            strategy = job.get("strategy")
            if isinstance(strategy, dict) and "matrix" in strategy:
                has_matrix = True
            if job.get("needs"):
                has_needs = True
            if job.get("uses"):  # a job that calls a reusable workflow
                reusable = True
            runs_on = job.get("runs-on")
            if "self-hosted" in str(runs_on):
                self_hosted = True
        if "workflow_call" in text:
            reusable = True
        if "docker/build-push-action" in text or "docker build" in text:
            has_docker = True

    if self_hosted or has_docker or reusable or n_files >= 3 or n_jobs >= 6:
        return Tier.SCALE
    if has_matrix or has_needs or n_jobs >= 2:
        return Tier.GROWING
    return Tier.STARTER


def select_visible(findings: list[Finding], tier: Tier) -> list[Finding]:
    """Keep only findings whose minimum tier is at or below the detected tier."""
    limit = TIER_ORDER[tier]
    return [f for f in findings if TIER_ORDER.get(f.min_tier, 0) <= limit]
