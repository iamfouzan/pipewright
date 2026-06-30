"""Reporter — turn results into readable terminal output."""

from __future__ import annotations

import difflib

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ciwright.apply import ApplyOutcome
from ciwright.models import CATEGORIES, IMPACT_ORDER, Finding, ProjectInfo, Tier
from ciwright.patch import PatchResult
from ciwright.score import ScoreCard, compute_score
from ciwright.usage import Estimate, UsageStats

console = Console()

_IMPACT_STYLE = {"high": "bold red", "medium": "yellow", "low": "dim"}
_CATEGORY_STYLE = {
    "speed": "cyan",
    "cost": "yellow",
    "security": "red",
    "reliability": "blue",
}
_TIER_LABEL = {
    Tier.STARTER: ("Starter", "green"),
    Tier.GROWING: ("Growing", "magenta"),
    Tier.SCALE: ("Scale", "yellow"),
}


def _score_band(score: int | None) -> tuple[str, str]:
    """Lighthouse-style colour bands."""
    if score is None:
        return ("—", "dim")
    if score >= 90:
        return (str(score), "green")
    if score >= 50:
        return (str(score), "yellow")
    return (str(score), "red")


def _score_bar(score: int | None, width: int = 10) -> str:
    if score is None:
        return "·" * width
    filled = round(width * score / 100)
    return "█" * filled + "░" * (width - filled)


def render_score(card: ScoreCard, tier: Tier | None = None) -> None:
    overall, ostyle = _score_band(card.overall)
    title = Text()
    title.append("CI health  ", style="bold")
    title.append(overall, style=f"bold {ostyle}")
    title.append("/100", style="dim")
    console.print(title)

    for category in CATEGORIES:
        cs = card.categories[category]
        score, style = _score_band(cs.score)
        line = Text("  ")
        line.append(f"{category:<12}", style=_CATEGORY_STYLE.get(category, ""))
        if cs.total == 0:
            line.append(_score_bar(None), style="dim")
            line.append("  —  ", style="dim")
            line.append("no checks at this tier", style="dim")
        else:
            line.append(_score_bar(cs.score), style=style)
            line.append(f"  {score:>3}  ", style=f"bold {style}")
            line.append(f"{cs.optimized}/{cs.total} ok", style="dim")
        console.print(line)
    console.print()


def render_usage(stats: UsageStats, estimates: list[Estimate]) -> None:
    body = Text()
    body.append("Measured over the last ", style="dim")
    body.append(f"{stats.window_days} days\n", style="bold")
    body.append("Runs            ", style="bold")
    body.append(f"{stats.total_runs}  ")
    body.append(f"(~{stats.runs_per_week:.0f}/week)\n", style="dim")
    body.append("CI time         ", style="bold")
    body.append(f"{stats.total_minutes:.0f} min  ")
    body.append(f"(~{stats.minutes_per_week:.0f} min/week)\n", style="dim")
    body.append("Per run         ", style="bold")
    body.append(f"avg {stats.avg_minutes:.1f} min, median {stats.median_minutes:.1f} min")
    console.print(Panel(body, title="CI usage", expand=False))

    if stats.by_workflow:
        console.print("[bold]Busiest workflows[/]")
        for wu in stats.by_workflow[:3]:
            console.print(
                f"  {wu.name:<24} [dim]{wu.runs} runs · {wu.minutes:.0f} min[/]"
            )
        console.print()

    if not estimates:
        return

    panel = Text()
    for e in estimates:
        panel.append(f"{e.title}\n", style="bold")
        panel.append(
            f"  ~{e.low_per_run:.1f}–{e.high_per_run:.1f} min/run "
            f"(≈ {e.low_per_week:.0f}–{e.high_per_week:.0f} min/week)\n",
            style="green",
        )
        panel.append(f"  assumes {e.assumption}\n", style="dim")
    console.print(
        Panel(
            panel,
            title="Potential savings — rough estimates",
            border_style="yellow",
            expand=False,
        )
    )
    console.print(
        "[dim]These are estimates with stated assumptions, and they overlap — "
        "don't add them up. The only way to know for sure is to apply a fix and "
        "compare the next few runs.[/]"
    )


def render_detect(info: ProjectInfo) -> None:
    body = Text()
    body.append("Package manager  ", style="bold")
    body.append(f"{info.package_manager or 'unknown'}\n")
    body.append("Test runner      ", style="bold")
    body.append(f"{info.test_runner or 'unknown'}\n")
    body.append("GitHub Actions   ", style="bold")
    body.append(f"{len(info.workflows)} workflow file(s)")
    console.print(Panel(body, title="ciwright · project", expand=False))


def render_analysis(
    info: ProjectInfo, findings: list[Finding], tier: Tier | None = None
) -> None:
    render_detect(info)

    if tier is not None:
        label, style = _TIER_LABEL[tier]
        console.print(f"Pipeline maturity: [bold {style}]{label}[/]\n")

    if not info.has_github_actions:
        console.print(
            "[yellow]No GitHub Actions workflows found — nothing to analyze yet.[/]\n"
            "[dim]Add a workflow under .github/workflows/ and run ciwright again.[/]"
        )
        return

    render_score(compute_score(findings))

    findings = sorted(
        findings, key=lambda f: (f.optimized, IMPACT_ORDER.get(f.impact, 9))
    )

    table = Table(show_lines=False, expand=True, pad_edge=False)
    table.add_column("", width=3, no_wrap=True)
    table.add_column("Check", style="bold", no_wrap=True)
    table.add_column("Area", width=12, no_wrap=True)
    table.add_column("Impact", width=8, no_wrap=True)
    table.add_column("What we found")

    for f in findings:
        if f.optimized:
            mark = Text("ok", style="green")
            impact = Text("—", style="dim")
        else:
            mark = Text("▲", style="bold magenta")
            impact = Text(f.impact, style=_IMPACT_STYLE.get(f.impact, ""))
        area = Text(f.category, style=_CATEGORY_STYLE.get(f.category, ""))
        table.add_row(mark, f.title, area, impact, f.detail)

    console.print(table)

    opportunities = [f for f in findings if f.is_opportunity]
    if opportunities:
        console.print(
            f"\n[bold magenta]{len(opportunities)}[/] improvement(s) available. "
            "[dim]This was read-only — nothing in your repo changed.[/]"
        )
    else:
        console.print("\n[bold green]Nice — this pipeline already looks well tuned.[/]")


def _render_diff(original: str, new: str, filename: str) -> None:
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    )
    out = Text()
    for line in diff:
        line = line.rstrip("\n")
        if line.startswith("+") and not line.startswith("+++"):
            out.append(line + "\n", style="green")
        elif line.startswith("-") and not line.startswith("---"):
            out.append(line + "\n", style="red")
        elif line.startswith("@@"):
            out.append(line + "\n", style="cyan")
        else:
            out.append(line + "\n", style="dim")
    console.print(out)


def render_fix(result: PatchResult, dry_run: bool = True) -> None:
    if result.target is None:
        console.print(f"[yellow]{result.note or 'Nothing to fix.'}[/]")
        _render_manual(result.manual)
        return

    console.print(f"[bold]Target workflow:[/] {result.target.name}")

    if result.note:
        console.print(f"[yellow]{result.note}[/]")
    elif result.changed:
        titles = ", ".join(f.title.lower() for f in result.applied)
        console.print(f"[bold green]Proposed changes[/] — {titles}\n")
        _render_diff(result.original_text, result.new_text, result.target.name)
    else:
        console.print("[green]No safe auto-fixes needed for this workflow.[/]")

    _render_manual(result.manual)

    if result.changed and dry_run:
        console.print(
            "\n[dim]Preview only — nothing was written. "
            "Re-run with [/][bold]--apply[/][dim] to open a pull request.[/]"
        )


def _render_manual(manual: list[Finding]) -> None:
    if not manual:
        return
    body = Text()
    for f in manual:
        body.append(f"• {f.title}\n", style="bold")
        body.append(f"  {f.detail}\n", style="dim")
    console.print(
        Panel(body, title="Do these by hand", border_style="yellow", expand=False)
    )


def render_apply(outcome: ApplyOutcome) -> None:
    if not outcome.ok:
        console.print(f"[yellow]{outcome.message}[/]")
        return

    console.print(
        f"[bold green]Committed[/] the changes on branch "
        f"[bold]{outcome.branch}[/] (off {outcome.base or 'HEAD'})."
    )

    if outcome.pr_url:
        console.print(f"[bold green]Opened pull request:[/] {outcome.pr_url}")
    elif outcome.pushed:
        where = outcome.compare_url or "your Git host"
        console.print(f"Pushed the branch. Open a pull request here:\n  {where}")
    else:
        console.print(
            "[dim]Not pushed (no remote, or push was declined). "
            "Finish when ready:[/]\n"
            f"  git push -u origin {outcome.branch}"
        )
        if outcome.compare_url:
            console.print(f"  then open: {outcome.compare_url}")

    console.print(
        f"\n[dim]You're now on [/][bold]{outcome.branch}[/][dim]. "
        f"Switch back with [/]git checkout {outcome.base or 'main'}[dim].[/]"
    )
