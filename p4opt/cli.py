"""P4CIOptimizer CLI — `p4opt select | run | report | seed | init`."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from p4opt import db as dbmod
from p4opt.runner import record_changeset, record_run, run_pytest
from p4opt.selector import select_tests
from p4opt.vcs import get_adapter

app = typer.Typer(
    name="p4opt",
    help="P4CIOptimizer — Test smarter, ship faster.",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()


# ---------- helpers ----------------------------------------------------------

def _open_db(project_root: Path):
    dbmod.init_db(project_root)
    return dbmod.connect(project_root)


def _fmt_time(seconds: float) -> str:
    """Human-readable duration: 3.2s, 45s, 3m12s, 1h05m."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        m, s = divmod(int(seconds), 60)
        return f"{m}m{s:02d}s"
    h, rem = divmod(int(seconds), 3600)
    m = rem // 60
    return f"{h}h{m:02d}m"


def _resolve_changeset(vcs: str, ref_from: Optional[str], ref_to: Optional[str],
                       changelist: Optional[str], cwd: Optional[Path] = None):
    adapter = get_adapter(vcs)
    return adapter.get_changeset(
        ref_from=ref_from, ref_to=ref_to, changelist=changelist,
        cwd=str(cwd) if cwd else None,
    )


def _print_changeset(cs):
    console.print(
        Panel.fit(
            f"[bold]Changeset[/bold] {cs.id}\n"
            f"[dim]vcs={cs.vcs} from={cs.ref_from} to={cs.ref_to}[/dim]\n"
            f"[bold]{len(cs.files)} changed file(s)[/bold]",
            border_style="cyan",
        )
    )
    if cs.files:
        for f in cs.files:
            console.print(f"  [yellow]*[/yellow] {f}")


# ---------- commands ---------------------------------------------------------

@app.command()
def init(
    project: Path = typer.Option(Path.cwd(), "--project", "-p", help="Project root"),
):
    """Initialize the SQLite database in the project root."""
    dbmod.init_db(project)
    console.print(f"[green][OK][/green] Initialized DB at [bold]{dbmod.db_path(project)}[/bold]")


@app.command()
def select(
    vcs: str = typer.Option("git", "--vcs", help="Version control system: git | p4"),
    ref_from: Optional[str] = typer.Option(None, "--from", help="git: from-ref (default HEAD~1)"),
    ref_to: Optional[str] = typer.Option(None, "--to", help="git: to-ref (default HEAD)"),
    changelist: Optional[str] = typer.Option(None, "--cl", help="p4 changelist number"),
    files: Optional[str] = typer.Option(
        None, "--files",
        help="Comma-separated changed files (bypasses VCS — handy for demos / CI dry-runs).",
    ),
    project: Path = typer.Option(Path.cwd(), "--project", "-p", help="Project root"),
    threshold: float = typer.Option(0.2, "--threshold", help="Min score to include a test"),
    explain: bool = typer.Option(False, "--explain", help="Show scores and reasons"),
):
    """Select tests to run, given a code change."""
    if files:
        from p4opt.vcs.base import Changeset
        file_list = tuple(f.strip() for f in files.split(",") if f.strip())
        cs = Changeset(
            id=f"manual:{','.join(file_list)[:32]}",
            vcs="manual", ref_from=None, ref_to=None, files=file_list,
        )
    else:
        cs = _resolve_changeset(vcs, ref_from, ref_to, changelist, cwd=project)
    _print_changeset(cs)

    conn = _open_db(project)
    scored = select_tests(
        changed_files=list(cs.files),
        project_root=project,
        conn=conn,
        threshold=threshold,
    )

    if not scored:
        console.print("[yellow]No tests matched (try lowering --threshold).[/yellow]")
        return

    table = Table(title=f"Smart selection — {len(scored)} tests", show_lines=False)
    table.add_column("#", style="dim", width=4)
    table.add_column("Test", style="cyan")
    table.add_column("Score", justify="right", style="bold green")
    if explain:
        table.add_column("Why", style="dim")
    for i, s in enumerate(scored, 1):
        if explain:
            table.add_row(str(i), s.test_id, f"{s.score:.2f}", " | ".join(s.reasons))
        else:
            table.add_row(str(i), s.test_id, f"{s.score:.2f}")
    console.print(table)


@app.command()
def run(
    vcs: str = typer.Option("git", "--vcs"),
    ref_from: Optional[str] = typer.Option(None, "--from"),
    ref_to: Optional[str] = typer.Option(None, "--to"),
    changelist: Optional[str] = typer.Option(None, "--cl"),
    files: Optional[str] = typer.Option(
        None, "--files",
        help="Comma-separated changed files (bypasses VCS — for demos / CI dry-runs).",
    ),
    project: Path = typer.Option(Path.cwd(), "--project", "-p"),
    threshold: float = typer.Option(0.2, "--threshold"),
    full: bool = typer.Option(False, "--full", help="Ignore selection; run the whole suite"),
    estimate_full_s: float = typer.Option(
        0.0,
        "--estimate-full-s",
        help="Optional: known full-suite wall time for time-saved math (else estimated from history).",
    ),
):
    """Run the smart-selected subset (or full suite with --full)."""
    if files:
        from p4opt.vcs.base import Changeset
        file_list = tuple(f.strip() for f in files.split(",") if f.strip())
        cs = Changeset(
            id=f"manual:{','.join(file_list)[:32]}",
            vcs="manual", ref_from=None, ref_to=None, files=file_list,
        )
    else:
        cs = _resolve_changeset(vcs, ref_from, ref_to, changelist, cwd=project)
    _print_changeset(cs)

    conn = _open_db(project)
    record_changeset(conn, cs)
    conn.commit()

    if full:
        targets: list[str] | None = None
        console.print("[bold]Running FULL suite…[/bold]")
    else:
        scored = select_tests(
            changed_files=list(cs.files),
            project_root=project,
            conn=conn,
            threshold=threshold,
        )
        if not scored:
            console.print("[yellow]No tests selected. Aborting (use --full to override).[/yellow]")
            return
        targets = [s.test_id for s in scored]
        console.print(f"[bold]Running {len(targets)} selected test file(s)…[/bold]")

    result = run_pytest(project, test_targets=targets)
    record_run(conn, result, changeset_id=cs.id)
    conn.commit()

    # Estimate full-suite time if not provided
    if estimate_full_s <= 0:
        from p4opt.selector.mapper import discover_tests
        total_files = len(discover_tests(project))
        if targets and total_files:
            est = result.wall_time_s * (total_files / max(1, len(targets)))
        else:
            est = result.wall_time_s
    else:
        est = estimate_full_s

    if targets:
        saved = max(0.0, est - result.wall_time_s)
        pct = (saved / est * 100.0) if est > 0 else 0.0
        passed = sum(1 for o in result.outcomes if o.status == "passed")
        failed = sum(1 for o in result.outcomes if o.status == "failed")
        console.print(Panel.fit(
            f"[bold green]Ran {len(result.outcomes)} tests in {result.wall_time_s:.2f}s[/bold green]\n"
            f"[dim]Estimated full-suite time: ~{est:.1f}s[/dim]\n"
            f"[bold yellow]Saved {saved:.1f}s ({pct:.0f}%)[/bold yellow]\n"
            f"passed={passed}  failed={failed}",
            title="Smart Run Result", border_style="green",
        ))
    else:
        console.print(f"[green]Full suite ran in {result.wall_time_s:.2f}s[/green]")

    raise typer.Exit(code=result.exit_code)


@app.command()
def ci(
    ref_from: str = typer.Option(..., "--from", help="Base ref/SHA (PR base)"),
    ref_to: str = typer.Option(..., "--to", help="Head ref/SHA (PR head)"),
    vcs: str = typer.Option("git", "--vcs"),
    project: Path = typer.Option(Path.cwd(), "--project", "-p"),
    threshold: float = typer.Option(0.2, "--threshold"),
    compare: bool = typer.Option(
        False, "--compare",
        help="Also run the full suite for a side-by-side timing comparison (demo flag).",
    ),
    pythonpath: Optional[str] = typer.Option(
        None, "--pythonpath",
        help="Prepend this path to PYTHONPATH when running pytest (e.g. 'src' for projects that aren't pip-installed).",
    ),
    pytest_arg: list[str] = typer.Option(
        [], "--pytest-arg",
        help="Extra arg to pass through to pytest (repeatable). Example: --pytest-arg=--override-ini=filterwarnings=",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Skip executing pytest; print the selection + projected savings only. Use with --baseline-s.",
    ),
    baseline_s: float = typer.Option(
        0.0, "--baseline-s",
        help="Known full-suite wall time (seconds). Used by --dry-run; also overrides --compare's measured full time.",
    ),
    subset_estimate_s: float = typer.Option(
        0.0, "--subset-estimate-s",
        help="Estimated wall time for the smart subset (seconds). Default = baseline * (selected/total).",
    ),
):
    """CI entry point: run smart subset, optionally compare against full suite.

    Exit code is non-zero only if a smart-selected test failed (full-suite
    failures are informational when --compare is on).
    """
    cs = _resolve_changeset(vcs, ref_from, ref_to, None, cwd=project)
    _print_changeset(cs)

    conn = _open_db(project)
    record_changeset(conn, cs)
    conn.commit()

    scored = select_tests(
        changed_files=list(cs.files),
        project_root=project,
        conn=conn,
        threshold=threshold,
    )
    smart_targets = [s.test_id for s in scored] if scored else []

    from p4opt.selector.mapper import discover_tests
    all_tests = discover_tests(project)

    env_extra = {"PYTHONPATH": pythonpath} if pythonpath else None
    extra_args = list(pytest_arg) if pytest_arg else None

    # --- Dry-run: selection + projected savings only, no pytest execution. ---
    if dry_run:
        total = len(all_tests)
        sel = len(smart_targets)
        if baseline_s <= 0:
            console.print("[yellow]--dry-run requires --baseline-s for a savings figure. Showing selection only.[/yellow]")
            baseline_s_disp = 0.0
            subset_disp = 0.0
        else:
            baseline_s_disp = baseline_s
            subset_disp = subset_estimate_s if subset_estimate_s > 0 else (
                baseline_s * (sel / total) if total else 0.0
            )
        saved = max(0.0, baseline_s_disp - subset_disp)
        pct = (saved / baseline_s_disp * 100.0) if baseline_s_disp > 0 else 0.0
        console.print(Panel.fit(
            f"[bold]Full suite (recorded):[/bold]  {total} tests in {_fmt_time(baseline_s_disp)}\n"
            f"[bold green]Smart subset (projected):[/bold green] {sel} test files in ~{_fmt_time(subset_disp)}\n"
            f"[bold yellow]Saved ~{_fmt_time(saved)} ({pct:.0f}%)[/bold yellow]\n"
            f"[dim]Dry run — no tests executed. Selection accuracy is real; timings are estimates.[/dim]",
            title="Smart Selection (dry-run)", border_style="cyan",
        ))
        raise typer.Exit(code=0)

    # --- Optional: full suite baseline ---
    full_result = None
    if compare:
        console.print("[bold]Running FULL suite for baseline…[/bold]")
        full_result = run_pytest(
            project, test_targets=None,
            extra_args=extra_args, env_extra=env_extra,
        )
        # Record the full run as well, so history captures it.
        record_run(conn, full_result, changeset_id=cs.id)
        conn.commit()

    # --- Smart subset ---
    if not smart_targets:
        console.print("[yellow]No tests passed the selection threshold.[/yellow]")
        if compare and full_result is not None:
            console.print(Panel.fit(
                f"[bold]Full suite:[/bold] {len(full_result.outcomes)} tests in "
                f"{full_result.wall_time_s:.2f}s\n"
                f"[bold]Smart subset:[/bold] 0 tests (threshold {threshold})\n"
                f"[bold yellow]Saved {full_result.wall_time_s:.1f}s (100%)[/bold yellow]",
                title="Smart Run vs Full Suite", border_style="yellow",
            ))
        raise typer.Exit(code=0)

    console.print(f"[bold]Running {len(smart_targets)} smart-selected test file(s)…[/bold]")
    smart_result = run_pytest(
        project, test_targets=smart_targets,
        extra_args=extra_args, env_extra=env_extra,
    )
    record_run(conn, smart_result, changeset_id=cs.id)
    conn.commit()

    smart_passed = sum(1 for o in smart_result.outcomes if o.status == "passed")
    smart_failed = sum(1 for o in smart_result.outcomes if o.status == "failed")
    smart_total = len(smart_result.outcomes)

    # --- Banner ---
    if compare and full_result is not None:
        full_total = len(full_result.outcomes)
        full_passed = sum(1 for o in full_result.outcomes if o.status == "passed")
        full_failed = sum(1 for o in full_result.outcomes if o.status == "failed")
        saved = max(0.0, full_result.wall_time_s - smart_result.wall_time_s)
        pct = (saved / full_result.wall_time_s * 100.0) if full_result.wall_time_s > 0 else 0.0
        console.print(Panel.fit(
            f"[bold]Full suite:[/bold]    {full_total} tests in {full_result.wall_time_s:.2f}s   "
            f"[dim](passed={full_passed} failed={full_failed})[/dim]\n"
            f"[bold]Smart subset:[/bold]  {smart_total} tests in {smart_result.wall_time_s:.2f}s   "
            f"[dim](passed={smart_passed} failed={smart_failed})[/dim]\n"
            f"[bold yellow]Saved {saved:.1f}s ({pct:.0f}%)[/bold yellow]\n"
            f"[dim]Discovered test files: {len(all_tests)}  |  Smart-selected: "
            f"{len(smart_targets)}[/dim]",
            title="Smart Run vs Full Suite", border_style="green",
        ))
    else:
        # Estimate full-suite time from average per-test cost in smart run.
        if smart_total and all_tests:
            est = smart_result.wall_time_s * (len(all_tests) / max(1, len(smart_targets)))
            saved = max(0.0, est - smart_result.wall_time_s)
            pct = (saved / est * 100.0) if est > 0 else 0.0
        else:
            est = smart_result.wall_time_s
            saved = 0.0
            pct = 0.0
        console.print(Panel.fit(
            f"[bold green]Smart subset:[/bold green]  {smart_total} tests in "
            f"{smart_result.wall_time_s:.2f}s\n"
            f"[dim]Estimated full-suite time: ~{est:.1f}s[/dim]\n"
            f"[bold yellow]Saved ~{saved:.1f}s ({pct:.0f}%)[/bold yellow]\n"
            f"passed={smart_passed}  failed={smart_failed}",
            title="CI Smart Run", border_style="green",
        ))

    # Exit code reflects ONLY smart-subset health (production gate).
    raise typer.Exit(code=1 if smart_failed > 0 else 0)


@app.command()
def report(
    project: Path = typer.Option(Path.cwd(), "--project", "-p"),
    section: Optional[str] = typer.Option(
        None, "--section",
        help="degradation | slow | flaky (omit to launch the Streamlit dashboard)",
    ),
):
    """Show CLI report or launch the Streamlit dashboard."""
    if section is None:
        # Launch Streamlit
        app_path = Path(__file__).parent / "dashboard" / "app.py"
        console.print("[bold]Launching dashboard at http://localhost:8501 …[/bold]")
        subprocess.run(
            [sys.executable, "-m", "streamlit", "run", str(app_path),
             "--", "--project", str(project)],
            check=False,
        )
        return

    conn = _open_db(project)
    from p4opt.monitor.degradation import detect_degrading, detect_flaky, detect_slow

    section = section.lower()
    if section == "degradation":
        rows = detect_degrading(conn)
        if not rows:
            console.print("[green][OK] No degrading tests.[/green]")
            return
        table = Table(title="Degrading tests (last 30 days)")
        table.add_column("Test", style="cyan")
        table.add_column("Slope (ms/day)", justify="right", style="bold red")
        table.add_column("First->Last (ms)", justify="right")
        table.add_column("p-value", justify="right", style="dim")
        table.add_column("N", justify="right", style="dim")
        for d in rows:
            table.add_row(
                d.test_id, f"+{d.slope_ms_per_day:.1f}",
                f"{d.first_ms:.0f} -> {d.last_ms:.0f}",
                f"{d.p_value:.3f}", str(d.n_points),
            )
        console.print(table)
    elif section == "slow":
        rows = detect_slow(conn)
        if not rows:
            console.print("[green][OK] No slow tests above p95 threshold.[/green]")
            return
        table = Table(title="Slow tests (median above suite p95)")
        table.add_column("Test", style="cyan")
        table.add_column("Median (ms)", justify="right", style="bold yellow")
        table.add_column("p95 threshold", justify="right", style="dim")
        for s in rows:
            table.add_row(s.test_id, f"{s.median_ms:.0f}", f"{s.p95_threshold:.0f}")
        console.print(table)
    elif section == "flaky":
        rows = detect_flaky(conn)
        if not rows:
            console.print("[green][OK] No flaky tests detected.[/green]")
            return
        table = Table(title="Flaky tests (last 20 runs)")
        table.add_column("Test", style="cyan")
        table.add_column("Pass rate", justify="right", style="bold magenta")
        table.add_column("N", justify="right", style="dim")
        for f in rows:
            table.add_row(f.test_id, f"{f.pass_rate*100:.0f}%", str(f.n_runs))
        console.print(table)
    else:
        console.print(f"[red]Unknown section: {section}[/red]")
        raise typer.Exit(1)


@app.command()
def seed(
    project: Path = typer.Option(Path.cwd(), "--project", "-p"),
    days: int = typer.Option(60, "--days"),
    seed: int = typer.Option(42, "--seed"),
):
    """Populate the DB with synthetic history (for demo)."""
    from p4opt.scripts.seed_history import seed_history
    dbmod.init_db(project)
    n = seed_history(project, days=days, rng_seed=seed)
    console.print(f"[green][OK][/green] Seeded {n} test runs across {days} days.")


if __name__ == "__main__":
    app()
