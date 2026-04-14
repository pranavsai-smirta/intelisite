"""
Quick smoke test for Steps 1 & 2.
Usage:
  cd CHR-AUTOMATION-V2
  python test_fetcher.py --month 2026-01
  python test_fetcher.py --month 2026-01 --client NYOH   # single client only
  python test_fetcher.py --parse-only                    # skip GitHub, test parser on dummy data
"""
import os
import sys
import argparse
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv()
console = Console()


# ── CLI args ────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="CHR fetcher/parser smoke test")
parser.add_argument("--month",      default="2026-01", help="YYYY-MM")
parser.add_argument("--client",     default=None,      help="Filter to one client (e.g. NYOH)")
parser.add_argument("--parse-only", action="store_true", help="Skip GitHub, use dummy markdown")
args = parser.parse_args()


# ── PARSE-ONLY mode: test parser on synthetic markdown ──────────────────────
DUMMY_MARKDOWN = """
## iOptimize stats

| Clinic | Scheduler Complaince | Avg delay in mins/day (Median) | Avg # treatments/day past Tx close (Median) (Overime patients per day) | Avg treatment mins/day/patient past Tx close (Median)(Overtime per patient) | Avg chair utilization (Median) |
| --- | --- | --- | --- | --- | --- |
| A210 | 61.06% | 16.29(15.82) | 0.67(0.00) | 18.71(0.00) | 57.54%(60.35%) |
| ACC | 71.11% | 1.43(1.12) | 0.73(0.00) | 28.58(0.00) | 33.69%(37.36%) |
| Company Avg | 62.31% | 8.11(2.95) | 0.64(0.00) | 18.33(0.00) | 48.94%(52.55%) |
| Onco | 59.56% | 14.29 | 1.08 | 23.16 | 69.01% |

## iAssign Stats

| Clinic | iAssign utilization | Avg patients/nurse/day (Median) | Avg chairs/nurse (Median) | Avg nurse-to-patient in chair time/day (Median) (Nurse Util) |
| --- | --- | --- | --- | --- |
| A210 | 90.48% | 5.29(5.33) | 3.24(3.00) | 46.28%(48.74%) |
| ACC | 96.15% | 5.39(5.33) | 3.91(3.51) | 46.49%(50%) |
| Company Avg | 96.05% | 5.8(5.69) | 3.24(3.24) | 48.54%(50.43%) |
| Onco | 90.44% | 6.19 | 3.46 | 62.70% |
"""

if args.parse_only:
    console.rule("[bold cyan]PARSE-ONLY MODE — testing KPI parser on dummy markdown[/bold cyan]")
    from app.parsers.kpi_parser import parse_issue_body

    configs_dir = os.getenv("CONFIGS_DIR", "./configs")
    iopt, iasg, meta = parse_issue_body(DUMMY_MARKDOWN, configs_dir)

    console.print(f"\n[bold]Parse metadata:[/bold] {meta}")
    console.print(f"iOptimize KPIs: [green]{len(iopt)}[/green]")
    console.print(f"iAssign KPIs:   [green]{len(iasg)}[/green]")

    def show_kpis(kpis, title):
        t = Table(title=title, show_header=True, header_style="bold magenta")
        t.add_column("Location")
        t.add_column("KPI")
        t.add_column("Raw")
        t.add_column("Avg", justify="right")
        t.add_column("Median", justify="right")
        t.add_column("Unit")
        t.add_column("Status")
        for k in kpis:
            style = "" if k.parse_status == "ok" else "yellow"
            t.add_row(
                k.location_name,
                k.kpi_name,
                k.value_raw,
                f"{k.value_avg:.4f}" if k.value_avg is not None else "—",
                f"{k.value_median:.4f}" if k.value_median is not None else "—",
                k.value_unit or "—",
                k.parse_status,
                style=style
            )
        console.print(t)

    show_kpis(iopt, "iOptimize KPIs")
    show_kpis(iasg, "iAssign KPIs")
    sys.exit(0)


# ── LIVE GITHUB FETCH ────────────────────────────────────────────────────────
console.rule(f"[bold cyan]LIVE FETCH — {args.month}[/bold cyan]")

token = os.getenv("GITHUB_TOKEN", "")
repo  = os.getenv("GITHUB_REPO", "")
label = os.getenv("CHR_LABEL", "Clinic health report")

if not token or token == "your_github_personal_access_token_here":
    console.print("[red]✗ GITHUB_TOKEN not set in .env — add it and retry[/red]")
    sys.exit(1)

from app.services.github_client import fetch_chr_issues_for_month
from app.parsers.kpi_parser import parse_issue_body

issues = fetch_chr_issues_for_month(repo, label, args.month)

if not issues:
    console.print(f"[yellow]⚠  No issues found for {args.month}[/yellow]")
    sys.exit(0)

if args.client:
    issues = [i for i in issues if args.client.upper() in i.title.upper()]
    console.print(f"[dim]Filtered to client '{args.client}': {len(issues)} issues[/dim]")

configs_dir = os.getenv("CONFIGS_DIR", "./configs")

for issue in issues:
    console.rule(f"[bold]#{issue.number} — {issue.title}[/bold]")
    iopt, iasg, meta = parse_issue_body(issue.body, configs_dir)
    console.print(f"  Parse meta: {meta}")
    console.print(f"  iOptimize: [green]{len(iopt)} KPIs[/green]  |  iAssign: [green]{len(iasg)} KPIs[/green]")

    warnings = [k for k in iopt + iasg if k.parse_status != "ok"]
    if warnings:
        console.print(f"  [yellow]⚠  {len(warnings)} parse warnings:[/yellow]")
        for w in warnings:
            console.print(f"     {w.location_name} / {w.kpi_name}: {w.parse_notes}")

console.print("\n[bold green]✓ Test complete[/bold green]")
