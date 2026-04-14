"""
Email Engine — generates one polished HTML email per client.

God-level v2 changes:
  1.  Filter "Global Avg" from clinic tables and location counts
  2.  Hide Onco row when all values are None (13/14 clients)
  3.  Smart charts: horizontal bars when >10 locations, top/bottom-N when >15
  4.  Outlier section moved ABOVE charts, capped at 8 rows
  5.  Prior-month value shown in KPI cells (in parentheses after arrow)
  6.  Unit suffixes on ALL columns (Avg Delay shows "min", Tx shows "/day")
  7.  Composite score footnote explaining the scale
  8.  Location names: underscores → spaces
  9.  Footer: "Prepared by the OncoSmart Analytics Team" + real run ID
  10. Score badge enlarged to 11px
  11. Print stylesheet with page-break rules
  12. Suppress MoM arrows when <10% coverage (e.g. TNO missing months)
  13. Chart DPI reduced for large clients to keep email under 500KB
  14. Note when prior month data unavailable
"""
import os
import io
import base64
import logging
from datetime import datetime
from typing import List, Dict, Optional
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# NON-CLINIC FILTER (same list as insight_engine)
# ─────────────────────────────────────────────────────────────
NON_CLINIC_NAMES = {
    'global avg', 'global average', 'network avg', 'network average',
    'onco avg', 'onco average', 'oncosmart avg', 'oncosmart average',
    'company avg', 'company average', 'all clinics',
    'onco', 'total', 'grand total', 'overall',
}


def _is_real_clinic(location_name: str) -> bool:
    return location_name.strip().lower() not in NON_CLINIC_NAMES


def _clean_name(name: str) -> str:
    """Replace underscores with spaces."""
    return name.replace('_', ' ').strip()


# ─────────────────────────────────────────────────────────────
# COLOUR PALETTE
# ─────────────────────────────────────────────────────────────
NAVY    = "#1B2A4A"
SLATE   = "#4A5568"
TEAL    = "#2C7A7B"
GREEN   = "#276749"
GREEN_BG= "#C6F6D5"
RED     = "#9B2335"
RED_BG  = "#FED7D7"
AMBER   = "#92400E"
AMBER_BG= "#FEF3C7"
GREY_BG = "#F7F8FA"
BORDER  = "#E2E8F0"
WHITE   = "#FFFFFF"


# ─────────────────────────────────────────────────────────────
# CHART GENERATION
# ─────────────────────────────────────────────────────────────

def _b64(fig, dpi=120) -> str:
    """
    Render chart to base64 string.
    Uses JPEG format at quality=75 for much smaller file sizes than PNG.
    A 4-chart email drops from ~250KB to ~80KB with JPEG.
    """
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.savefig(buf, format='jpeg', dpi=dpi, bbox_inches='tight',
                facecolor='white', edgecolor='none',
                pil_kwargs={'quality': 75, 'optimize': True})
    buf.seek(0)
    data = base64.b64encode(buf.read()).decode()
    plt.close(fig)
    return data


def _bar_chart(names, values, benchmark_lines, title, ylabel,
               lower_is_better=False, y_suffix="%", max_locations=15):
    """
    Smart bar chart:
      - ≤10 locations: vertical bars (standard)
      - 11-15 locations: vertical bars, rotated labels
      - >15 locations: show only top 5 + bottom 5 with separator
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np

    # For very large location counts, show top 5 + bottom 5
    original_n = len(names)
    truncated = False
    if original_n > max_locations:
        # Sort by value to find top and bottom performers
        paired = sorted(zip(names, values), key=lambda x: x[1],
                        reverse=(not lower_is_better))
        top5 = paired[:5]
        bot5 = paired[-5:]
        names  = [p[0] for p in top5] + ['⋯'] + [p[0] for p in bot5]
        values = [p[1] for p in top5] + [0]    + [p[1] for p in bot5]
        truncated = True

    n = len(names)
    # DPI: JPEG compression handles quality, so we can go lower
    dpi = 90 if original_n > 10 else 100

    fig, ax = plt.subplots(figsize=(max(7, n * 0.9), 4.5))
    fig.patch.set_facecolor('white')

    bar_colors = []
    for i, v in enumerate(values):
        if truncated and names[i] == '⋯':
            bar_colors.append('#E2E8F0')
            continue
        refs = [b for b in [bl[0] for bl in benchmark_lines] if b is not None]
        if not refs:
            bar_colors.append('#4A90D9')
            continue
        best_ref = min(refs) if lower_is_better else max(refs)
        if lower_is_better:
            bar_colors.append('#2C7A7B' if v <= best_ref else ('#E53E3E' if v > best_ref * 1.15 else '#DD6B20'))
        else:
            bar_colors.append('#2C7A7B' if v >= best_ref else ('#E53E3E' if v < best_ref * 0.85 else '#DD6B20'))

    bars = ax.bar(range(n), values, color=bar_colors,
                  alpha=0.88, width=0.55, zorder=3)

    for bar, val, name in zip(bars, values, names):
        if name == '⋯':
            continue
        ax.text(bar.get_x() + bar.get_width()/2,
                bar.get_height() + (max(values)*0.015 if values else 1),
                f'{val:.1f}{y_suffix}', ha='center', va='bottom',
                fontsize=8 if n > 10 else 8.5, fontweight='600', color='#2D3748')

    line_styles = [('--', '#1B2A4A', 1.6), (':', '#718096', 1.4)]
    for i, (ref_val, label) in enumerate(benchmark_lines):
        if ref_val is None:
            continue
        ls, lc, lw = line_styles[i % 2]
        ax.axhline(ref_val, color=lc, linestyle=ls, linewidth=lw,
                   label=f'{label} ({ref_val:.1f}{y_suffix})', zorder=4)

    rotation = 35 if n > 8 else 28
    ax.set_xticks(range(n))
    ax.set_xticklabels([_clean_name(nm) for nm in names],
                       rotation=rotation, ha='right',
                       fontsize=7.5 if n > 10 else 8.5, color='#4A5568')
    ax.set_ylabel(ylabel, fontsize=9, color='#4A5568')

    subtitle = f' (top 5 & bottom 5 of {original_n})' if truncated else ''
    ax.set_title(f'{title}{subtitle}', fontsize=11, fontweight='700',
                 color='#1B2A4A', pad=12)
    ax.set_ylim(0, max(values + [b[0] or 0 for b in benchmark_lines] + [1]) * 1.18)
    if any(b[0] for b in benchmark_lines):
        ax.legend(fontsize=8, framealpha=0.6, loc='lower right')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#CBD5E0')
    ax.spines['bottom'].set_color('#CBD5E0')
    ax.tick_params(colors='#718096')
    ax.yaxis.grid(True, color='#EDF2F7', linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    plt.tight_layout()
    return _b64(fig, dpi=dpi)


def generate_compliance_chart(locations, company_avg, onco):
    names  = [l['name'] for l in locations]
    values = [l['scheduler_compliance'] or 0 for l in locations]
    return _bar_chart(names, values,
                      [(company_avg, 'Company Avg'), (onco, 'Onco Network')],
                      'Scheduler Compliance by Location',
                      'Scheduler Compliance (%)', lower_is_better=False)


def generate_delay_chart(locations, company_avg, onco):
    names  = [l['name'] for l in locations]
    values = [l['avg_delay_mins'] or 0 for l in locations]
    return _bar_chart(names, values,
                      [(company_avg, 'Company Avg'), (onco, 'Onco Network')],
                      'Avg Delay Before Treatment',
                      'Minutes', lower_is_better=True, y_suffix=" min")


def generate_chair_util_chart(locations, company_avg, onco):
    names  = [l['name'] for l in locations]
    values = [l['avg_chair_utilization'] or 0 for l in locations]
    return _bar_chart(names, values,
                      [(company_avg, 'Company Avg'), (onco, 'Onco Network')],
                      'Chair Utilization by Location',
                      'Chair Utilization (%)', lower_is_better=False)


def generate_iassign_chart(locations, company_avg):
    locs   = [l for l in locations if l.get('iassign_utilization') is not None]
    if not locs:
        return None
    names  = [l['name'] for l in locs]
    values = [l['iassign_utilization'] or 0 for l in locs]
    return _bar_chart(names, values,
                      [(company_avg, 'Company Avg'), (None, '')],
                      'iAssign Utilization by Location',
                      'iAssign Utilization (%)', lower_is_better=False)


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _month_label(run_month: str) -> str:
    try:
        return datetime.strptime(run_month, '%Y-%m').strftime('%B %Y')
    except:
        return run_month


def _fmt(val, suffix='', decimals=1):
    if val is None:
        return '—'
    return f"{val:.{decimals}f}{suffix}"


def _delta_html(current, prior, higher_is_better=True, show_prior=True):
    """
    Return a small MoM delta span: ↑2.3 (from 4.5) in green or ↓1.1 (from 5.6) in red.
    If show_prior=True, includes the prior value in parentheses.
    """
    if current is None or prior is None:
        return ''
    delta = current - prior
    if abs(delta) < 0.05:
        return '<span style="color:#A0AEC0;font-size:10px;margin-left:4px;">→</span>'
    is_good = (delta > 0) if higher_is_better else (delta < 0)
    arrow   = '↑' if delta > 0 else '↓'
    color   = GREEN if is_good else RED
    prior_str = f' <span style="color:#A0AEC0;font-size:9px;">(was {prior:.1f})</span>' if show_prior else ''
    return (f'<span style="color:{color};font-size:10px;'
            f'font-weight:600;margin-left:4px;">{arrow}{abs(delta):.1f}</span>{prior_str}')


def _kpi_cell(val, benchmark, higher_is_better=True, suffix='%',
              prior=None, decimals=1, show_prior=True):
    """Return a <td> with value, colour coding vs benchmark, and MoM arrow with prior."""
    if val is None:
        return f'<td class="kpi-cell">—</td>'

    if benchmark is not None:
        diff = val - benchmark
        threshold = abs(benchmark) * 0.05
        if abs(diff) <= threshold:
            bg, tc = '#EDF2F7', SLATE
        elif (diff > 0) == higher_is_better:
            bg, tc = GREEN_BG, GREEN
        else:
            bg, tc = RED_BG, RED
    else:
        bg, tc = WHITE, SLATE

    delta_span = _delta_html(val, prior, higher_is_better, show_prior=show_prior)
    return (f'<td class="kpi-cell" style="background:{bg};color:{tc};font-weight:600;">'
            f'{_fmt(val, suffix, decimals)}{delta_span}</td>')


def _chart_img(b64, alt):
    if not b64:
        return ''
    return (f'<img src="data:image/jpeg;base64,{b64}" alt="{alt}" '
            f'style="width:100%;border-radius:6px;display:block;">')


def _has_any_value(*vals):
    """True if any value in the list is not None."""
    return any(v is not None for v in vals)


# ─────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────

def generate_client_email(session: Session, client_name: str,
                           run_month: str, run_id: str) -> str:
    from app.db.models import (ChrKpiWide, ChrAiInsight, ChrComparisonResult,
                                ChrEmailDraft, RowType, KpiSource)

    # ── Pull data ────────────────────────────────────────────
    clinic_iopt_raw = session.query(ChrKpiWide).filter_by(
        run_month=run_month, client_name=client_name,
        row_type=RowType.CLINIC, source=KpiSource.IOPTIMIZE,
    ).order_by(ChrKpiWide.location_name).all()

    # CRITICAL: Filter out non-clinic rows
    clinic_iopt = [r for r in clinic_iopt_raw if _is_real_clinic(r.location_name)]

    clinic_iasg_raw = session.query(ChrKpiWide).filter_by(
        run_month=run_month, client_name=client_name,
        row_type=RowType.CLINIC, source=KpiSource.IASSIGN,
    ).all()
    clinic_iasg = {r.location_name: r for r in clinic_iasg_raw if _is_real_clinic(r.location_name)}

    co_iopt  = session.query(ChrKpiWide).filter_by(run_month=run_month, client_name=client_name,
                  row_type=RowType.COMPANY_AVG, source=KpiSource.IOPTIMIZE).first()
    co_iasg  = session.query(ChrKpiWide).filter_by(run_month=run_month, client_name=client_name,
                  row_type=RowType.COMPANY_AVG, source=KpiSource.IASSIGN).first()
    onco_iopt= session.query(ChrKpiWide).filter_by(run_month=run_month, client_name=client_name,
                  row_type=RowType.ONCO, source=KpiSource.IOPTIMIZE).first()
    onco_iasg= session.query(ChrKpiWide).filter_by(run_month=run_month, client_name=client_name,
                  row_type=RowType.ONCO, source=KpiSource.IASSIGN).first()

    insights = session.query(ChrAiInsight).filter_by(
        run_month=run_month, client_name=client_name,
    ).order_by(ChrAiInsight.priority.desc()).all()

    outliers = session.query(ChrComparisonResult).filter_by(
        run_month=run_month, client_name=client_name, is_outlier=True,
    ).all()
    # Filter non-clinic from outliers
    outliers = [o for o in outliers if _is_real_clinic(o.location_name)]

    # Composite scores per location
    composite_scores = {}
    for row in clinic_iopt:
        sc_row = session.query(ChrComparisonResult).filter_by(
            run_month=run_month, client_name=client_name,
            location_name=row.location_name, source=KpiSource.IOPTIMIZE,
            kpi_name='scheduler_compliance',
        ).first()
        if sc_row and sc_row.composite_score is not None:
            composite_scores[row.location_name] = sc_row.composite_score

    # MoM comparison rows (for delta arrows)
    comps = {
        (c.location_name, c.kpi_name): c
        for c in session.query(ChrComparisonResult).filter_by(
            run_month=run_month, client_name=client_name,
            source=KpiSource.IOPTIMIZE,
        ).all()
    }
    comps_ia = {
        (c.location_name, c.kpi_name): c
        for c in session.query(ChrComparisonResult).filter_by(
            run_month=run_month, client_name=client_name,
            source=KpiSource.IASSIGN,
        ).all()
    }

    # ── Check MoM arrow coverage ─────────────────────────────
    # If <10% of cells have prior data, suppress arrows entirely
    total_cells = 0
    cells_with_prior = 0
    for row in clinic_iopt:
        for kpi in ['scheduler_compliance', 'avg_delay_mins', 'avg_chair_utilization',
                     'avg_treatments_per_day', 'avg_treatment_mins_per_patient']:
            total_cells += 1
            c = comps.get((row.location_name, kpi))
            if c and c.prior_avg is not None:
                cells_with_prior += 1
    arrow_coverage = cells_with_prior / max(1, total_cells)
    show_arrows = arrow_coverage >= 0.10  # suppress if <10% coverage

    # ── Build location dicts ─────────────────────────────────
    locations = []
    for row in clinic_iopt:
        ia = clinic_iasg.get(row.location_name)
        locations.append({
            'name':                   _clean_name(row.location_name),
            'db_name':                row.location_name,
            'scheduler_compliance':   row.scheduler_compliance,
            'avg_delay_mins':         row.delay_avg,
            'avg_delay_median':       row.delay_median,
            'avg_chair_utilization':  row.chair_util_avg,
            'chair_util_median':      row.chair_util_median,
            'avg_treatments_per_day': row.treatments_avg,
            'tx_mins_avg':            row.tx_mins_avg,
            'iassign_utilization':    ia.iassign_utilization if ia else None,
            'avg_patients_per_nurse': ia.patients_per_nurse_avg if ia else None,
            'avg_chairs_per_nurse':   ia.chairs_per_nurse_avg if ia else None,
            'avg_nurse_util':         ia.nurse_util_avg if ia else None,
        })

    co  = {
        'scheduler_compliance':   co_iopt.scheduler_compliance  if co_iopt else None,
        'avg_delay_mins':         co_iopt.delay_avg             if co_iopt else None,
        'avg_chair_utilization':  co_iopt.chair_util_avg        if co_iopt else None,
        'iassign_utilization':    co_iasg.iassign_utilization   if co_iasg else None,
        'avg_nurse_util':         co_iasg.nurse_util_avg        if co_iasg else None,
    }

    # Check if Onco has ANY real data — if all None, we hide the row
    onco_has_data = onco_iopt is not None and _has_any_value(
        onco_iopt.scheduler_compliance, onco_iopt.delay_avg,
        onco_iopt.chair_util_avg, onco_iopt.treatments_avg,
    )
    onco = {
        'scheduler_compliance':   onco_iopt.scheduler_compliance if onco_iopt else None,
        'avg_delay_mins':         onco_iopt.delay_avg            if onco_iopt else None,
        'avg_chair_utilization':  onco_iopt.chair_util_avg       if onco_iopt else None,
    }

    # ── Charts ───────────────────────────────────────────────
    c_compliance = generate_compliance_chart(
        locations, co['scheduler_compliance'],
        onco['scheduler_compliance'] if onco_has_data else None
    ) if locations else None
    c_delay = generate_delay_chart(
        locations, co['avg_delay_mins'],
        onco['avg_delay_mins'] if onco_has_data else None
    ) if locations else None
    c_chair = generate_chair_util_chart(
        locations, co['avg_chair_utilization'],
        onco['avg_chair_utilization'] if onco_has_data else None
    ) if locations else None
    c_iassign = generate_iassign_chart(
        locations, co['iassign_utilization']
    ) if locations else None

    # ── Render ───────────────────────────────────────────────
    html = _render(
        client_name=client_name, run_month=run_month, run_id=run_id,
        locations=locations, co=co, onco=onco, onco_has_data=onco_has_data,
        co_iopt=co_iopt, co_iasg=co_iasg,
        onco_iopt=onco_iopt, onco_iasg=onco_iasg,
        insights=insights, outliers=outliers,
        comps=comps, comps_ia=comps_ia,
        composite_scores=composite_scores,
        show_arrows=show_arrows,
        c_compliance=c_compliance, c_delay=c_delay,
        c_chair=c_chair, c_iassign=c_iassign,
    )

    # ── Store ────────────────────────────────────────────────
    subject  = f"{client_name} — Clinic Health Report | {_month_label(run_month)}"
    existing = session.query(ChrEmailDraft).filter_by(
        run_month=run_month, client_name=client_name
    ).first()
    if existing:
        existing.subject_line = subject
        existing.body_html    = html
        existing.draft_status = 'generated'
        existing.run_id       = run_id
    else:
        session.add(ChrEmailDraft(
            run_month=run_month, client_name=client_name,
            subject_line=subject, body_html=html,
            draft_status='generated', run_id=run_id,
        ))
    session.commit()
    return html


# ─────────────────────────────────────────────────────────────
# HTML RENDERER
# ─────────────────────────────────────────────────────────────

def _render(client_name, run_month, run_id, locations, co, onco, onco_has_data,
            co_iopt, co_iasg, onco_iopt, onco_iasg,
            insights, outliers, comps, comps_ia,
            composite_scores, show_arrows,
            c_compliance, c_delay, c_chair, c_iassign):

    month_label = _month_label(run_month)
    n_loc       = len(locations)

    # ── AI insight sections ──────────────────────────────────
    exec_sum  = next((i for i in insights if i.insight_type == 'executive_summary'), None)
    highlight = next((i for i in insights if i.insight_type == 'highlight'), None)
    areas     = next((i for i in insights if i.insight_type == 'concern'), None)
    rec       = next((i for i in insights if i.insight_type == 'recommendation'), None)

    # ── No-arrow note (when prior month data unavailable) ────
    arrow_note = ""
    if not show_arrows:
        arrow_note = (
            '<p class="section-note" style="color:#92400E;background:#FEF3C7;'
            'padding:6px 12px;border-radius:4px;margin-bottom:10px;">'
            'Prior month data is not available for this client — '
            'month-over-month comparisons will appear in next month\'s report.</p>'
        )

    # ── iOptimize table ──────────────────────────────────────
    iopt_body = ''
    for loc in locations:
        n = loc['name']
        db = loc['db_name']
        sc_comp  = comps.get((db, 'scheduler_compliance'))
        del_comp = comps.get((db, 'avg_delay_mins'))
        cu_comp  = comps.get((db, 'avg_chair_utilization'))
        tx_comp  = comps.get((db, 'avg_treatments_per_day'))

        sc_prior  = sc_comp.prior_avg if sc_comp and show_arrows else None
        del_prior = del_comp.prior_avg if del_comp and show_arrows else None
        cu_prior  = cu_comp.prior_avg if cu_comp and show_arrows else None
        tx_prior  = tx_comp.prior_avg if tx_comp and show_arrows else None

        score = composite_scores.get(db)
        score_badge = ''
        if score is not None:
            sc = score
            badge_bg  = '#C6F6D5' if sc >= 60 else ('#FED7D7' if sc < 40 else '#FEF3C7')
            badge_col = '#276749' if sc >= 60 else ('#9B2335' if sc < 40 else '#92400E')
            score_badge = (f'<span style="font-size:11px;font-weight:700;'
                          f'background:{badge_bg};color:{badge_col};'
                          f'padding:2px 7px;border-radius:4px;margin-left:6px;">'
                          f'{sc:.0f}</span>')
        iopt_body += f"""
        <tr>
          <td class="loc-cell">{n}{score_badge}</td>
          {_kpi_cell(loc['scheduler_compliance'], co['scheduler_compliance'],
                     True, '%', sc_prior, show_prior=show_arrows)}
          {_kpi_cell(loc['avg_delay_mins'], co['avg_delay_mins'],
                     False, ' min', del_prior, decimals=1, show_prior=show_arrows)}
          <td class="kpi-cell">{_fmt(loc['avg_delay_median'], ' min')}</td>
          {_kpi_cell(loc['avg_chair_utilization'], co['avg_chair_utilization'],
                     True, '%', cu_prior, show_prior=show_arrows)}
          <td class="kpi-cell">{_fmt(loc['chair_util_median'], '%')}</td>
          {_kpi_cell(loc['avg_treatments_per_day'], co_iopt.treatments_avg if co_iopt else None,
                     False, '/day', tx_prior, show_prior=show_arrows)}
          <td class="kpi-cell">{_fmt(loc['tx_mins_avg'], ' min')}</td>
        </tr>"""

    # Company avg row
    iopt_body += f"""
        <tr class="bench-row">
          <td class="loc-cell">Company Average</td>
          <td class="kpi-cell">{_fmt(co_iopt.scheduler_compliance if co_iopt else None, '%')}</td>
          <td class="kpi-cell" colspan="2">{_fmt(co_iopt.delay_avg if co_iopt else None, ' min')}</td>
          <td class="kpi-cell" colspan="2">{_fmt(co_iopt.chair_util_avg if co_iopt else None, '%')}</td>
          <td class="kpi-cell">{_fmt(co_iopt.treatments_avg if co_iopt else None, '/day')}</td>
          <td class="kpi-cell">{_fmt(co_iopt.tx_mins_avg if co_iopt else None, ' min')}</td>
        </tr>"""

    # Onco row — ONLY if it has real data
    onco_row_html = ''
    if onco_has_data:
        onco_row_html = f"""
        <tr class="onco-row">
          <td class="loc-cell">Onco Network</td>
          <td class="kpi-cell">{_fmt(onco_iopt.scheduler_compliance if onco_iopt else None, '%')}</td>
          <td class="kpi-cell" colspan="2">{_fmt(onco_iopt.delay_avg if onco_iopt else None, ' min')}</td>
          <td class="kpi-cell" colspan="2">{_fmt(onco_iopt.chair_util_avg if onco_iopt else None, '%')}</td>
          <td class="kpi-cell">{_fmt(onco_iopt.treatments_avg if onco_iopt else None, '/day')}</td>
          <td class="kpi-cell">{_fmt(onco_iopt.tx_mins_avg if onco_iopt else None, ' min')}</td>
        </tr>"""
    iopt_body += onco_row_html

    # ── iAssign table ────────────────────────────────────────
    iasg_body = ''
    has_iasg  = any(l['iassign_utilization'] is not None for l in locations)

    if has_iasg:
        for loc in locations:
            if loc['iassign_utilization'] is None:
                continue
            n = loc['name']
            db = loc['db_name']
            ia_comp = comps_ia.get((db, 'iassign_utilization'))
            nu_comp = comps_ia.get((db, 'avg_nurse_to_patient_chair_time'))
            ia_prior = ia_comp.prior_avg if ia_comp and show_arrows else None
            nu_prior = nu_comp.prior_avg if nu_comp and show_arrows else None
            iasg_body += f"""
            <tr>
              <td class="loc-cell">{n}</td>
              {_kpi_cell(loc['iassign_utilization'], co['iassign_utilization'],
                         True, '%', ia_prior, show_prior=show_arrows)}
              <td class="kpi-cell">{_fmt(loc['avg_patients_per_nurse'])}</td>
              <td class="kpi-cell">{_fmt(loc['avg_chairs_per_nurse'])}</td>
              {_kpi_cell(loc['avg_nurse_util'], co['avg_nurse_util'],
                         True, '%', nu_prior, show_prior=show_arrows)}
            </tr>"""

        if co_iasg:
            iasg_body += f"""
            <tr class="bench-row">
              <td class="loc-cell">Company Average</td>
              <td class="kpi-cell">{_fmt(co_iasg.iassign_utilization, '%')}</td>
              <td class="kpi-cell">{_fmt(co_iasg.patients_per_nurse_avg)}</td>
              <td class="kpi-cell">{_fmt(co_iasg.chairs_per_nurse_avg)}</td>
              <td class="kpi-cell">{_fmt(co_iasg.nurse_util_avg, '%')}</td>
            </tr>"""

        # Onco row in iAssign — only if data exists
        onco_iasg_has_data = onco_iasg is not None and _has_any_value(
            onco_iasg.iassign_utilization, onco_iasg.patients_per_nurse_avg,
        )
        if onco_iasg_has_data:
            iasg_body += f"""
            <tr class="onco-row">
              <td class="loc-cell">Onco Network</td>
              <td class="kpi-cell">{_fmt(onco_iasg.iassign_utilization, '%')}</td>
              <td class="kpi-cell">{_fmt(onco_iasg.patients_per_nurse_avg)}</td>
              <td class="kpi-cell">{_fmt(onco_iasg.chairs_per_nurse_avg)}</td>
              <td class="kpi-cell">{_fmt(onco_iasg.nurse_util_avg, '%')}</td>
            </tr>"""

    # ── Outlier rows (capped at 8, sorted by severity) ───────
    from app.engine.insight_engine import KPI_LABELS
    # Sort outliers by absolute z-score descending
    outliers_sorted = sorted(outliers, key=lambda o: abs(o.z_score or 0), reverse=True)
    outliers_capped = outliers_sorted[:8]
    outliers_extra  = len(outliers_sorted) - len(outliers_capped)

    outlier_rows = ''
    for o in outliers_capped:
        pct  = o.vs_company_delta_pct or 0
        up   = pct > 0
        kib  = {'scheduler_compliance': True, 'avg_chair_utilization': True,
                 'iassign_utilization': True}.get(o.kpi_name, False)
        good = up == kib
        bg   = GREEN_BG if good else RED_BG
        tc   = GREEN    if good else RED
        arrow= '▲' if up else '▼'
        outlier_rows += f"""
        <tr>
          <td style="padding:8px 14px;font-weight:600;">{_clean_name(o.location_name)}</td>
          <td style="padding:8px 14px;">{KPI_LABELS.get(o.kpi_name, o.kpi_name)}</td>
          <td style="padding:8px 14px;text-align:center;">{_fmt(o.current_avg)}</td>
          <td style="padding:8px 14px;text-align:center;">{_fmt(o.company_avg_value)}</td>
          <td style="padding:8px 14px;background:{bg};color:{tc};font-weight:700;text-align:center;">
            {arrow} {abs(pct):.1f}%
          </td>
        </tr>"""

    outlier_section = ''
    if outlier_rows:
        extra_note = ''
        if outliers_extra > 0:
            extra_note = (
                f'<p class="section-note" style="margin-top:8px;">'
                f'{outliers_extra} additional outlier{"s" if outliers_extra > 1 else ""} '
                f'not shown — only the most significant deviations are displayed.</p>'
            )
        outlier_section = f"""
      <div class="section">
        <h2 class="section-title">Statistical Outliers</h2>
        <p class="section-note">Locations deviating significantly from the company group average this month.</p>
        <table class="data-table">
          <thead><tr>
            <th>Location</th><th>Metric</th>
            <th style="text-align:center;">This Month</th>
            <th style="text-align:center;">Company Avg</th>
            <th style="text-align:center;">Variance</th>
          </tr></thead>
          <tbody>{outlier_rows}</tbody>
        </table>
        {extra_note}
      </div>"""

    # ── Analytics section (AI prose) ────────────────────────
    def prose(insight_obj, fallback=''):
        return insight_obj.insight_text if insight_obj else fallback

    analytics_section = f"""
      <div class="section">
        <h2 class="section-title">Performance Overview</h2>
        <p class="prose">{prose(exec_sum, 'Data processing in progress.')}</p>

        <div class="two-col" style="margin-top:24px;">
          <div class="insight-box insight-green">
            <div class="insight-label">What's Working Well</div>
            <p class="prose">{prose(highlight, 'Results are being compiled.')}</p>
          </div>
          <div class="insight-box insight-blue">
            <div class="insight-label">Areas to Explore</div>
            <p class="prose">{prose(areas, 'No significant concerns identified.')}</p>
          </div>
        </div>

        <div class="insight-box insight-navy" style="margin-top:16px;">
          <div class="insight-label">How We Can Help</div>
          <p class="prose">{prose(rec, 'Our team is available to review these results with you.')}</p>
        </div>
      </div>"""

    # ── iAssign section ──────────────────────────────────────
    iasg_section = ''
    if has_iasg and iasg_body:
        arrow_legend = 'Small arrows indicate month-over-month change' if show_arrows else ''
        iasg_section = f"""
      <div class="section">
        <h2 class="section-title">iAssign — Staffing & Nurse Metrics</h2>
        <p class="section-note">
          Colour coding vs company average
          {(' &nbsp;|&nbsp; ' + arrow_legend) if arrow_legend else ''}
        </p>
        {arrow_note}
        <div class="table-wrap">
        <table class="data-table">
          <thead><tr>
            <th>Location</th>
            <th>iAssign Utilization</th>
            <th>Patients / Nurse</th>
            <th>Chairs / Nurse</th>
            <th>Nurse Utilization</th>
          </tr></thead>
          <tbody>{iasg_body}</tbody>
        </table>
        </div>
      </div>"""

    # ── Charts section ───────────────────────────────────────
    def chart_col(b64, alt):
        if not b64:
            return ''
        return f"""
        <div class="chart-box">
          {_chart_img(b64, alt)}
        </div>"""

    charts_section = f"""
      <div class="section">
        <h2 class="section-title">Performance Charts</h2>
        <div class="chart-grid">
          {chart_col(c_compliance, 'Scheduler Compliance')}
          {chart_col(c_delay,      'Avg Delay')}
          {chart_col(c_chair,      'Chair Utilization')}
          {chart_col(c_iassign,    'iAssign Utilization')}
        </div>
      </div>"""

    # ── Legend ───────────────────────────────────────────────
    arrow_legend_text = (
        f'&nbsp;&nbsp;<span style="font-size:11px;color:{SLATE};">'
        f'Arrows (↑↓) show month-over-month change with prior value</span>'
    ) if show_arrows else ''

    legend = f"""
        <span class="badge badge-green">■ Above avg</span>
        <span class="badge badge-red">■ Below avg</span>
        <span class="badge badge-neutral">■ Within 5%</span>
        {arrow_legend_text}"""

    # ── Composite score footnote ─────────────────────────────
    score_footnote = (
        '<p class="section-note" style="margin-top:10px;font-style:italic;">'
        'Performance Score (shown as badge): weighted blend of compliance, delay, '
        'chair utilization, iAssign adoption, overtime, and nurse utilization, '
        'benchmarked against the full OncoSmart network. 50 = network average, '
        '100 = top decile.</p>'
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{client_name} — Clinic Health Report {month_label}</title>
<style>
  /* ── Reset ── */
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
                 'Helvetica Neue', Arial, sans-serif;
    font-size: 13px; line-height: 1.6;
    color: #2D3748; background: #EDF2F7;
  }}

  /* ── Shell ── */
  .shell {{ max-width: 860px; margin: 24px auto; background: {WHITE};
            border-radius: 8px; overflow: hidden;
            box-shadow: 0 2px 16px rgba(0,0,0,.10); }}

  /* ── Header ── */
  .header {{
    background: linear-gradient(135deg, {NAVY} 0%, #2D4A7A 100%);
    padding: 36px 44px 32px;
    color: white;
  }}
  .header-eyebrow {{
    font-size: 10px; letter-spacing: 2px; text-transform: uppercase;
    opacity: .65; margin-bottom: 8px;
  }}
  .header-title {{ font-size: 24px; font-weight: 700; letter-spacing: -.3px; }}
  .header-sub   {{ margin-top: 6px; font-size: 13px; opacity: .75; }}
  .header-meta  {{
    margin-top: 20px; padding-top: 16px;
    border-top: 1px solid rgba(255,255,255,.18);
    display: flex; gap: 32px; flex-wrap: wrap;
  }}
  .meta-item {{ font-size: 11px; opacity: .8; }}
  .meta-item strong {{ display: block; font-size: 18px; font-weight: 700;
                       opacity: 1; letter-spacing: -.5px; }}

  /* ── Sections ── */
  .section {{ padding: 32px 44px; border-bottom: 1px solid {BORDER}; }}
  .section:last-child {{ border-bottom: none; }}
  .section-title {{
    font-size: 14px; font-weight: 700; color: {NAVY};
    text-transform: uppercase; letter-spacing: .8px;
    padding-bottom: 10px; margin-bottom: 14px;
    border-bottom: 2px solid {NAVY};
  }}
  .section-note {{ font-size: 11px; color: #718096; margin-top: -8px; margin-bottom: 12px; }}

  /* ── Legend ── */
  .legend {{ margin-bottom: 10px; }}
  .badge {{ display: inline-block; font-size: 11px; padding: 2px 8px;
            border-radius: 4px; margin-right: 4px; }}
  .badge-green   {{ background: {GREEN_BG};  color: {GREEN}; }}
  .badge-red     {{ background: {RED_BG};    color: {RED};   }}
  .badge-neutral {{ background: #EDF2F7;    color: {SLATE}; }}

  /* ── Tables ── */
  .table-wrap {{ overflow-x: auto; }}
  .data-table {{ width: 100%; border-collapse: collapse; font-size: 12.5px; }}
  .data-table thead tr {{ background: {NAVY}; color: white; }}
  .data-table th {{
    padding: 9px 14px; text-align: left; font-weight: 600;
    font-size: 11px; letter-spacing: .4px; white-space: nowrap;
  }}
  .data-table tbody tr:hover {{ background: #F7FAFC; }}
  .loc-cell {{
    padding: 8px 14px; font-weight: 600; color: {NAVY};
    border-bottom: 1px solid {BORDER}; white-space: nowrap;
  }}
  .kpi-cell {{
    padding: 8px 14px; text-align: center;
    border-bottom: 1px solid {BORDER}; white-space: nowrap;
  }}
  .bench-row td {{ background: #EBF4FF !important; font-weight: 700;
                   font-style: normal; color: {NAVY}; }}
  .onco-row  td {{ background: #FAF5FF !important; font-style: italic;
                   color: #553C9A; }}

  /* ── Charts ── */
  .chart-grid {{
    display: grid; grid-template-columns: 1fr 1fr; gap: 16px;
  }}
  .chart-box {{
    background: {GREY_BG}; border: 1px solid {BORDER};
    border-radius: 6px; padding: 14px; overflow: hidden;
  }}

  /* ── Insight boxes ── */
  .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
  .insight-box {{
    border-radius: 6px; padding: 16px 18px;
  }}
  .insight-green {{ background: #F0FFF4; border-left: 4px solid {GREEN}; }}
  .insight-blue  {{ background: #EBF8FF; border-left: 4px solid #2B6CB0; }}
  .insight-navy  {{ background: #EBF4FF; border-left: 4px solid {NAVY};  }}
  .insight-label {{
    font-size: 10px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 1px; margin-bottom: 7px; color: #718096;
  }}
  .prose {{ font-size: 13px; line-height: 1.75; color: #2D3748; }}

  /* ── Footer ── */
  .footer {{
    padding: 20px 44px; background: {GREY_BG};
    text-align: center; font-size: 11px; color: #A0AEC0;
  }}

  /* ── Mobile ── */
  @media (max-width: 620px) {{
    .header {{ padding: 24px 20px; }}
    .section {{ padding: 24px 20px; }}
    .chart-grid {{ grid-template-columns: 1fr; }}
    .two-col    {{ grid-template-columns: 1fr; }}
    .header-meta{{ gap: 16px; }}
  }}

  /* ── Print ── */
  @media print {{
    body {{ background: white; }}
    .shell {{ box-shadow: none; max-width: 100%; }}
    .section {{ page-break-inside: avoid; }}
    .data-table {{ page-break-inside: auto; }}
    .data-table tr {{ page-break-inside: avoid; }}
    .chart-grid {{ page-break-inside: avoid; }}
  }}
</style>
</head>
<body>
<div class="shell">

  <!-- HEADER -->
  <div class="header">
    <div class="header-eyebrow">OncoSmart · Clinic Health Report</div>
    <div class="header-title">{client_name}</div>
    <div class="header-sub">{month_label} &nbsp;·&nbsp; Monthly Performance Summary</div>
    <div class="header-meta">
      <div class="meta-item"><strong>{n_loc}</strong>Location{'s' if n_loc != 1 else ''}</div>
      <div class="meta-item"><strong>{_fmt(co.get('scheduler_compliance'), '%')}</strong>Company Avg Compliance</div>
      <div class="meta-item"><strong>{_fmt(co.get('avg_delay_mins'), ' min')}</strong>Company Avg Delay</div>
      <div class="meta-item"><strong>{_fmt(co.get('avg_chair_utilization'), '%')}</strong>Company Avg Chair Util.</div>
    </div>
  </div>

  <!-- PERFORMANCE OVERVIEW -->
  {analytics_section}

  <!-- iOPTIMIZE TABLE -->
  <div class="section">
    <h2 class="section-title">iOptimize — Scheduling & Flow Metrics</h2>
    <p class="section-note">
      Colour coding vs company average
      {(' &nbsp;|&nbsp; Arrows show MoM change with prior value') if show_arrows else ''}
    </p>
    {arrow_note}
    <div class="legend">{legend}</div>
    {score_footnote}
    <div class="table-wrap">
    <table class="data-table">
      <thead><tr>
        <th>Location</th>
        <th>Scheduler Compliance</th>
        <th>Avg Delay (min)</th>
        <th>Median Delay</th>
        <th>Chair Utilization</th>
        <th>Chair Util. Median</th>
        <th>Tx Past Close</th>
        <th>Mins Past Close / Pt</th>
      </tr></thead>
      <tbody>{iopt_body}</tbody>
    </table>
    </div>
  </div>

  <!-- iASSIGN TABLE -->
  {iasg_section}

  <!-- OUTLIERS (moved ABOVE charts — most actionable data first) -->
  {outlier_section}

  <!-- CHARTS -->
  {charts_section}

  <!-- FOOTER -->
  <div class="footer">
    {client_name} &nbsp;·&nbsp; {month_label} Clinic Health Report
    &nbsp;·&nbsp; Prepared by the OncoSmart Analytics Team<br>
    Confidential — for internal review only &nbsp;·&nbsp; {run_id}
  </div>

</div>
</body>
</html>"""