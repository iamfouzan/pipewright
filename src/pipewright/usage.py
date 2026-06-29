"""CI usage stats and savings estimates.

Two very different kinds of number live here, and the distinction matters:

* **Measured facts** — how many runs, how many minutes, how often. These come
  straight from your run history and are exact.
* **Savings estimates** — how much a fix *might* save. These are rough ranges
  built on stated assumptions, not promises. The only way to know for sure is
  to apply the fix and compare the next runs.

We surface the facts prominently and keep the estimates clearly labelled, so a
single confident-but-wrong "saves 22 minutes" number never misleads anyone.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pipewright.models import Finding


@dataclass
class Run:
    workflow: str
    started: datetime
    updated: datetime
    status: str
    conclusion: str | None

    @property
    def minutes(self) -> float:
        return max(0.0, (self.updated - self.started).total_seconds() / 60.0)


@dataclass
class WorkflowUsage:
    name: str
    runs: int
    minutes: float


@dataclass
class UsageStats:
    window_days: int
    total_runs: int
    total_minutes: float
    avg_minutes: float
    median_minutes: float
    runs_per_week: float
    by_workflow: list[WorkflowUsage]

    @property
    def minutes_per_week(self) -> float:
        if self.window_days <= 0:
            return 0.0
        return self.total_minutes / self.window_days * 7.0


@dataclass
class Estimate:
    rule_id: str
    title: str
    low_per_run: float
    high_per_run: float
    low_per_week: float
    high_per_week: float
    assumption: str


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_runs(payload: dict | list) -> list[Run]:
    """Parse the GitHub Actions runs API shape (or a bare list of runs)."""
    items = payload.get("workflow_runs", []) if isinstance(payload, dict) else payload
    runs: list[Run] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        started = _parse_dt(item.get("run_started_at") or item.get("created_at"))
        updated = _parse_dt(item.get("updated_at"))
        if started is None or updated is None:
            continue
        name = item.get("name") or item.get("display_title") or "workflow"
        runs.append(
            Run(
                workflow=str(name),
                started=started,
                updated=updated,
                status=str(item.get("status", "")),
                conclusion=item.get("conclusion"),
            )
        )
    return runs


def summarize(
    runs: list[Run], window_days: int = 30, now: datetime | None = None
) -> UsageStats:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)
    recent = [
        r for r in runs if r.started >= cutoff and r.status in ("", "completed")
    ]

    durations = [r.minutes for r in recent]
    total = sum(durations)

    per_wf: dict[str, WorkflowUsage] = {}
    for r in recent:
        wu = per_wf.setdefault(r.workflow, WorkflowUsage(r.workflow, 0, 0.0))
        wu.runs += 1
        wu.minutes += r.minutes

    return UsageStats(
        window_days=window_days,
        total_runs=len(recent),
        total_minutes=total,
        avg_minutes=(total / len(recent)) if recent else 0.0,
        median_minutes=statistics.median(durations) if durations else 0.0,
        runs_per_week=(len(recent) / window_days * 7.0) if window_days else 0.0,
        by_workflow=sorted(per_wf.values(), key=lambda w: w.minutes, reverse=True),
    )


# Rough wall-clock reductions per finding — ESTIMATES, expressed as ranges.
# These overlap (you can't just add them up) and depend heavily on the project.
_SPEED_SAVINGS: dict[str, tuple[float, float, str]] = {
    "dependency-caching": (0.05, 0.25, "skipping dependency installs on a cache hit"),
    "parallel-tests": (0.20, 0.50, "using every CPU core for the test run"),
    "test-splitting": (0.30, 0.60, "splitting the suite across machines (wall-clock)"),
    "docker-layer-cache": (0.15, 0.45, "reusing cached Docker layers"),
}


def estimate_savings(stats: UsageStats, findings: list[Finding]) -> list[Estimate]:
    estimates: list[Estimate] = []
    for f in findings:
        if f.optimized:
            continue
        mapping = _SPEED_SAVINGS.get(f.rule_id)
        if mapping is None:
            continue
        low, high, why = mapping
        estimates.append(
            Estimate(
                rule_id=f.rule_id,
                title=f.title,
                low_per_run=stats.avg_minutes * low,
                high_per_run=stats.avg_minutes * high,
                low_per_week=stats.minutes_per_week * low,
                high_per_week=stats.minutes_per_week * high,
                assumption=why,
            )
        )
    return estimates


def load_runs_from_file(path: Path) -> list[Run]:
    return parse_runs(json.loads(Path(path).read_text(encoding="utf-8")))
