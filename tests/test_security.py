"""Tests for the security and reliability checks added in v1.1."""

from __future__ import annotations

from ciwright.detect import detect
from ciwright.models import Tier
from ciwright.rules import analyze

PINNED = """\
name: CI
on:
  pull_request:
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11 # v4
      - run: pytest
"""

UNPINNED = """\
name: CI
on:
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pytest
"""

DEPRECATED = """\
name: CI
on:
  pull_request:
jobs:
  test:
    runs-on: ubuntu-18.04
    steps:
      - uses: actions/upload-artifact@v3
      - run: pytest
"""


def _by_id(make_repo, workflow):
    repo = make_repo({"requirements.txt": "pytest>=8\n", ".github/workflows/ci.yml": workflow})
    return {f.rule_id: f for f in analyze(detect(repo))}


def test_sha_pinned_actions_pass(make_repo):
    assert _by_id(make_repo, PINNED)["action-pinning"].optimized is True


def test_tag_pinned_actions_flagged(make_repo):
    assert _by_id(make_repo, UNPINNED)["action-pinning"].optimized is False


def test_permissions_block_recognized(make_repo):
    assert _by_id(make_repo, PINNED)["token-permissions"].optimized is True
    assert _by_id(make_repo, UNPINNED)["token-permissions"].optimized is False


def test_deprecated_usage_flagged(make_repo):
    found = _by_id(make_repo, DEPRECATED)
    assert found["deprecated-actions"].optimized is False
    # a clean modern workflow passes the same check
    assert _by_id(make_repo, PINNED)["deprecated-actions"].optimized is True


def test_security_findings_have_right_metadata(make_repo):
    found = _by_id(make_repo, UNPINNED)
    assert found["action-pinning"].category == "security"
    assert found["token-permissions"].category == "security"
    assert found["deprecated-actions"].category == "reliability"
    assert found["action-pinning"].min_tier is Tier.GROWING


def test_security_checks_skip_when_not_applicable(make_repo):
    # No workflows at all → security checks should not appear.
    repo = make_repo({"requirements.txt": "pytest>=8\n"})
    ids = {f.rule_id for f in analyze(detect(repo))}
    assert "action-pinning" not in ids
    assert "token-permissions" not in ids
    assert "deprecated-actions" not in ids
