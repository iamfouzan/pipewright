"""Tests for apply (Phase 5 / v0.3).

These use real temporary git repositories but never touch the network:
push and PR creation are turned off, so only the local, deterministic part
(branch + commit + rollback) is exercised.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ciwright.apply import apply_patch, current_branch
from ciwright.detect import detect
from ciwright.patch import build_patch
from ciwright.rules import analyze

SLOW = """\
name: CI
on:
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pytest
"""

FAST = """\
name: CI
on:
  pull_request:
    paths-ignore:
      - '**.md'
concurrency:
  group: ${{ github.ref }}
  cancel-in-progress: true
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'
      - run: pytest -n auto
"""


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)


@pytest.fixture
def git_repo(make_repo):
    """A make_repo that also initializes git with a clean initial commit."""

    def _make(workflow: str) -> Path:
        repo = make_repo(
            {"requirements.txt": "pytest>=8\n", ".github/workflows/ci.yml": workflow}
        )
        _git(["init", "-q"], repo)
        _git(["config", "user.email", "test@example.com"], repo)
        _git(["config", "user.name", "Test"], repo)
        _git(["add", "-A"], repo)
        _git(["commit", "-qm", "init"], repo)
        return repo

    return _make


def _result(repo: Path):
    info = detect(repo)
    return build_patch(info, analyze(info))


def test_apply_creates_branch_and_commits(git_repo):
    repo = git_repo(SLOW)
    base = current_branch(repo)
    outcome = apply_patch(_result(repo), push=False, open_pr=False)

    assert outcome.ok and outcome.committed
    assert outcome.branch and outcome.branch != base
    assert outcome.pushed is False
    # we are now on the new branch, and the file holds the fixes
    assert current_branch(repo) == outcome.branch
    wf = (repo / ".github/workflows/ci.yml").read_text()
    assert "concurrency:" in wf and "paths-ignore:" in wf and "cache: pip" in wf


def test_base_branch_is_untouched(git_repo):
    repo = git_repo(SLOW)
    base = current_branch(repo)
    apply_patch(_result(repo), push=False, open_pr=False)

    _git(["checkout", base], repo)
    wf = (repo / ".github/workflows/ci.yml").read_text()
    assert "concurrency:" not in wf  # the change lives only on the new branch


def test_refuses_outside_git_repo(make_repo):
    repo = make_repo(
        {"requirements.txt": "pytest>=8\n", ".github/workflows/ci.yml": SLOW}
    )
    before = (repo / ".github/workflows/ci.yml").read_text()
    outcome = apply_patch(_result(repo), push=False, open_pr=False)

    assert outcome.ok is False
    assert "git" in outcome.message.lower()
    assert (repo / ".github/workflows/ci.yml").read_text() == before  # untouched


def test_refuses_when_target_file_is_dirty(git_repo):
    repo = git_repo(SLOW)
    base = current_branch(repo)
    (repo / ".github/workflows/ci.yml").write_text(SLOW + "\n# local edit\n")

    outcome = apply_patch(_result(repo), push=False, open_pr=False)

    assert outcome.ok is False
    assert "uncommitted" in outcome.message.lower()
    assert current_branch(repo) == base  # no branch was created


def test_nothing_to_apply_when_already_fast(git_repo):
    repo = git_repo(FAST)
    base = current_branch(repo)
    outcome = apply_patch(_result(repo), push=False, open_pr=False)

    assert outcome.ok is False
    assert "no changes" in outcome.message.lower()
    assert current_branch(repo) == base


def test_applying_twice_is_idempotent(git_repo):
    repo = git_repo(SLOW)
    apply_patch(_result(repo), push=False, open_pr=False)
    # now on the patched branch — a fresh analysis should find nothing to do
    second = apply_patch(_result(repo), push=False, open_pr=False)
    assert second.ok is False
    assert "no changes" in second.message.lower()


def test_branch_name_is_unique(git_repo):
    repo = git_repo(SLOW)
    base = current_branch(repo)
    _git(["branch", "ciwright/ci-tuneup"], repo)  # squat the default name

    outcome = apply_patch(_result(repo), push=False, open_pr=False, branch=None)
    assert outcome.ok
    assert outcome.branch == "ciwright/ci-tuneup-2"

    _git(["checkout", base], repo)
