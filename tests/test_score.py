"""Tests for the per-category health score."""

from __future__ import annotations

from ciwright.models import Finding, Tier
from ciwright.score import compute_score


def _f(rule_id, optimized, category):
    return Finding(
        rule_id=rule_id,
        title=rule_id,
        optimized=optimized,
        impact="medium",
        detail="",
        category=category,
        min_tier=Tier.STARTER,
    )


def test_all_optimized_scores_100():
    findings = [_f("a", True, "speed"), _f("b", True, "speed")]
    card = compute_score(findings)
    assert card.categories["speed"].score == 100
    assert card.overall == 100


def test_all_opportunities_score_0():
    card = compute_score([_f("a", False, "speed")])
    assert card.categories["speed"].score == 0
    assert card.overall == 0


def test_partial_score_rounds():
    findings = [_f("a", True, "speed"), _f("b", False, "speed"), _f("c", False, "speed")]
    assert compute_score(findings).categories["speed"].score == 33


def test_empty_category_scores_none():
    card = compute_score([_f("a", True, "speed")])
    assert card.categories["security"].score is None


def test_overall_ignores_empty_categories():
    # speed=100, cost=0, security/reliability empty → overall = mean(100, 0) = 50
    findings = [_f("a", True, "speed"), _f("b", False, "cost")]
    assert compute_score(findings).overall == 50


def test_overall_none_when_no_findings():
    assert compute_score([]).overall is None
