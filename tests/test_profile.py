"""Tests for the profiler (tiers), tier filtering, and the v1 checks."""

from __future__ import annotations

from ciwright.detect import detect
from ciwright.models import Tier
from ciwright.profile import profile, select_visible
from ciwright.rules import analyze

ONE_JOB = """\
name: CI
on:
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: pytest
"""

MATRIX = """\
name: CI
on:
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python: ['3.11', '3.12']
    steps:
      - run: pytest
"""

DOCKER = """\
name: CI
on:
  push:
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: docker/build-push-action@v5
"""


def _info(make_repo, workflow, extra=None):
    files = {"requirements.txt": "pytest>=8\n", ".github/workflows/ci.yml": workflow}
    files.update(extra or {})
    return detect(make_repo(files))


# --- tier classification ----------------------------------------------


def test_one_job_is_starter(make_repo):
    assert profile(_info(make_repo, ONE_JOB)) is Tier.STARTER


def test_matrix_is_growing(make_repo):
    assert profile(_info(make_repo, MATRIX)) is Tier.GROWING


def test_docker_is_scale(make_repo):
    assert profile(_info(make_repo, DOCKER)) is Tier.SCALE


def test_many_files_is_scale(make_repo):
    info = _info(
        make_repo,
        ONE_JOB,
        extra={
            ".github/workflows/lint.yml": ONE_JOB,
            ".github/workflows/release.yml": ONE_JOB,
        },
    )
    assert profile(info) is Tier.SCALE


# --- tier filtering ----------------------------------------------------


def test_starter_hides_advanced_findings(make_repo):
    info = _info(make_repo, ONE_JOB)
    findings = analyze(info)
    visible = select_visible(findings, Tier.STARTER)
    ids = {f.rule_id for f in visible}
    # starter shows the three basics, and never the scale-tier ones
    assert "dependency-caching" in ids
    assert "test-splitting" not in ids
    assert "parallel-tests" not in ids  # parallel is a growing-tier concern


def test_scale_shows_everything_relevant(make_repo):
    info = _info(make_repo, MATRIX)
    visible = select_visible(analyze(info), Tier.SCALE)
    ids = {f.rule_id for f in visible}
    assert "parallel-tests" in ids and "test-splitting" in ids


# --- the new checks ----------------------------------------------------


def test_timeouts_flagged_when_missing(make_repo):
    info = _info(make_repo, ONE_JOB)
    opt = {f.rule_id: f.optimized for f in analyze(info)}
    assert opt["job-timeouts"] is False


def test_double_trigger_only_when_both_present(make_repo):
    both = ONE_JOB.replace("on:\n  pull_request:", "on:\n  push:\n  pull_request:")
    ids_both = {f.rule_id for f in analyze(_info(make_repo, both))}
    ids_single = {f.rule_id for f in analyze(_info(make_repo, ONE_JOB))}
    assert "double-run-trigger" in ids_both
    assert "double-run-trigger" not in ids_single


def test_docker_cache_check_appears_only_with_docker(make_repo):
    ids_docker = {f.rule_id for f in analyze(_info(make_repo, DOCKER))}
    ids_plain = {f.rule_id for f in analyze(_info(make_repo, ONE_JOB))}
    assert "docker-layer-cache" in ids_docker
    assert "docker-layer-cache" not in ids_plain


def test_findings_carry_category_and_tier(make_repo):
    info = _info(make_repo, MATRIX)
    by_id = {f.rule_id: f for f in analyze(info)}
    assert by_id["dependency-caching"].category == "speed"
    assert by_id["dependency-caching"].min_tier is Tier.STARTER
    assert by_id["job-timeouts"].category == "cost"
    assert by_id["test-splitting"].min_tier is Tier.SCALE
