"""Main pipeline orchestrator — all 7 steps"""
import os
import logging
from datetime import datetime
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
log = logging.getLogger(__name__)


class PipelineOrchestrator:

    def __init__(self, run_month: str, skip_github: bool = False):
        self.run_month   = run_month
        self.skip_github = skip_github
        self.run_id      = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.stats = {
            'issues_fetched': 0,
            'kpis_parsed': 0,
            'kpis_warnings': 0,
            'comparisons': 0,
            'ml_rows': 0,
            'correlations': 0,
            'insights': 0,
            'emails': 0,
            'json_exports': 0,
        }

    def run(self):
        console.print(Panel.fit(
            f"[bold cyan]CHR Pipeline[/bold cyan]  run_id=[yellow]{self.run_id}[/yellow]",
            border_style="cyan"
        ))
        self._step(1, "Fetch GitHub issues",   self._fetch_github_data)
        self._step(2, "Parse & store KPIs",    self._parse_kpis)
        self._step(3,   "Run comparisons",        self._run_comparisons)
        self._step(3.5, "ML analytics",           self._run_ml_analytics)
        self._step(4,   "Detect correlations",    self._detect_correlations)
        self._step(5, "Generate AI insights",   self._generate_insights)
        self._step(6, "Draft emails + charts",  self._generate_emails)
        self._step(7, "Export JSON for React",  self._export_json)
        self._print_summary()

    def _step(self, num: int, label: str, fn):
        console.print(f"\n[bold cyan]Step {num}/7:[/bold cyan] {label}")
        try:
            fn()
        except Exception as e:
            console.print(f"  [red]✗ Error: {e}[/red]")
            log.exception(f"Step {num} failed: {e}")
            raise

    # ── Step 1 ────────────────────────────────────────────────────────
    def _fetch_github_data(self):
        if self.skip_github:
            console.print("  [yellow]⏭  Skipped (--skip-github)[/yellow]")
            return

        from app.services.github_client import fetch_chr_issues_for_month
        from app.db.session import get_session
        from app.db.models import ChrIssueSnapshot

        repo  = os.getenv("GITHUB_REPO", "")
        label = os.getenv("CHR_LABEL", "Clinic health report")
        if not repo:
            raise RuntimeError("GITHUB_REPO not set in .env")

        issues = fetch_chr_issues_for_month(repo, label, self.run_month)
        console.print(f"  [green]✓ Fetched {len(issues)} issues[/green]")

        with get_session() as session:
            for issue in issues:
                client_name, _, _ = _parse_client_from_title(issue.title)
                existing = session.query(ChrIssueSnapshot).filter_by(
                    repo=repo, issue_number=issue.number
                ).first()
                if existing:
                    existing.body_markdown    = issue.body
                    existing.issue_updated_at = issue.updated_at
                    existing.run_id           = self.run_id
                else:
                    session.add(ChrIssueSnapshot(
                        run_month=self.run_month,
                        client_name=client_name or "UNKNOWN",
                        repo=repo,
                        issue_number=issue.number,
                        issue_title=issue.title,
                        issue_url=issue.html_url,
                        issue_created_at=issue.created_at,
                        issue_updated_at=issue.updated_at,
                        body_markdown=issue.body,
                        run_id=self.run_id,
                    ))
            session.commit()

        self.stats['issues_fetched'] = len(issues)
        console.print(f"  [dim]Saved to chr_issue_snapshot[/dim]")

    # ── Step 2 ────────────────────────────────────────────────────────
    def _parse_kpis(self):
        from app.db.session import get_session
        from app.db.models import ChrIssueSnapshot, ChrKpiValue, RowType, KpiSource
        from app.parsers.kpi_parser import parse_issue_body

        configs_dir = os.getenv("CONFIGS_DIR", "./configs")
        total_ok = total_warn = 0

        with get_session() as session:
            snapshots = session.query(ChrIssueSnapshot).filter_by(
                run_month=self.run_month
            ).all()

            if not snapshots:
                console.print("  [yellow]⚠  No snapshots — run Step 1 first[/yellow]")
                return

            for snap in snapshots:
                console.print(f"  [dim]Parsing {snap.client_name} #{snap.issue_number}...[/dim]")
                iopt_kpis, iasg_kpis, meta = parse_issue_body(snap.body_markdown, configs_dir)

                for kpi_list, source_enum in [(iopt_kpis, KpiSource.IOPTIMIZE),
                                               (iasg_kpis, KpiSource.IASSIGN)]:
                    for kpi in kpi_list:
                        row_type = _resolve_row_type(kpi.location_name)
                        existing = session.query(ChrKpiValue).filter_by(
                            run_month=self.run_month,
                            client_name=snap.client_name,
                            location_name=kpi.location_name,
                            source=source_enum,
                            kpi_name=kpi.kpi_name,
                        ).first()
                        if existing:
                            existing.value_raw    = kpi.value_raw
                            existing.value_avg    = kpi.value_avg
                            existing.value_median = kpi.value_median
                            existing.value_unit   = kpi.value_unit
                            existing.parse_status = kpi.parse_status
                            existing.parse_notes  = kpi.parse_notes
                            existing.run_id       = self.run_id
                        else:
                            session.add(ChrKpiValue(
                                run_month=self.run_month,
                                client_name=snap.client_name,
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
                                issue_number=snap.issue_number,
                                run_id=self.run_id,
                            ))
                        if kpi.parse_status == "ok":
                            total_ok += 1
                        else:
                            total_warn += 1

                session.commit()
                console.print(f"  [green]✓ {snap.client_name}: {len(iopt_kpis)} iOpt | {len(iasg_kpis)} iAssign[/green]")

        self.stats['kpis_parsed']   = total_ok
        self.stats['kpis_warnings'] = total_warn
        console.print(f"  [bold green]✓ {total_ok} KPIs stored ({total_warn} warnings)[/bold green]")

    # ── Step 3 ────────────────────────────────────────────────────────
    def _run_comparisons(self):
        from app.db.session import get_session
        from app.engine.comparison_engine import run_comparisons

        with get_session() as session:
            total = run_comparisons(session, self.run_month, self.run_id)

        self.stats['comparisons'] = total
        console.print(f"  [green]✓ {total} comparison rows computed[/green]")

    # ── Step 3.5 ──────────────────────────────────────────────────────
    def _run_ml_analytics(self):
        from app.db.session import get_session
        from app.engine.ml_engine import run_ml_analytics

        with get_session() as session:
            total = run_ml_analytics(session, self.run_month, self.run_id)

        self.stats['ml_rows'] = total
        console.print(f"  [green]\u2713 {total} ML analytics rows written[/green]")

    # ── Step 4 ────────────────────────────────────────────────────────
    def _detect_correlations(self):
        from app.db.session import get_session
        from app.engine.insight_engine import detect_correlations

        with get_session() as session:
            total = detect_correlations(session, self.run_month, self.run_id)

        self.stats['correlations'] = total
        console.print(f"  [green]✓ {total} correlations detected[/green]")

    # ── Step 5 ────────────────────────────────────────────────────────
    def _generate_insights(self):
        from app.db.session import get_session
        from app.engine.insight_engine import generate_ai_insights

        with get_session() as session:
            total = generate_ai_insights(session, self.run_month, self.run_id)

        self.stats['insights'] = total
        console.print(f"  [green]✓ {total} AI insights generated[/green]")

    # ── Step 6 ────────────────────────────────────────────────────────
    def _generate_emails(self):
        from app.db.session import get_session
        from app.db.models import ChrKpiWide, RowType
        from app.engine.email_engine import generate_client_email

        artifacts_dir = os.getenv("ARTIFACTS_DIR", "./artifacts")
        os.makedirs(artifacts_dir, exist_ok=True)

        with get_session() as session:
            clients = [r[0] for r in session.query(ChrKpiWide.client_name).filter_by(
                run_month=self.run_month, row_type=RowType.CLINIC
            ).distinct().all()]

            for client in clients:
                console.print(f"  [dim]Generating email for {client}...[/dim]")
                html = generate_client_email(session, client, self.run_month, self.run_id)

                # Save HTML file to artifacts
                fname = f"{artifacts_dir}/{self.run_month}_{client}_email.html"
                with open(fname, 'w', encoding='utf-8') as f:
                    f.write(html)
                console.print(f"  [green]✓ {client} → {fname}[/green]")
                self.stats['emails'] += 1

    # ── Step 7 ────────────────────────────────────────────────────────
    def _export_json(self):
        from app.db.session import get_session
        from app.db.models import ChrKpiWide, RowType
        from app.engine.json_exporter import export_json

        output_dir = os.getenv("JSON_EXPORT_PATH", "../frontend/public/data")

        with get_session() as session:
            clients = [r[0] for r in session.query(ChrKpiWide.client_name).filter_by(
                run_month=self.run_month, row_type=RowType.CLINIC
            ).distinct().all()]

            count = export_json(session, clients, self.run_month, output_dir)

        self.stats['json_exports'] = count
        console.print(f"  [green]\u2713 {count} JSON files written to {output_dir}[/green]")

    # ── Summary ───────────────────────────────────────────────────────
    def _print_summary(self):
        t = Table(title="Pipeline Summary", show_header=True, header_style="bold cyan")
        t.add_column("Metric")
        t.add_column("Value", justify="right")
        t.add_row("Run ID",          self.run_id)
        t.add_row("Month",           self.run_month)
        t.add_row("Issues fetched",  str(self.stats['issues_fetched']))
        t.add_row("KPIs stored",     str(self.stats['kpis_parsed']))
        t.add_row("Parse warnings",  str(self.stats['kpis_warnings']))
        t.add_row("Comparisons",     str(self.stats['comparisons']))
        t.add_row("ML analytics rows", str(self.stats['ml_rows']))
        t.add_row("Correlations",    str(self.stats['correlations']))
        t.add_row("AI insights",     str(self.stats['insights']))
        t.add_row("Emails generated",str(self.stats['emails']))
        t.add_row("JSON files written", str(self.stats['json_exports']))
        console.print(t)


def _parse_client_from_title(title: str):
    from app.services.github_client import parse_issue_title
    return parse_issue_title(title)


def _resolve_row_type(location_name: str):
    """
    Classify a location row from the GitHub issue into its RowType.

    Ordering matters: check most-specific patterns first.
      - 'Company Avg'  → COMPANY_AVG
      - 'Onco …'       → ONCO
      - 'Global Avg', 'Network Avg', 'Overall', 'Total', 'Grand Total',
        'All Clinics'  → COMPANY_AVG  (network-wide aggregates, not real clinics)
      - anything else  → CLINIC
    """
    from app.db.models import RowType
    loc = location_name.lower().strip()

    if 'company' in loc:
        return RowType.COMPANY_AVG

    if 'onco' in loc:
        return RowType.ONCO

    # Network/global aggregate rows submitted inside some client issues.
    # These must NOT be stored as RowType.CLINIC or they pollute the
    # json_exporter location lists and composite score calculations.
    _AGGREGATE_KEYWORDS = (
        'global avg', 'global average',
        'network avg', 'network average',
        'all clinic',    # covers "All Clinics", "All Clinic Avg", etc.
        'grand total',
        'overall',
        'total',         # bare "Total" row
    )
    if any(kw in loc for kw in _AGGREGATE_KEYWORDS):
        return RowType.COMPANY_AVG

    return RowType.CLINIC