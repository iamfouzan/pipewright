"""Tests for the usage stats and savings estimates."""

from __future__ import annotations

from datetime import datetime, timezone

from ciwright.models import Finding, Tier
from ciwright.usage import (
    Run,
    estimate_savings,
    parse_runs,
    summarize,
)

NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _payload():
    # two completed runs: 10 min and 20 min, both within the window
    return {
        "workflow_runs": [
            {
                "name": "CI",
                "run_started_at": "2026-05-30T10:00:00Z",
                "updated_at": "2026-05-30T10:10:00Z",
                "status": "completed",
                "conclusion": "success",
            },
            {
                "name": "CI",
                "run_started_at": "2026-05-31T10:00:00Z",
                "updated_at": "2026-05-31T10:20:00Z",
                "status": "completed",
                "conclusion": "failure",
            },
            {
                "name": "Old",  # outside a 7-day window
                "run_started_at": "2026-01-01T10:00:00Z",
                "updated_at": "2026-01-01T10:05:00Z",
                "status": "completed",
                "conclusion": "success",
            },
        ]
    }


def test_parse_runs_reads_durations():
    runs = parse_runs(_payload())
    assert len(runs) == 3
    assert runs[0].minutes == 10.0
    assert runs[1].minutes == 20.0


def test_summarize_window_and_aggregates():
    runs = parse_runs(_payload())
    stats = summarize(runs, window_days=7, now=NOW)
    assert stats.total_runs == 2  # the January run is excluded
    assert stats.total_minutes == 30.0
    assert stats.avg_minutes == 15.0
    assert stats.median_minutes == 15.0


def test_minutes_per_week_scaling():
    runs = parse_runs(_payload())
    stats = summarize(runs, window_days=7, now=NOW)
    # 30 min over a 7-day window → 30 min/week
    assert round(stats.minutes_per_week) == 30


def test_busiest_workflow_first():
    runs = parse_runs(_payload())
    stats = summarize(runs, window_days=30, now=NOW)
    assert stats.by_workflow[0].name == "CI"


def test_estimates_only_for_speed_opportunities():
    runs = parse_runs(_payload())
    stats = summarize(runs, window_days=7, now=NOW)
    findings = [
        Finding("dependency-caching", "Cache dependencies", False, "high", "", "speed", Tier.STARTER),
        Finding("parallel-tests", "Run tests in parallel", True, "high", "", "speed", Tier.GROWING),
        Finding("token-permissions", "Limit GITHUB_TOKEN scope", False, "medium", "", "security", Tier.GROWING),
    ]
    ests = {e.rule_id for e in estimate_savings(stats, findings)}
    assert "dependency-caching" in ests  # an opportunity with a mapping
    assert "parallel-tests" not in ests  # already optimized
    assert "token-permissions" not in ests  # no wall-clock mapping


def test_estimate_range_is_ordered_and_scaled():
    stats = summarize(parse_runs(_payload()), window_days=7, now=NOW)
    f = Finding("dependency-caching", "Cache dependencies", False, "high", "", "speed", Tier.STARTER)
    (e,) = estimate_savings(stats, [f])
    assert 0 <= e.low_per_run <= e.high_per_run
    assert e.high_per_run <= stats.avg_minutes  # never more than a whole run


def test_no_runs_summarizes_to_zero():
    stats = summarize([], window_days=30, now=NOW)
    assert stats.total_runs == 0
    assert stats.avg_minutes == 0.0
    assert estimate_savings(stats, []) == []


def test_bare_list_payload_is_accepted():
    runs = parse_runs(
        [
            {
                "name": "CI",
                "run_started_at": "2026-05-30T10:00:00Z",
                "updated_at": "2026-05-30T10:05:00Z",
                "status": "completed",
            }
        ]
    )
    assert len(runs) == 1 and runs[0].minutes == 5.0


def test_run_duration_never_negative():
    r = Run(
        workflow="x",
        started=datetime(2026, 5, 1, 10, 5, tzinfo=timezone.utc),
        updated=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
        status="completed",
        conclusion=None,
    )
    assert r.minutes == 0.0
