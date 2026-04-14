"""
Step 4 & 5 — Correlation Detection + AI Insight Generation

The AI section must read like a thoughtful senior analyst wrote it —
not a chatbot. No bullet lists. No "Highlights / Concerns" headers.
Flowing prose that references specific numbers and trends.

God-level v2 changes:
  - Filters out "Global Avg" and other non-clinic rows from AI context
  - Anchored-comparison prompt rules (every number must cite its benchmark)
  - Post-generation causation validator (rejects bad causal language)
  - Specific recommendations (references actual KPI gaps, not generic "deep dive")
  - Handles >100% chair utilization correctly in AI context
  - Human-readable month names in all MoM data
"""
import os
import re
import json
import logging
from datetime import datetime
from typing import List, Dict, Optional
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

HIGHER_IS_BETTER = {
    'scheduler_compliance':            True,
    'avg_delay_mins':                  False,
    'avg_treatments_per_day':          False,
    'avg_treatment_mins_per_patient':  False,
    'avg_chair_utilization':           True,
    'iassign_utilization':             True,
    'avg_patients_per_nurse':          None,
    'avg_chairs_per_nurse':            None,
    'avg_nurse_to_patient_chair_time': True,
}

KPI_LABELS = {
    'scheduler_compliance':            'Scheduler Compliance',
    'avg_delay_mins':                  'Avg Delay (mins)',
    'avg_treatments_per_day':          'Treatments Past Close/Day',
    'avg_treatment_mins_per_patient':  'Mins Past Close/Patient',
    'avg_chair_utilization':           'Chair Utilization',
    'iassign_utilization':             'iAssign Utilization',
    'avg_patients_per_nurse':          'Patients/Nurse',
    'avg_chairs_per_nurse':            'Chairs/Nurse',
    'avg_nurse_to_patient_chair_time': 'Nurse Utilization',
}

# ─────────────────────────────────────────────────────────────
# Non-clinic location names that should NEVER appear as real clinics.
# These are aggregate/benchmark rows that leak from GitHub issue tables.
# Case-insensitive matching.
# ─────────────────────────────────────────────────────────────
NON_CLINIC_NAMES = {
    'global avg', 'global average', 'network avg', 'network average',
    'onco avg', 'onco average', 'oncosmart avg', 'oncosmart average',
    'company avg', 'company average', 'all clinics',
    'onco', 'total', 'grand total', 'overall',
}


def _is_real_clinic(location_name: str) -> bool:
    """Return True only if this is a real clinic, not an aggregate row."""
    return location_name.strip().lower() not in NON_CLINIC_NAMES


def _month_name(run_month: str) -> str:
    """Convert '2026-02' to 'February 2026'."""
    try:
        return datetime.strptime(run_month, '%Y-%m').strftime('%B %Y')
    except Exception:
        return run_month


def _clean_location_name(name: str) -> str:
    """Replace underscores with spaces for display."""
    return name.replace('_', ' ').strip()


def detect_correlations(session: Session, run_month: str, run_id: str) -> int:
    from app.db.models import ChrComparisonResult, ChrKpiCorrelation, KpiSource

    clients = [r[0] for r in session.query(ChrComparisonResult.client_name).filter_by(
        run_month=run_month
    ).distinct().all()]

    total = 0
    for client in clients:
        comps = session.query(ChrComparisonResult).filter_by(
            run_month=run_month,
            client_name=client,
            source=KpiSource.IOPTIMIZE,
        ).all()

        by_location = {}
        for c in comps:
            if not _is_real_clinic(c.location_name):
                continue
            by_location.setdefault(c.location_name, {})[c.kpi_name] = c

        for location, kpis in by_location.items():
            sc   = kpis.get('scheduler_compliance')
            del_ = kpis.get('avg_delay_mins')

            if sc and del_ and sc.current_avg is not None and del_.current_avg is not None:
                sc_below  = sc.vs_company_delta is not None and sc.vs_company_delta < -5
                del_above = del_.vs_company_delta is not None and del_.vs_company_delta > 5
                if sc_below and del_above:
                    session.add(ChrKpiCorrelation(
                        run_month=run_month,
                        client_name=client,
                        location_name=location,
                        kpi1_source=KpiSource.IOPTIMIZE,
                        kpi1_name='scheduler_compliance',
                        kpi1_change_pct=sc.vs_company_delta_pct,
                        kpi2_source=KpiSource.IOPTIMIZE,
                        kpi2_name='avg_delay_mins',
                        kpi2_change_pct=del_.vs_company_delta_pct,
                        correlation_type='negative_correlation',
                        narrative_quality='excellent',
                        should_highlight=True,
                        run_id=run_id,
                    ))
                    total += 1

        session.commit()

    return total


def generate_ai_insights(session: Session, run_month: str, run_id: str) -> int:
    from app.db.models import ChrKpiWide, ChrComparisonResult, ChrAiInsight, RowType, KpiSource
    import anthropic

    client_ai = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

    clients = [r[0] for r in session.query(ChrKpiWide.client_name).filter_by(
        run_month=run_month, row_type=RowType.CLINIC
    ).distinct().all()]

    total = 0
    for client_name in clients:
        log.info(f"Generating insights for {client_name}...")
        context = _build_context_for_client(session, client_name, run_month)
        prompt  = _build_prompt(client_name, run_month, context)

        max_attempts = 3
        insights = None
        for attempt in range(max_attempts):
            try:
                response = client_ai.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=1500,
                    timeout=60,
                    messages=[{"role": "user", "content": prompt}]
                )
                raw      = response.content[0].text
                insights = _parse_ai_response(raw)

                # Post-generation validation
                validation_issues = _validate_ai_output(insights, context)
                if validation_issues and attempt < max_attempts - 1:
                    log.warning(f"AI output for {client_name} failed validation "
                                f"(attempt {attempt+1}): {validation_issues}")
                    # Add validation feedback to prompt for retry
                    prompt += (
                        f"\n\nYOUR PREVIOUS RESPONSE HAD THESE PROBLEMS — FIX THEM:\n"
                        + "\n".join(f"- {v}" for v in validation_issues)
                        + "\n\nRegenerate the JSON with these issues corrected."
                    )
                    insights = None
                    continue
                break
            except Exception as e:
                log.error(f"AI call failed for {client_name} (attempt {attempt+1}): {e}")
                if attempt == max_attempts - 1:
                    insights = _fallback_insights(context)

        if insights is None:
            insights = _fallback_insights(context)

        for insight in insights:
            # Last-resort cleanup: fix any causal/vague language that survived retries
            insight['text'] = _cleanup_ai_text(insight['text'])

            session.query(ChrAiInsight).filter_by(
                run_month=run_month,
                client_name=client_name,
                insight_type=insight['type'],
            ).delete()

            session.add(ChrAiInsight(
                run_month=run_month,
                client_name=client_name,
                insight_type=insight['type'],
                insight_text=insight['text'],
                priority=insight['priority'],
                supporting_kpis=json.dumps(insight.get('kpis', [])),
                confidence_score=insight.get('confidence', 0.9),
                run_id=run_id,
            ))
            total += 1

        session.commit()

    return total


# ─────────────────────────────────────────────────────────────
# POST-GENERATION VALIDATOR
# Checks AI output for forbidden patterns and rejects if found.
# ─────────────────────────────────────────────────────────────

# Forbidden causal phrases — only allowed if a likely_causal correlation exists
_CAUSAL_PHRASES = re.compile(
    r'\b(?:translat(?:ed|ing|es?)\s+into|result(?:ed|ing|s)\s+in|'
    r'led\s+to|lead(?:s|ing)\s+to|caus(?:ed|es?|ing)\s+by|'
    r'caus(?:ed|es?|ing)\b|driving|driven\s+by|because\s+of|'
    r'contribut(?:ed|ing|es?)\s+to|impact(?:ed|ing|s)\s+(?:the|their|its)|'
    r'enabled|enabling|fuell?(?:ed|ing)|'
    r'directly\s+(?:affect|impact|influenc)|'
    r'as\s+a\s+result\s+of|thanks\s+to)\b',
    re.IGNORECASE,
)

# Vague language patterns — catch adjectives that lack benchmark numbers
_VAGUE_PHRASES = re.compile(
    r'\b(?:strong\s+performance|impressive\s+|remarkable\s+|notable\s+gains?|'
    r'significant\s+(?:progress|gains?|improvement)|'
    r'showed?\s+improvement|demonstrated?\s+improvement|'
    r'(?:surged?|jumped?|soared?|climbed?|spiked?)\b|'
    r'above\s+(?:the\s+)?(?:benchmark|average|network)(?!\s+(?:of|at)\s+[\d.])|'
    r'below\s+(?:the\s+)?(?:benchmark|average|network)(?!\s+(?:of|at)\s+[\d.])|'
    r'exceeds?\s+(?:the\s+)?(?:benchmark|average|network)(?!\s+(?:of|at|by)\s+[\d.])|'
    r'trails?\s+(?:the\s+)?(?:benchmark|average|network)(?!\s+(?:of|at|by)\s+[\d.]))\b',
    re.IGNORECASE,
)


def _validate_ai_output(insights: List[dict], context: dict) -> List[str]:
    """
    Validate AI output for forbidden patterns.
    Returns list of issues (empty = passed).
    """
    issues = []
    has_causal_corr = any(
        c.get('rel_type') in ('likely_causal', 'plausible_causal')
        for c in context.get('correlations', [])
    )

    all_text = ' '.join(i['text'] for i in insights if i.get('text'))

    # Check for false causation
    causal_matches = _CAUSAL_PHRASES.findall(all_text)
    if causal_matches and not has_causal_corr:
        issues.append(
            f"Used causal language ({', '.join(causal_matches[:3])}) but no causal "
            f"relationships were detected. Use 'associated with' instead."
        )

    # Check for "Global Avg" referenced as a clinic
    if re.search(r'global\s*avg', all_text, re.IGNORECASE):
        issues.append(
            "Referenced 'Global Avg' as a clinic. This is not a real location — "
            "it is a network benchmark. Do not mention it by name."
        )

    # Check for vague benchmarks
    vague_matches = _VAGUE_PHRASES.findall(all_text)
    if vague_matches:
        issues.append(
            f"Used vague benchmark language ({', '.join(vague_matches[:3])}). "
            f"Every comparison must include the actual benchmark number."
        )

    return issues


def _cleanup_ai_text(text: str) -> str:
    """
    Last-resort text cleanup for common AI slips that survive the retry loop.
    Replaces causal language with safe alternatives in-place.
    """
    replacements = [
        (r'\btranslated\s+into\b', 'coincided with'),
        (r'\bresulted\s+in\b', 'coincided with'),
        (r'\bled\s+to\b', 'coincided with'),
        (r'\bleading\s+to\b', 'coinciding with'),
        (r'\bcaused\s+by\b', 'associated with'),
        (r'\bdriving\b', 'accompanying'),
        (r'\bdriven\s+by\b', 'associated with'),
        (r'\bcontributed\s+to\b', 'coincided with'),
        (r'\bcontributing\s+to\b', 'coinciding with'),
        (r'\benabled\b', 'accompanied'),
        (r'\benabling\b', 'accompanying'),
        (r'\bfueled\b', 'accompanied'),
        (r'\bfueling\b', 'accompanying'),
        (r'\bas\s+a\s+result\s+of\b', 'alongside'),
        (r'\bthanks\s+to\b', 'alongside'),
        (r'\bimpressive\s+', ''),
        (r'\bremarkable\s+', ''),
        (r'\bnotable\s+', ''),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    # Clean up double spaces from removals
    text = re.sub(r'  +', ' ', text).strip()
    return text


def _build_context_for_client(session, client_name: str, run_month: str) -> dict:
    from app.db.models import ChrKpiWide, ChrComparisonResult, ChrKpiCorrelation, RowType, KpiSource

    month_label = _month_name(run_month)

    context = {
        'client': client_name,
        'month': run_month,
        'month_label': month_label,
        'locations': [],
        'outliers': [],
        'mom_changes': [],        # notable MoM movements
        'trends': [],             # multi-month trend data
        'composite_scores': {},   # location_name → score
        'correlations': [],       # causal/correlated KPI pairs
    }

    wide_rows = session.query(ChrKpiWide).filter_by(
        run_month=run_month, client_name=client_name,
        row_type=RowType.CLINIC, source=KpiSource.IOPTIMIZE,
    ).all()

    iasg_rows = {r.location_name: r for r in session.query(ChrKpiWide).filter_by(
        run_month=run_month, client_name=client_name,
        row_type=RowType.CLINIC, source=KpiSource.IASSIGN,
    ).all()}

    onco_iopt = session.query(ChrKpiWide).filter_by(
        run_month=run_month, client_name=client_name,
        row_type=RowType.ONCO, source=KpiSource.IOPTIMIZE,
    ).first()

    co_iopt = session.query(ChrKpiWide).filter_by(
        run_month=run_month, client_name=client_name,
        row_type=RowType.COMPANY_AVG, source=KpiSource.IOPTIMIZE,
    ).first()

    context['onco'] = {
        'scheduler_compliance': onco_iopt.scheduler_compliance if onco_iopt else None,
        'avg_delay_mins':        onco_iopt.delay_avg if onco_iopt else None,
        'avg_chair_utilization': onco_iopt.chair_util_avg if onco_iopt else None,
    }
    context['company_avg'] = {
        'scheduler_compliance': co_iopt.scheduler_compliance if co_iopt else None,
        'avg_delay_mins':        co_iopt.delay_avg if co_iopt else None,
        'avg_chair_utilization': co_iopt.chair_util_avg if co_iopt else None,
    }

    for row in wide_rows:
        # CRITICAL: Filter out non-clinic rows that leaked into RowType.CLINIC
        if not _is_real_clinic(row.location_name):
            continue
        ia = iasg_rows.get(row.location_name)
        display_name = _clean_location_name(row.location_name)
        context['locations'].append({
            'name':                 display_name,
            'db_name':              row.location_name,  # original for DB lookups
            'scheduler_compliance': row.scheduler_compliance,
            'avg_delay_mins':       row.delay_avg,
            'avg_delay_median':     row.delay_median,
            'avg_chair_utilization':row.chair_util_avg,
            'avg_treatments_per_day': row.treatments_avg,
            'iassign_utilization':  ia.iassign_utilization if ia else None,
            'avg_patients_per_nurse': ia.patients_per_nurse_avg if ia else None,
            'avg_nurse_util':       ia.nurse_util_avg if ia else None,
        })

    # Outliers — filter out non-clinic locations
    outliers = session.query(ChrComparisonResult).filter_by(
        run_month=run_month, client_name=client_name, is_outlier=True,
    ).all()
    context['outliers'] = [
        {
            'location':      _clean_location_name(o.location_name),
            'kpi':           KPI_LABELS.get(o.kpi_name, o.kpi_name),
            'value':         o.current_avg,
            'vs_company_pct': o.vs_company_delta_pct,
            'reason':        o.outlier_reason,
            'percentile':    o.percentile_rank,
        }
        for o in outliers
        if _is_real_clinic(o.location_name)
    ]

    # Notable MoM changes — filter out non-clinic, convert month names
    all_comps = session.query(ChrComparisonResult).filter_by(
        run_month=run_month, client_name=client_name,
    ).filter(
        ChrComparisonResult.mom_delta_avg_pct.isnot(None),
        ChrComparisonResult.mom_is_meaningful == True,
    ).all()

    for c in all_comps:
        if not _is_real_clinic(c.location_name):
            continue
        if c.mom_delta_avg_pct is not None and abs(c.mom_delta_avg_pct) >= 3:
            context['mom_changes'].append({
                'location':     _clean_location_name(c.location_name),
                'kpi':          KPI_LABELS.get(c.kpi_name, c.kpi_name),
                'prior_month':  c.prior_month,
                'prior_label':  _month_name(c.prior_month) if c.prior_month else 'prior month',
                'prior_val':    c.prior_avg,
                'current_val':  c.current_avg,
                'pct_change':   c.mom_delta_avg_pct,
                'is_good':      c.mom_is_good,
            })

    context['mom_changes'].sort(key=lambda x: (not x['is_good'], -abs(x['pct_change'])))

    # Notable trends — filter out non-clinic
    trend_rows = session.query(ChrComparisonResult).filter(
        ChrComparisonResult.run_month   == run_month,
        ChrComparisonResult.client_name == client_name,
        ChrComparisonResult.trend_label.in_(['improving', 'declining']),
        ChrComparisonResult.trend_r2.isnot(None),
    ).filter(ChrComparisonResult.trend_r2 >= 0.6).all()

    for t in trend_rows:
        if not _is_real_clinic(t.location_name):
            continue
        context['trends'].append({
            'location':   _clean_location_name(t.location_name),
            'kpi':        KPI_LABELS.get(t.kpi_name, t.kpi_name),
            'label':      t.trend_label,
            'slope':      t.trend_slope,
            'r2':         t.trend_r2,
            'streak':     t.streak_count,
            'streak_dir': t.streak_direction,
            'ma3':        t.rolling_avg_3m,
            'ma6':        t.rolling_avg_6m,
            'current':    t.current_avg,
        })

    # Composite scores per location
    for loc in context['locations']:
        score_row = session.query(ChrComparisonResult).filter_by(
            run_month=run_month, client_name=client_name,
            location_name=loc['db_name'], source=KpiSource.IOPTIMIZE,
            kpi_name='scheduler_compliance',
        ).first()
        if score_row and score_row.composite_score is not None:
            context['composite_scores'][loc['name']] = score_row.composite_score

    # Correlations — ONLY include likely_causal and plausible_causal
    corr_rows = session.query(ChrKpiCorrelation).filter_by(
        run_month=run_month, client_name=client_name,
        should_highlight=True,
    ).all()
    for c in corr_rows:
        context['correlations'].append({
            'kpi1':        KPI_LABELS.get(c.kpi1_name, c.kpi1_name),
            'kpi2':        KPI_LABELS.get(c.kpi2_name, c.kpi2_name),
            'r':           c.kpi1_change_pct,
            'rel_type':    c.correlation_type,
            'narrative':   c.narrative_quality,
        })

    # Compute the biggest gap-to-benchmark for specific recommendations
    context['biggest_gap'] = _find_biggest_gap(context)

    return context


def _find_biggest_gap(context: dict) -> Optional[dict]:
    """
    Find the single biggest gap between a clinic and the company average.
    Used to generate specific (not generic) recommendations.
    """
    co = context.get('company_avg', {})
    gaps = []

    for loc in context['locations']:
        for kpi_name, label in [
            ('scheduler_compliance', 'Scheduler Compliance'),
            ('avg_delay_mins', 'Avg Delay'),
            ('avg_chair_utilization', 'Chair Utilization'),
            ('iassign_utilization', 'iAssign Utilization'),
        ]:
            loc_val = loc.get(kpi_name)
            co_val  = co.get(kpi_name)
            if loc_val is None or co_val is None:
                continue

            higher = HIGHER_IS_BETTER.get(kpi_name, True)
            if higher is True:
                gap = co_val - loc_val  # positive = below avg
            elif higher is False:
                gap = loc_val - co_val  # positive = above avg (bad)
            else:
                continue

            if gap > 0:  # only underperformers
                gaps.append({
                    'location': loc['name'],
                    'kpi': label,
                    'kpi_name': kpi_name,
                    'loc_val': loc_val,
                    'co_val': co_val,
                    'gap': gap,
                    'gap_pct': abs(gap / co_val * 100) if co_val != 0 else 0,
                })

    if not gaps:
        return None
    return max(gaps, key=lambda x: x['gap_pct'])


def _build_prompt(client_name: str, run_month: str, context: dict) -> str:
    month_label = context['month_label']

    # Current month data
    locations_text = ""
    for loc in context['locations']:
        score = context['composite_scores'].get(loc['name'])
        score_str = f" [Performance Score: {score:.0f}/100, where 50 = network average]" if score else ""
        locations_text += f"\n  {loc['name']}{score_str}:"
        if loc['scheduler_compliance'] is not None:
            locations_text += f"\n    Scheduler Compliance: {loc['scheduler_compliance']:.1f}%"
        if loc['avg_delay_mins'] is not None:
            locations_text += f"\n    Avg Delay: {loc['avg_delay_mins']:.1f} mins"
        if loc['avg_chair_utilization'] is not None:
            note = ""
            if loc['avg_chair_utilization'] > 100:
                note = " (>100% indicates overbooking — declining toward 100% may be healthy)"
            locations_text += f"\n    Chair Utilization: {loc['avg_chair_utilization']:.1f}%{note}"
        if loc['avg_treatments_per_day'] is not None:
            locations_text += f"\n    Treatments Past Closing/Day: {loc['avg_treatments_per_day']:.1f}"
        if loc['iassign_utilization'] is not None:
            locations_text += f"\n    iAssign Utilization: {loc['iassign_utilization']:.1f}%"
        if loc['avg_nurse_util'] is not None:
            locations_text += f"\n    Nurse Utilization: {loc['avg_nurse_util']:.1f}%"

    # MoM changes — with full month names
    mom_text = ""
    if context['mom_changes']:
        mom_text = "\nMONTH-OVER-MONTH CHANGES (meaningful, statistically tested):\n"
        for m in context['mom_changes'][:8]:
            direction = "improved" if m['is_good'] else "declined"
            mom_text += (
                f"  {m['location']} — {m['kpi']}: "
                f"{m['prior_val']:.1f} in {m['prior_label']} → "
                f"{m['current_val']:.1f} in {month_label} "
                f"({m['pct_change']:+.1f}%, {direction})\n"
            )

    # Multi-month trends
    trend_text = ""
    if context['trends']:
        trend_text = "\nMULTI-MONTH TRENDS (linear regression, R² ≥ 0.6 = consistent):\n"
        for t in context['trends'][:5]:
            streak_str = f", {t['streak']} consecutive months" if t['streak'] else ""
            ma_str = f", 3-month avg: {t['ma3']:.1f}" if t['ma3'] else ""
            trend_text += (
                f"  {t['location']} — {t['kpi']}: {t['label'].upper()} "
                f"(R²={t['r2']:.2f}{streak_str}{ma_str})\n"
            )

    # Correlations — WITH CAUSAL TYPE LABELLED
    corr_text = ""
    if context['correlations']:
        corr_text = "\nOPERATIONAL RELATIONSHIPS DETECTED (READ CAREFULLY):\n"
        for c in context['correlations']:
            if c['rel_type'] == 'likely_causal':
                lang_note = "Likely causal mechanism — you MAY say one 'may be driving' the other"
            elif c['rel_type'] == 'plausible_causal':
                lang_note = "Plausible mechanism — you MAY say one 'may be contributing to' the other"
            else:
                lang_note = "CORRELATION ONLY — do NOT imply causation; say 'are associated with'"
            corr_text += f"  {c['kpi1']} ↔ {c['kpi2']}: {c['narrative']}\n"
            corr_text += f"    [LANGUAGE RULE: {lang_note}]\n"

    # Outliers
    outlier_text = ""
    if context['outliers']:
        outlier_text = "\nSTATISTICAL OUTLIERS (significant deviation from company group):\n"
        for o in context['outliers']:
            pct_str = f"{o['vs_company_pct']:+.1f}%" if o['vs_company_pct'] else ""
            pct_str += f", P{o['percentile']:.0f}" if o.get('percentile') else ""
            outlier_text += f"  {o['location']} — {o['kpi']}: {o['reason']} ({pct_str})\n"

    co = context['company_avg']
    on = context['onco']

    # Build the biggest-gap info for specific recommendations
    gap = context.get('biggest_gap')
    gap_text = ""
    if gap:
        gap_text = (
            f"\nBIGGEST PERFORMANCE GAP (use this for your recommendation):\n"
            f"  {gap['location']} — {gap['kpi']}: {gap['loc_val']:.1f} vs company avg {gap['co_val']:.1f} "
            f"(gap: {gap['gap_pct']:.0f}%)\n"
            f"  Your recommendation MUST reference this specific clinic and KPI.\n"
            f"  Suggest a CONCRETE action: e.g. 'review scheduling templates', 'pilot iAssign training', "
            f"'audit nurse-to-chair assignments' — NOT 'conduct a deep dive'.\n"
        )

    # Onco line — only include if data exists
    onco_section = ""
    if on.get('scheduler_compliance') is not None:
        onco_section = (
            f"\nONCO NETWORK BENCHMARKS:\n"
            f"  Scheduler Compliance: {on.get('scheduler_compliance')}%  |  "
            f"Avg Delay: {on.get('avg_delay_mins')} mins  |  "
            f"Chair Utilization: {on.get('avg_chair_utilization')}%\n"
        )

    return f"""You are a senior clinical operations analyst at OncoSmart writing the {month_label} performance summary for {client_name}. You are writing directly to the COO.

WHAT THE METRICS MEAN:
- Scheduler Compliance: % of appointments following iOptimize recommendations. Higher = better scheduling discipline.
- Avg Delay: minutes patients wait before treatment. Lower = better patient flow.
- Treatments Past Closing/Day: how many run beyond closing time daily. Zero = perfect.
- Chair Utilization: % of chair capacity used. Higher = better asset use. NOTE: values >100% indicate overbooking — a gradual decline toward 100% should be framed as healthy normalisation, not a concern.
- iAssign Utilization: % assignments via iAssign. Higher = better adherence.
- Nurse Utilization: % of nurse capacity used. Closer to 100% = optimal.
- Performance Score: a composite 0-100 score where 50 = network average. Weighted blend of compliance, delay, chair utilization, iAssign adoption, overtime, and nurse utilization.

COMPANY AVERAGES ({month_label}):
  Scheduler Compliance: {co.get('scheduler_compliance')}%  |  Avg Delay: {co.get('avg_delay_mins')} mins  |  Chair Utilization: {co.get('avg_chair_utilization')}%
{onco_section}
CLINIC DATA:
{locations_text}
{mom_text}{trend_text}{corr_text}{outlier_text}{gap_text}

IMPORTANT — NON-CLINIC NAMES:
"Global Avg", "Company Avg", "Onco" etc. are BENCHMARKS, NOT real clinics. NEVER reference them by name as if they are a clinic location. Use the benchmark numbers in comparisons but never say "Global Avg showed..." or "Global Avg's performance..."

CRITICAL SCIENTIFIC PRINCIPLE:
Correlation is NOT causation. Two metrics moving together does not mean one causes the other.
They may both be caused by a third factor (e.g. patient volume drives both chair utilization AND delays).
Only use causal language when the LANGUAGE RULE explicitly permits it.
All other relationships must be described as associations only.

FORBIDDEN CAUSAL WORDS (unless LANGUAGE RULE says otherwise):
"translated into", "resulted in", "led to", "caused by", "causes", "driving", "driven by", "because of",
"contributed to", "contributing to", "impacted", "impacting", "enabled", "enabling", "fueled", "fueling",
"directly affected", "as a result of", "thanks to"
If no LANGUAGE RULE permits it, use ONLY: "associated with", "coincided with", "alongside", "at the same time as"

FORBIDDEN VAGUE ADJECTIVES (never use without a number):
"impressive", "remarkable", "notable", "significant", "strong", "exceptional", "substantial"
Instead of "impressive gains", say "a 20-point gain from 47.0% in January to 67.1% in February".
Instead of "strong compliance", say "compliance of 89.7%, above the company average of 80.0%".

WRITING RULES — NON-NEGOTIABLE:
1. Write in flowing paragraphs. No bullet points. No lists. No bold mid-sentence.
2. Sound like a thoughtful human consultant, not AI software. Use specific numbers. Name the clinics.
3. Tone: professional, warm, collaborative. Never alarmist. Never blame the clinic.
4. Use "we noticed", "the data suggests", "one area worth exploring together". Never prescriptive.
5. For TRENDS: reference actual months and values, not just "improving over time".
6. For CORRELATIONS: follow the LANGUAGE RULE strictly. Never say a correlation "proves" anything.
7. Reference the Performance Score when notable — always explain the scale (50 = network average).
8. Keep each field to 2-4 crisp sentences. No padding.
9. For CHAIR UTILIZATION >100%: frame a decline toward 100% as positive normalisation, NOT as a concern.

10. ANCHORED COMPARISONS — THE MOST IMPORTANT RULE:
   Every number you cite MUST be anchored to a specific reference point. The reader must ALWAYS know: compared to what? from when? which benchmark?

   REQUIRED patterns (use these exact structures):
   - MoM: "X rose from 42.3% in January to 66.7% in February" — ALWAYS name both months.
   - vs Company: "X's delay of 6.4 mins sits well below the company average of 11.2 mins" — ALWAYS state the benchmark number.
   - vs Onco: "Chair utilization of 95.2% exceeds the Onco benchmark of 68.0%" — ALWAYS state the Onco number.
   - Composite: "A composite score of 74 out of 100 (where 50 represents the network average)" — ALWAYS contextualize the scale.
   - Changes: "A 24-point improvement from 43.0% in January to 67.1% in February" — ALWAYS state before, after, AND months.

   FORBIDDEN patterns (never do these):
   - "compliance surged" — surged from what? to what? when?
   - "above the benchmark" without the benchmark number
   - "a 14.5% reduction" without saying from what prior value or which month
   - "sits lower than average" without stating what the average IS
   - "showed improvement" without before/after values
   - "strong performance" without a benchmark to compare against

   If you lack the comparison number, DON'T make the comparison.

Respond with ONLY raw JSON (no markdown, no backticks):
{{
  "executive_summary": "2-3 sentences. Every claim cites benchmark numbers and named months. Mention the overall company performance score average if available.",
  "highlights": "2-3 sentences celebrating 1-2 wins. Name clinic, current value, comparison value (company avg or prior month with month name), and the delta.",
  "areas_to_explore": "2-3 sentences on 1-2 opportunities. Name clinic, current value, benchmark number. Use 'we noticed' framing.",
  "recommendation": "1-2 sentences. Reference the BIGGEST GAP clinic and KPI by name. Suggest a SPECIFIC operational action (not 'deep dive'). Frame as collaborative."
}}"""


def _parse_ai_response(raw: str) -> List[dict]:
    try:
        clean = raw.strip()
        if clean.startswith('```'):
            clean = '\n'.join(clean.split('\n')[1:])
        if clean.endswith('```'):
            clean = '\n'.join(clean.split('\n')[:-1])
        clean = clean.strip()

        data     = json.loads(clean)
        insights = []

        if 'executive_summary' in data:
            insights.append({
                'type': 'executive_summary',
                'text': data['executive_summary'],
                'priority': 100, 'kpis': [], 'confidence': 0.95,
            })
        if 'highlights' in data:
            insights.append({
                'type': 'highlight',
                'text': data['highlights'],
                'priority': 80, 'kpis': [], 'confidence': 0.9,
            })
        if 'areas_to_explore' in data:
            insights.append({
                'type': 'concern',
                'text': data['areas_to_explore'],
                'priority': 70, 'kpis': [], 'confidence': 0.9,
            })
        if 'recommendation' in data:
            insights.append({
                'type': 'recommendation',
                'text': data['recommendation'],
                'priority': 60, 'kpis': [], 'confidence': 0.85,
            })

        return insights

    except Exception as e:
        log.error(f"Failed to parse AI response: {e}\nRaw: {raw[:300]}")
        return [{'type': 'executive_summary', 'text': raw[:800],
                 'priority': 100, 'kpis': [], 'confidence': 0.5}]


def _fallback_insights(context: dict) -> List[dict]:
    locs = context['locations']
    if not locs:
        return []

    valid = [l for l in locs if l['scheduler_compliance'] is not None]
    if not valid:
        return []

    best  = max(valid, key=lambda x: x['scheduler_compliance'])
    worst = min(valid, key=lambda x: x['scheduler_compliance'])
    n     = len(locs)

    summary = (
        f"{context['client']} operated across {n} location{'s' if n != 1 else ''} "
        f"in {context['month_label']}. Scheduler compliance ranged from "
        f"{worst['scheduler_compliance']:.1f}% ({worst['name']}) to "
        f"{best['scheduler_compliance']:.1f}% ({best['name']})."
    )
    return [{'type': 'executive_summary', 'text': summary,
             'priority': 100, 'kpis': ['scheduler_compliance'], 'confidence': 0.7}]