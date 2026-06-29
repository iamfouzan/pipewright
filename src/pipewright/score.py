"""Health score — a per-category grade, the way Lighthouse scores a web page.

Each category scores 0–100 from the share of its checks that are already in
good shape. The overall score is the mean of the categories that actually have
checks at this pipeline's tier, so a small repo isn't graded on machinery it
doesn't need.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipewright.models import CATEGORIES, Finding


@dataclass
class CategoryScore:
    category: str
    optimized: int
    total: int

    @property
    def score(self) -> int | None:
        if self.total == 0:
            return None
        return round(100 * self.optimized / self.total)


@dataclass
class ScoreCard:
    categories: dict[str, CategoryScore]

    @property
    def overall(self) -> int | None:
        scored = [c.score for c in self.categories.values() if c.score is not None]
        if not scored:
            return None
        return round(sum(scored) / len(scored))


def compute_score(findings: list[Finding]) -> ScoreCard:
    cats: dict[str, CategoryScore] = {}
    for category in CATEGORIES:
        in_cat = [f for f in findings if f.category == category]
        optimized = sum(1 for f in in_cat if f.optimized)
        cats[category] = CategoryScore(category, optimized, len(in_cat))
    return ScoreCard(cats)
