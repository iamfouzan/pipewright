"""The command-line interface.

Commands:
    pipewright detect [PATH]    show what pipewright sees in a repo
    pipewright analyze [PATH]   report tier-relevant CI improvements (read-only)
    pipewright fix [PATH]       preview, or --apply the fixes as a pull request
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from pipewright import __version__
from pipewright.apply import apply_patch
from pipewright.detect import detect as detect_project
from pipewright.patch import build_patch
from pipewright.profile import profile, select_visible
from pipewright.report import (
    render_analysis,
    render_apply,
    render_detect,
    render_fix,
    render_score,
    render_usage,
)
from pipewright.rules import analyze as analyze_project
from pipewright.score import compute_score
from pipewright.usage import (
    estimate_savings,
    load_runs_from_file,
    parse_runs,
    summarize,
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Keep your CI pipelines fast, cheap, secure, and reliable.",
)

_PATH_ARG = typer.Argument(Path("."), help="Path to the repository (default: current dir).")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"pipewright {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """pipewright — a friendly advisor for your CI pipelines."""


def _scan(path: Path):
    """Detect, analyze, profile, and keep only tier-relevant findings."""
    info = detect_project(path)
    tier = profile(info)
    visible = select_visible(analyze_project(info), tier)
    return info, tier, visible


def _infer_repo(path: Path) -> str | None:
    """Read owner/name from the git 'origin' remote, if there is one."""
    import re
    import subprocess

    try:
        url = subprocess.run(
            ["git", "-C", str(path), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None
    m = re.search(r"github\.com[:/]+([^/]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else None


def _fetch_runs_via_gh(repo: str, days: int):
    """Fetch recent workflow runs with the GitHub CLI. Returns None on failure."""
    import json
    import subprocess

    try:
        out = subprocess.run(
            ["gh", "api", f"repos/{repo}/actions/runs?per_page=100"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return None
    try:
        return parse_runs(json.loads(out))
    except (ValueError, KeyError):
        return None


@app.command()
def detect(path: Path = _PATH_ARG) -> None:
    """Show what pipewright sees in this project."""
    render_detect(detect_project(path))


@app.command()
def analyze(path: Path = _PATH_ARG) -> None:
    """Report tier-relevant CI improvements. Read-only — changes nothing."""
    info, tier, visible = _scan(path)
    render_analysis(info, visible, tier=tier)


@app.command()
def score(path: Path = _PATH_ARG) -> None:
    """Show the CI health score per category (speed, cost, security, reliability)."""
    info, tier, visible = _scan(path)
    if not info.has_github_actions:
        typer.echo("No GitHub Actions workflows found — nothing to score yet.")
        raise typer.Exit()
    render_score(compute_score(visible), tier=tier)


@app.command()
def usage(
    path: Path = _PATH_ARG,
    repo: Optional[str] = typer.Option(
        None, "--repo", help="owner/name (defaults to the git 'origin' remote)."
    ),
    from_file: Optional[Path] = typer.Option(
        None,
        "--from-file",
        help="Read runs from a JSON file (e.g. `gh api repos/O/R/actions/runs > runs.json`).",
    ),
    days: int = typer.Option(30, "--days", help="Window of run history to summarize."),
) -> None:
    """Summarize real CI usage from run history, with rough savings estimates."""
    info, _tier, visible = _scan(path)

    if from_file is not None:
        runs = load_runs_from_file(from_file)
    else:
        target = repo or _infer_repo(path)
        runs = _fetch_runs_via_gh(target, days) if target else None

    if runs is None:
        typer.echo(
            "Couldn't load run history. Either:\n"
            "  • pass --from-file runs.json  (gh api repos/OWNER/NAME/actions/runs > runs.json), or\n"
            "  • install the GitHub CLI (gh) and run inside the repo, or pass --repo OWNER/NAME."
        )
        raise typer.Exit(code=1)

    stats = summarize(runs, window_days=days)
    if stats.total_runs == 0:
        typer.echo(f"No completed runs in the last {days} days to summarize.")
        raise typer.Exit()

    render_usage(stats, estimate_savings(stats, visible))


@app.command()
def fix(
    path: Path = _PATH_ARG,
    workflow: Optional[Path] = typer.Option(
        None, "--workflow", "-w", help="Target a specific workflow file."
    ),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--apply",
        help="Preview the changes (default), or --apply to open a pull request.",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the confirmation prompt when applying."
    ),
    no_push: bool = typer.Option(
        False,
        "--no-push",
        help="Commit on a new branch locally, but don't push or open a PR.",
    ),
) -> None:
    """Preview the CI improvements, or --apply them as a pull request."""
    info, _tier, visible = _scan(path)
    result = build_patch(info, visible, override=workflow)

    render_fix(result, dry_run=dry_run)

    if dry_run or not result.changed:
        return

    if not yes and not typer.confirm("\nApply these changes on a new branch?"):
        typer.echo("Cancelled — nothing changed.")
        raise typer.Exit()

    outcome = apply_patch(result, push=not no_push, open_pr=not no_push)
    render_apply(outcome)
    if not outcome.ok:
        raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
