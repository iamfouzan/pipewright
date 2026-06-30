"""Tests for the patcher (Phase 4)."""

from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

from ciwright.detect import detect
from ciwright.patch import build_patch, primary_workflow
from ciwright.rules import analyze

_safe = YAML(typ="safe")

SLOW = """\
name: CI
on:                    # keep this comment
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


def _patch(make_repo, workflow: str, extra: dict | None = None):
    files = {"requirements.txt": "pytest>=8\n", ".github/workflows/ci.yml": workflow}
    files.update(extra or {})
    repo = make_repo(files)
    info = detect(repo)
    return build_patch(info, analyze(info))


def test_slow_workflow_gets_three_safe_fixes(make_repo):
    result = _patch(make_repo, SLOW)
    applied = {f.rule_id for f in result.applied}
    assert applied == {"dependency-caching", "path-filters", "cancel-superseded-runs"}
    assert result.changed


def test_patched_output_is_valid_yaml_with_the_fixes(make_repo):
    result = _patch(make_repo, SLOW)
    doc = _safe.load(result.new_text)
    assert doc["on"]["pull_request"]["paths-ignore"] == ["**.md", "docs/**"]
    assert doc["concurrency"]["cancel-in-progress"] is True
    steps = doc["jobs"]["test"]["steps"]
    setup = next(s for s in steps if str(s.get("uses", "")).startswith("actions/setup-python"))
    assert setup["with"]["cache"] == "pip"


def test_comments_are_preserved(make_repo):
    result = _patch(make_repo, SLOW)
    assert "# keep this comment" in result.new_text


def test_already_fast_workflow_changes_nothing(make_repo):
    result = _patch(make_repo, FAST)
    assert result.changed is False
    assert result.applied == []


def test_patching_is_idempotent(make_repo):
    # Apply once, write it back, and confirm a second pass adds nothing.
    repo = make_repo(
        {"requirements.txt": "pytest>=8\n", ".github/workflows/ci.yml": SLOW}
    )
    info = detect(repo)
    first = build_patch(info, analyze(info))
    (repo / ".github/workflows/ci.yml").write_text(first.new_text, encoding="utf-8")
    info2 = detect(repo)
    second = build_patch(info2, analyze(info2))
    assert second.changed is False


def test_test_rules_are_advisory_not_auto_applied(make_repo):
    result = _patch(make_repo, SLOW)
    manual_ids = {f.rule_id for f in result.manual}
    assert "parallel-tests" in manual_ids
    assert "test-splitting" in manual_ids


def test_uv_caching_is_advisory_not_auto_applied(make_repo):
    # setup-python's cache: doesn't cover uv, so we must not auto-patch it.
    result = _patch(make_repo, SLOW, extra={"uv.lock": ""})
    applied = {f.rule_id for f in result.applied}
    manual = {f.rule_id for f in result.manual}
    assert "dependency-caching" not in applied
    assert "dependency-caching" in manual


def test_list_form_triggers_do_not_crash(make_repo):
    wf = "name: CI\non: [push, pull_request]\njobs:\n  t:\n    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n"
    result = _patch(make_repo, wf)
    # path-filters can't be safely added to list form, so it stays manual.
    assert "path-filters" in {f.rule_id for f in result.manual}
    # still valid YAML
    _safe.load(result.new_text)


def test_no_workflow_reports_a_note(make_repo):
    repo = make_repo({"requirements.txt": "pytest>=8\n"})
    info = detect(repo)
    result = build_patch(info, analyze(info))
    assert result.target is None
    assert result.note


def test_primary_workflow_override_by_filename(make_repo):
    repo = make_repo(
        {
            ".github/workflows/ci.yml": SLOW,
            ".github/workflows/release.yml": "name: release\non: [push]\n",
        }
    )
    info = detect(repo)
    chosen = primary_workflow(info, override=Path("release.yml"))
    assert chosen is not None and chosen.name == "release.yml"
