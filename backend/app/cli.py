"""Command-line interface for CHR Automation"""
import os
import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

app = typer.Typer(help="CHR Automation - God-Tier Edition")
console = Console()

@app.command("db-init")
def db_init():
    """Initialize database with god-tier schema"""
    load_dotenv()
    from app.db.init_db import init_db

    console.print(Panel.fit(
        "[bold cyan]Initializing God-Tier Database Schema[/bold cyan]",
        border_style="cyan"
    ))

    init_db()

    console.print("\n[bold green]✅ Database ready![/bold green]")
    console.print("[dim]You can now run: python -m app.cli run --month 2026-01[/dim]")


@app.command("run")
def run(
    month: str = typer.Option(None, "--month", help="Month to process (YYYY-MM)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Dry run mode"),
    skip_github: bool = typer.Option(False, "--skip-github", help="Skip GitHub fetch (use existing data)")
):
    """Run the complete CHR automation pipeline"""
    load_dotenv()
    from app.core.time_utils import previous_month_yyyymm
    from app.core.orchestrator import PipelineOrchestrator

    run_month = month or previous_month_yyyymm()

    console.print(Panel.fit(
        f"[bold cyan]CHR Automation Pipeline[/bold cyan]\n"
        f"Month: [yellow]{run_month}[/yellow]\n"
        f"Mode: [yellow]{'DRY RUN' if dry_run else 'LIVE'}[/yellow]",
        border_style="cyan"
    ))

    if dry_run:
        console.print("\n[yellow]⚠️  DRY RUN MODE - No changes will be made[/yellow]")
        console.print("[green]✅ Dry run complete![/green]")
        return

    orchestrator = PipelineOrchestrator(run_month=run_month, skip_github=skip_github)
    orchestrator.run()


@app.command("import-history")
def import_history():
    """Fetch ALL historical CHR issues (open + closed) and parse every month into the DB."""
    import os
    from datetime import datetime
    load_dotenv()

    console.print(Panel.fit(
        "[bold cyan]CHR Historical Data Import[/bold cyan]\n"
        "Fetching ALL issues — open and closed (all pages)",
        border_style="cyan"
    ))

    from app.services.github_client import (
        GitHubAPIClient, parse_issue_title,
        get_discrepancies, clear_discrepancies
    )
    from app.parsers.kpi_parser import parse_issue_body
    from app.db.session import get_session
    from app.db.models import ChrIssueSnapshot, ChrKpiValue, ChrKpiWide, RowType, KpiSource
    from app.core.orchestrator import _resolve_row_type
    from app.engine.comparison_engine import run_comparisons

    repo       = os.getenv("GITHUB_REPO", "")
    label      = os.getenv("CHR_LABEL", "Clinic health report")
    token      = os.getenv("GITHUB_TOKEN", "")
    configs_dir = os.getenv("CONFIGS_DIR", "./configs")

    if not repo or not token:
        console.print("[red]❌ GITHUB_REPO or GITHUB_TOKEN not set in .env[/red]")
        raise typer.Exit(1)

    run_id = f"history_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    gh = GitHubAPIClient(token, repo)
    clear_discrepancies()

    # ── Step 1: Fetch ALL issues via REST (no page cap) ─────────────────
    console.print("\n[cyan]Step 1/3:[/cyan] Fetching all issues from GitHub (REST, all pages)...")
    all_items = gh.list_issues_by_label(label)
    console.print(f"  Found [yellow]{len(all_items)}[/yellow] total issues with label '{label}'")

    # Parse titles and group by month
    by_month = {}
    skipped  = 0
    skipped_titles = []

    for item in all_items:
        client_name, month_text, month_yyyymm = parse_issue_title(
            item["title"], issue_number=item.get("number", 0)
        )
        if not month_yyyymm or not client_name:
            skipped += 1
            skipped_titles.append(f"  #{item.get('number','?')}: {item['title']}")
            continue
        by_month.setdefault(month_yyyymm, []).append((client_name, item))

    console.print(f"  [green]✓ Parsed {len(by_month)} distinct months[/green]")
    if skipped:
        console.print(f"  [yellow]⚠  Skipped {skipped} issues (see discrepancy report below)[/yellow]")

    months_sorted = sorted(by_month.keys())
    console.print(f"  Months found: {', '.join(months_sorted)}")

    # ── Step 2: Store snapshots + parse KPIs ────────────────────────────
    console.print("\n[cyan]Step 2/3:[/cyan] Storing snapshots and parsing KPIs...")

    total_issues = 0
    total_kpis   = 0
    total_warn   = 0
    months_done  = []

    for month_yyyymm in months_sorted:
        items = by_month[month_yyyymm]
        console.print(f"\n  [bold]{month_yyyymm}[/bold] — {len(items)} issue(s)")

        with get_session() as session:
            for client_name, item in items:
                issue = gh.get_issue(item["number"])

                # Upsert snapshot
                existing_snap = session.query(ChrIssueSnapshot).filter_by(
                    repo=repo, issue_number=issue.number
                ).first()
                if existing_snap:
                    existing_snap.body_markdown    = issue.body
                    existing_snap.issue_updated_at = issue.updated_at
                    existing_snap.run_month        = month_yyyymm
                    existing_snap.client_name      = client_name
                    existing_snap.run_id           = run_id
                else:
                    session.add(ChrIssueSnapshot(
                        run_month=month_yyyymm,
                        client_name=client_name,
                        repo=repo,
                        issue_number=issue.number,
                        issue_title=issue.title,
                        issue_url=issue.html_url,
                        issue_created_at=issue.created_at,
                        issue_updated_at=issue.updated_at,
                        body_markdown=issue.body,
                        run_id=run_id,
                    ))
                session.commit()

                # Parse KPIs
                iopt_kpis, iasg_kpis, meta = parse_issue_body(issue.body, configs_dir)
                ok = warn = 0

                for kpi_list, source_enum in [
                    (iopt_kpis, KpiSource.IOPTIMIZE),
                    (iasg_kpis, KpiSource.IASSIGN),
                ]:
                    for kpi in kpi_list:
                        row_type = _resolve_row_type(kpi.location_name)
                        existing_kpi = session.query(ChrKpiValue).filter_by(
                            run_month=month_yyyymm,
                            client_name=client_name,
                            location_name=kpi.location_name,
                            source=source_enum,
                            kpi_name=kpi.kpi_name,
                        ).first()
                        if existing_kpi:
                            existing_kpi.value_raw    = kpi.value_raw
                            existing_kpi.value_avg    = kpi.value_avg
                            existing_kpi.value_median = kpi.value_median
                            existing_kpi.run_id       = run_id
                        else:
                            session.add(ChrKpiValue(
                                run_month=month_yyyymm,
                                client_name=client_name,
                                location_name=kpi.location_name,
                                row_type=row_type,
                                source=source_enum,
                                kpi_name=kpi.kpi_name,
                                kpi_display_name=kpi.kpi_display_name,
                                value_raw=kpi.value_raw,
                                value_avg=kpi.value_avg,
                                value_median=kpi.value_median,
                                value_unit=kpi.value_unit,
                                parse_status=kpi.parse_status,
                                parse_notes=kpi.parse_notes,
                                issue_number=issue.number,
                                run_id=run_id,
                            ))
                        if kpi.parse_status == "ok":
                            ok += 1
                        else:
                            warn += 1

                session.commit()
                console.print(
                    f"    [green]✓[/green] {client_name} #{issue.number}: "
                    f"{len(iopt_kpis)} iOpt | {len(iasg_kpis)} iAssign"
                    + (f" [yellow]({warn} warnings)[/yellow]" if warn else "")
                )
                total_issues += 1
                total_kpis   += ok
                total_warn   += warn

        months_done.append(month_yyyymm)

    # ── Step 3: Run comparisons ──────────────────────────────────────────
    console.print(f"\n[cyan]Step 3/3:[/cyan] Running comparisons for all {len(months_done)} months...")

    total_comparisons = 0
    for month_yyyymm in months_done:
        with get_session() as session:
            n = run_comparisons(session, month_yyyymm, run_id)
            total_comparisons += n
        console.print(f"  [green]✓[/green] {month_yyyymm}: {n} comparison rows")

    # ── Summary table ────────────────────────────────────────────────────
    from rich.table import Table as RichTable
    t = RichTable(title="History Import Summary", show_header=True, header_style="bold cyan")
    t.add_column("Metric")
    t.add_column("Value", justify="right")
    t.add_row("Months imported",  str(len(months_done)))
    t.add_row("Issues processed", str(total_issues))
    t.add_row("KPIs stored",      str(total_kpis))
    t.add_row("Parse warnings",   str(total_warn))
    t.add_row("Comparison rows",  str(total_comparisons))
    console.print(t)

    # ── Discrepancy report ───────────────────────────────────────────────
    discrepancies = get_discrepancies()
    if discrepancies:
        console.print(Panel.fit(
            f"[bold yellow]⚠  Discrepancy Report — {len(discrepancies)} issues found[/bold yellow]",
            border_style="yellow"
        ))

        # Group by type
        by_type = {}
        for d in discrepancies:
            by_type.setdefault(d.discrepancy_type, []).append(d)

        for dtype, items in sorted(by_type.items()):
            console.print(f"\n[bold yellow]{dtype}[/bold yellow] ({len(items)} occurrence{'s' if len(items)>1 else ''})")
            for d in items:
                console.print(f"  Issue #{d.issue_number}: {d.issue_title}")
                console.print(f"    Problem : {d.detail}")
                console.print(f"    Handled : {d.how_handled}")

        if skipped_titles:
            console.print(f"\n[bold red]UNRECOGNISED_FORMAT[/bold red] — {len(skipped_titles)} issue(s) skipped entirely:")
            for t_str in skipped_titles:
                console.print(t_str)
    else:
        console.print("\n[green]✅ No discrepancies found — all titles parsed cleanly.[/green]")

    console.print("\n[bold green]✅ History import complete![/bold green]")
    console.print("[dim]Now run: python -m app.cli run --month 2026-01 --skip-github[/dim]")


@app.command("ingest-raw")
def ingest_raw(
    client: str = typer.Option(None, "--client", help="Client code (e.g., DEMO)"),
    path: str = typer.Option(None, "--path", help="Directory containing CSV files"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Parse and validate only"),
    skip_aggregation: bool = typer.Option(False, "--skip-aggregation", help="Skip rollup computation"),
):
    """Ingest raw daily operational CSVs into the chr_raw_* tables + rollups."""
    from datetime import datetime
    load_dotenv()

    if not client or not path:
        console.print("[red]❌ --client and --path are both required[/red]")
        raise typer.Exit(1)

    from app.db.session import get_session
    from app.parsers.raw_data_parser import find_csv_files, ingest_csv
    from app.engine.raw_data_aggregator import compute_rollups

    ingest_id = f"ingest_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    console.print(Panel.fit(
        f"[bold cyan]Raw Data Ingestion[/bold cyan]\n"
        f"Client: [yellow]{client}[/yellow]\n"
        f"Path:   [yellow]{path}[/yellow]\n"
        f"Ingest ID: [yellow]{ingest_id}[/yellow]\n"
        f"Mode: [yellow]{'DRY RUN' if dry_run else 'LIVE'}[/yellow]",
        border_style="cyan"
    ))

    try:
        csv_files = find_csv_files(path)
    except FileNotFoundError as exc:
        console.print(f"[red]❌ {exc}[/red]")
        raise typer.Exit(1)

    if not csv_files:
        console.print("[red]❌ No CSV files found under path[/red]")
        raise typer.Exit(1)

    console.print(f"\n[cyan]Found {len(csv_files)} CSV file(s)[/cyan]")

    from rich.table import Table as RichTable
    results_table = RichTable(
        title="Ingestion Results", show_header=True, header_style="bold cyan"
    )
    results_table.add_column("File")
    results_table.add_column("Type")
    results_table.add_column("Parsed", justify="right")
    results_table.add_column("Inserted", justify="right")
    results_table.add_column("Status")

    type_counts: dict = {}
    total_parsed = 0
    total_inserted = 0

    with get_session() as session:
        for csv_path in csv_files:
            result = ingest_csv(session, client, csv_path, ingest_id, dry_run=dry_run)
            short = csv_path.name
            csv_type = result.csv_type or "[red]UNKNOWN[/red]"
            status = "[green]✓[/green]" if not result.errors else f"[red]✗ {result.errors[0]}[/red]"
            results_table.add_row(
                short, str(csv_type),
                str(result.rows_parsed), str(result.rows_inserted), status,
            )
            total_parsed += result.rows_parsed
            total_inserted += result.rows_inserted
            if result.csv_type:
                type_counts[result.csv_type] = type_counts.get(result.csv_type, 0) + result.rows_inserted

        console.print(results_table)

        if dry_run:
            console.print("\n[yellow]⚠️  DRY RUN — no rows committed, no rollups computed[/yellow]")
            return

        # Aggregation
        if skip_aggregation:
            console.print("\n[yellow]--skip-aggregation set, not computing rollups[/yellow]")
        else:
            console.print("\n[cyan]Computing weekly + monthly rollups...[/cyan]")
            rollup_counts = compute_rollups(session, client, ingest_id)
            rt = RichTable(title="Rollup Summary", show_header=True, header_style="bold cyan")
            rt.add_column("Category × Period")
            rt.add_column("Rows", justify="right")
            for key in sorted(rollup_counts):
                rt.add_row(key, str(rollup_counts[key]))
            console.print(rt)

    # Final summary
    summary = RichTable(title="Ingestion Summary", show_header=True, header_style="bold cyan")
    summary.add_column("Metric")
    summary.add_column("Value", justify="right")
    summary.add_row("CSV files",      str(len(csv_files)))
    summary.add_row("Total parsed",   str(total_parsed))
    summary.add_row("Total inserted", str(total_inserted))
    for t, n in sorted(type_counts.items()):
        summary.add_row(f"  {t}", str(n))
    console.print(summary)

    console.print(f"\n[bold green]✅ Raw data ingest complete![/bold green]")
    console.print(f"[dim]ingest_id = {ingest_id}[/dim]")


if __name__ == "__main__":
    app()