"""Detector — read a repository and figure out what it's made of.

Everything here is read-only. We never write to the user's repo.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from pipewright.models import ProjectInfo


def _read_pyproject(root: Path) -> dict:
    """Parse pyproject.toml if present; return {} on any problem."""
    path = root / "pyproject.toml"
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (tomllib.TOMLDecodeError, OSError):
        return {}


def detect_package_manager(root: Path, pyproject: dict | None = None) -> str | None:
    """Pick the most specific package manager we can prove.

    Order matters: uv / poetry / pipenv are checked before plain pip,
    because a uv or poetry project usually *also* looks like a pip project.
    """
    if pyproject is None:
        pyproject = _read_pyproject(root)
    tool = pyproject.get("tool", {}) if isinstance(pyproject, dict) else {}

    if (root / "uv.lock").is_file() or "uv" in tool:
        return "uv"
    if (root / "poetry.lock").is_file() or "poetry" in tool:
        return "poetry"
    if (root / "Pipfile").is_file():
        return "pipenv"
    if (
        "project" in pyproject
        or (root / "requirements.txt").is_file()
        or any(root.glob("requirements*.txt"))
        or (root / "setup.py").is_file()
        or (root / "setup.cfg").is_file()
    ):
        return "pip"
    return None


def detect_test_runner(root: Path, pyproject: dict | None = None) -> str | None:
    """Decide whether this project uses pytest, unittest, or neither."""
    if pyproject is None:
        pyproject = _read_pyproject(root)
    tool = pyproject.get("tool", {}) if isinstance(pyproject, dict) else {}

    if "pytest" in tool:
        return "pytest"
    if (root / "pytest.ini").is_file() or (root / "conftest.py").is_file():
        return "pytest"
    if any(root.rglob("conftest.py")):
        return "pytest"

    # Look at declared dependencies for an explicit pytest entry.
    blob_parts: list[str] = []
    project = pyproject.get("project", {}) if isinstance(pyproject, dict) else {}
    blob_parts.extend(project.get("dependencies", []) or [])
    for group in (project.get("optional-dependencies", {}) or {}).values():
        blob_parts.extend(group)
    req = root / "requirements.txt"
    if req.is_file():
        try:
            blob_parts.append(req.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            pass
    if "pytest" in " ".join(blob_parts):
        return "pytest"

    # Last resort: there are test files, but no pytest signal.
    if any(root.rglob("test_*.py")) or any(root.rglob("*_test.py")):
        return "unittest"
    return None


def find_workflows(root: Path) -> list[Path]:
    """Return the GitHub Actions workflow files, sorted by name."""
    wf_dir = root / ".github" / "workflows"
    if not wf_dir.is_dir():
        return []
    return sorted(
        p
        for p in wf_dir.iterdir()
        if p.is_file() and p.suffix in {".yml", ".yaml"}
    )


def detect(root: Path | str) -> ProjectInfo:
    """Run every detector and bundle the result."""
    root = Path(root)
    pyproject = _read_pyproject(root)
    return ProjectInfo(
        root=root,
        package_manager=detect_package_manager(root, pyproject),
        test_runner=detect_test_runner(root, pyproject),
        workflows=find_workflows(root),
    )
