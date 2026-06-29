"""Small, plain data containers shared across pipewright."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# Impact is qualitative on purpose: a read-only scan can't know the real
# minutes saved without CI run history (a later feature).
IMPACT_ORDER = {"high": 0, "medium": 1, "low": 2}

# The four things pipewright watches.
CATEGORIES = ("speed", "cost", "security", "reliability")


class Tier(str, Enum):
    """How mature a pipeline is — controls which checks are relevant."""

    STARTER = "starter"
    GROWING = "growing"
    SCALE = "scale"


TIER_ORDER = {Tier.STARTER: 0, Tier.GROWING: 1, Tier.SCALE: 2}


@dataclass
class ProjectInfo:
    """What pipewright could figure out about a repository."""

    root: Path
    package_manager: str | None  # "pip" | "poetry" | "pipenv" | "uv" | None
    test_runner: str | None  # "pytest" | "unittest" | None
    workflows: list[Path] = field(default_factory=list)

    @property
    def has_github_actions(self) -> bool:
        return bool(self.workflows)


@dataclass
class Finding:
    """One check and its result for this repo."""

    rule_id: str
    title: str
    optimized: bool  # True = already in good shape, False = opportunity
    impact: str  # "high" | "medium" | "low"
    detail: str
    category: str = "speed"  # one of CATEGORIES
    min_tier: Tier = Tier.STARTER  # smallest pipeline this matters for

    @property
    def is_opportunity(self) -> bool:
        return not self.optimized
