"""Tests for the detector."""

from __future__ import annotations

from ciwright.detect import detect


def test_detects_uv(make_repo):
    repo = make_repo({"uv.lock": "", "pyproject.toml": "[project]\nname='x'\n"})
    info = detect(repo)
    assert info.package_manager == "uv"


def test_detects_poetry(make_repo):
    repo = make_repo(
        {"poetry.lock": "", "pyproject.toml": "[tool.poetry]\nname='x'\n"}
    )
    assert detect(repo).package_manager == "poetry"


def test_detects_pipenv(make_repo):
    repo = make_repo({"Pipfile": "[packages]\n"})
    assert detect(repo).package_manager == "pipenv"


def test_detects_pip_from_requirements(make_repo):
    repo = make_repo({"requirements.txt": "rich\n"})
    assert detect(repo).package_manager == "pip"


def test_unknown_when_empty(make_repo):
    repo = make_repo({"README.md": "hi"})
    assert detect(repo).package_manager is None


def test_detects_pytest_from_pyproject(make_repo):
    repo = make_repo(
        {"pyproject.toml": "[tool.pytest.ini_options]\ntestpaths=['tests']\n"}
    )
    assert detect(repo).test_runner == "pytest"


def test_detects_pytest_from_dependency(make_repo):
    repo = make_repo({"requirements.txt": "pytest>=8\n"})
    assert detect(repo).test_runner == "pytest"


def test_finds_workflows(make_repo):
    repo = make_repo(
        {
            ".github/workflows/ci.yml": "name: ci\n",
            ".github/workflows/release.yaml": "name: release\n",
            ".github/workflows/notes.txt": "ignore me",
        }
    )
    info = detect(repo)
    assert info.has_github_actions
    assert [p.name for p in info.workflows] == ["ci.yml", "release.yaml"]


def test_no_workflows(make_repo):
    repo = make_repo({"pyproject.toml": "[project]\nname='x'\n"})
    assert detect(repo).has_github_actions is False
