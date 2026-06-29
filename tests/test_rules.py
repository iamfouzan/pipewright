"""Tests for the read-only rules engine."""

from __future__ import annotations

from pipewright.detect import detect
from pipewright.rules import analyze

# A workflow that does everything the slow way.
SLOW_WORKFLOW = """\
name: CI
on:
  push:
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: pytest
"""

# A workflow with every safe speed-up already applied.
FAST_WORKFLOW = """\
name: CI
on:
  pull_request:
    paths-ignore:
      - '**.md'
      - 'docs/**'
permissions:
  contents: read
concurrency:
  group: ${{ github.ref }}
  cancel-in-progress: true
jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    strategy:
      matrix:
        group: [1, 2]
    steps:
      - uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11 # v4.1.1
      - uses: actions/setup-python@0a5c61591373683505ea898e09a3ea4f39ef2b9c # v5.0.0
        with:
          python-version: '3.12'
          cache: 'pip'
      - run: pip install -r requirements.txt pytest-xdist pytest-split
      - run: pytest -n auto --splits 2 --group ${{ matrix.group }}
"""

BASE = {"requirements.txt": "pytest>=8\n"}


def _findings(make_repo, workflow: str) -> dict[str, bool]:
    repo = make_repo({**BASE, ".github/workflows/ci.yml": workflow})
    info = detect(repo)
    return {f.rule_id: f.optimized for f in analyze(info)}


def test_slow_workflow_flags_every_opportunity(make_repo):
    opt = _findings(make_repo, SLOW_WORKFLOW)
    assert opt["dependency-caching"] is False
    assert opt["cancel-superseded-runs"] is False
    assert opt["path-filters"] is False
    assert opt["parallel-tests"] is False
    assert opt["test-splitting"] is False


def test_fast_workflow_is_all_clear(make_repo):
    opt = _findings(make_repo, FAST_WORKFLOW)
    assert all(opt.values()), f"expected all optimized, got {opt}"


def test_on_key_is_not_eaten_by_yaml(make_repo):
    # Regression guard: the `on:` block must be readable so path filters work.
    opt = _findings(make_repo, FAST_WORKFLOW)
    assert opt["path-filters"] is True


def test_pytest_rules_skipped_without_pytest(make_repo):
    no_pytest = """\
name: CI
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo build
"""
    repo = make_repo({"README.md": "x", ".github/workflows/ci.yml": no_pytest})
    info = detect(repo)
    ids = {f.rule_id for f in analyze(info)}
    assert "parallel-tests" not in ids
    assert "test-splitting" not in ids


def test_no_workflows_returns_general_rules_only(make_repo):
    repo = make_repo(BASE)
    info = detect(repo)
    findings = analyze(info)
    # With no workflow files, every general check reports "not optimized".
    assert all(f.optimized is False for f in findings)
