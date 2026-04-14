"""
God-Level Comparison Engine — Architected with Opus 4.6

Analytical layers:
  1. BENCHMARKING   — company avg, global avg (across all clients), rolling 3/6-month MA,
                      Onco benchmark, best-in-class (top decile across all history)
  2. STATISTICAL    — z-score, percentile rank (0-100 best), meaningful-change test,
                      volatility score (std dev last 6 months)
  3. TREND          — linear regression slope over last 3 data points, R² confidence,
                      consecutive-month streak (improving / declining)
  4. CORRELATION    — pairwise Pearson r across locations this month,
                      labelled as likely_causal / plausible_causal /
                      correlated_confounded / spurious
                      (causation ≠ correlation — never conflate them in AI prompts)
  5. COMPOSITE SCORE — weighted 0-100 performance score per location, with
                       volatility penalty

Key design principles:
  - Correlation is NOT causation. Every correlated pair is tagged with a relationship
    type so the AI never implies causation from correlation alone.
  - Only plausible operational causal chains are flagged as causal.
  - All benchmarks (company avg, global avg, best-in-class) are pre-computed before
    any per-location comparisons so every location sees the same reference numbers.
  - Statistical meaningfulness threshold prevents noise from being reported as signal.
"""
import difflib
import logging
import statistics
import json
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# KPI METADATA
# ─────────────────────────────────────────────────────────────

# True = higher is better, False = lower is better, None = context-dependent
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

# Composite score weights — only KPIs with clear directional meaning
# Must sum to 1.0
COMPOSITE_WEIGHTS = {
    'scheduler_compliance':            0.25,
    'avg_delay_mins':                  0.20,
    'avg_chair_utilization':           0.20,
    'iassign_utilization':             0.15,
    'avg_treatments_per_day':          0.10,
    'avg_nurse_to_patient_chair_time': 0.10,
}

# Known causal relationships in oncology clinic operations.
# Key = (cause_kpi, effect_kpi), value = relationship_type
# IMPORTANT: correlation ≠ causation.
# - likely_causal: strong operational mechanism, direction is clear
# - plausible_causal: reasonable mechanism but confounders exist
# - correlated_confounded: both driven by a third factor (e.g. patient volume)
# - spurious: no plausible mechanism; flag as noise if detected
CAUSAL_MAP = {
    ('scheduler_compliance', 'avg_delay_mins'):
        ('likely_causal',
         'Higher scheduling compliance reduces wait times via better appointment spacing'),
    ('scheduler_compliance', 'avg_treatments_per_day'):
        ('likely_causal',
         'Better scheduling reduces overtime treatments by preventing late-day stacking'),
    ('scheduler_compliance', 'avg_chair_utilization'):
        ('plausible_causal',
         'Compliance improves chair flow but utilisation also depends on patient volume'),
    ('iassign_utilization', 'avg_nurse_to_patient_chair_time'):
        ('likely_causal',
         'Higher iAssign adoption directly drives nurse-to-chair assignment efficiency'),
    ('avg_chair_utilization', 'avg_delay_mins'):
        ('correlated_confounded',
         'Both are driven by patient volume — correlation does not imply causation here'),
    ('avg_patients_per_nurse', 'avg_delay_mins'):
        ('plausible_causal',
         'Higher nurse load may cause delays but staffing decisions are the upstream cause'),
}

# Minimum n locations for z-score / percentile to be meaningful
MIN_N_FOR_STATS = 3

# MoM change is "meaningful" if |delta| > this fraction of historical std dev
MEANINGFUL_CHANGE_THRESHOLD = 0.5

# Volatility: std dev of last 6 months — above this z-score = high volatility
VOLATILITY_HIGH_THRESHOLD = 1.5

# Trend: abs(slope) below this = flat
TREND_FLAT_THRESHOLD = 0.5

# Outlier: z-score >= this = outlier
OUTLIER_Z_THRESHOLD = 1.5


# ─────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────

def run_comparisons(session: Session, run_month: str, run_id: str) -> int:
    from app.db.models import ChrKpiValue, ChrComparisonResult, ChrKpiWide, RowType, KpiSource

    clients = [r[0] for r in session.query(ChrKpiValue.client_name).filter_by(
        run_month=run_month
    ).distinct().all()]

    # ── Pre-compute global benchmarks (across ALL clients this month) ──
    global_benchmarks = _compute_global_benchmarks(session, run_month)

    # ── Pre-compute best-in-class (top decile across all history) ──────
    best_in_class = _compute_best_in_class(session)

    total = 0

    for client in clients:
        prior_month = _get_prior_month(session, client, run_month)

        for source_enum in [KpiSource.IOPTIMIZE, KpiSource.IASSIGN]:
            all_vals = session.query(ChrKpiValue).filter_by(
                run_month=run_month,
                client_name=client,
                source=source_enum,
            ).all()

            if not all_vals:
                continue

            company_vals = {v.kpi_name: v for v in all_vals if v.row_type == RowType.COMPANY_AVG}
            onco_vals    = {v.kpi_name: v for v in all_vals if v.row_type == RowType.ONCO}
            clinic_vals  = [v for v in all_vals if v.row_type == RowType.CLINIC]

            locations = list(set(v.location_name for v in clinic_vals))

            # ── Per-KPI group stats for this client/month ──────────────
            # {kpi_name: [list of avg values across all locations]}
            kpi_group_values: Dict[str, List[float]] = {}
            for loc in locations:
                for v in clinic_vals:
                    if v.location_name == loc and v.value_avg is not None:
                        kpi_group_values.setdefault(v.kpi_name, []).append(v.value_avg)

            # Company-level stats per KPI (mean, std)
            kpi_company_stats: Dict[str, Tuple[float, float]] = {}
            for kpi_name, vals in kpi_group_values.items():
                if len(vals) >= 2:
                    kpi_company_stats[kpi_name] = (
                        statistics.mean(vals),
                        statistics.stdev(vals),
                    )
                elif len(vals) == 1:
                    kpi_company_stats[kpi_name] = (vals[0], 0.0)

            # ── Wide row upserts ───────────────────────────────────────
            for location in locations:
                loc_vals = {v.kpi_name: v for v in clinic_vals if v.location_name == location}
                _upsert_wide_row(session, run_month, client, location,
                                 RowType.CLINIC, source_enum, loc_vals, run_id,
                                 all_vals[0].issue_number if all_vals else 0)

            for special_location, row_type, vals_dict in [
                ('Company Avg', RowType.COMPANY_AVG, company_vals),
                ('Onco',        RowType.ONCO,        onco_vals),
            ]:
                if vals_dict:
                    issue_num = list(vals_dict.values())[0].issue_number
                    _upsert_wide_row(session, run_month, client, special_location,
                                     row_type, source_enum, vals_dict, run_id, issue_num)

            # ── Per-location comparisons ───────────────────────────────
            for location in locations:
                loc_vals = {v.kpi_name: v for v in clinic_vals if v.location_name == location}

                for kpi_name, kpi_val in loc_vals.items():
                    company_val = company_vals.get(kpi_name)
                    onco_val    = onco_vals.get(kpi_name)
                    prior_val   = _get_prior_value(
                        session, client, location, source_enum, kpi_name, prior_month
                    )

                    # ── Statistical layer ──────────────────────────────
                    group_vals  = kpi_group_values.get(kpi_name, [])
                    co_stats    = kpi_company_stats.get(kpi_name)
                    z_score     = _z_score(kpi_val.value_avg, co_stats)
                    percentile  = _percentile_rank(
                        location, kpi_name, kpi_val.value_avg, kpi_group_values
                    )
                    is_outlier, outlier_reason = _detect_outlier(
                        kpi_name, kpi_val.value_avg, co_stats, z_score
                    )

                    # ── MoM meaningful-change test ─────────────────────
                    hist_std      = _historical_std(session, client, location, source_enum, kpi_name, run_month)
                    mom_meaningful = _is_mom_meaningful(
                        kpi_val.value_avg, prior_val.value_avg if prior_val else None, hist_std
                    )

                    # ── Volatility ─────────────────────────────────────
                    volatility_score = _volatility_score(
                        session, client, location, source_enum, kpi_name, run_month
                    )
                    volatility_label = _volatility_label(volatility_score, hist_std)

                    # ── Trend layer ────────────────────────────────────
                    (trend_slope, trend_r2,
                     trend_label, streak_count,
                     streak_direction) = _compute_trend(
                        session, client, location, source_enum, kpi_name, run_month
                    )

                    # ── Rolling averages ───────────────────────────────
                    ma3 = _rolling_avg(session, client, location, source_enum, kpi_name, run_month, 3)
                    ma6 = _rolling_avg(session, client, location, source_enum, kpi_name, run_month, 6)

                    # ── Global & best-in-class benchmarks ─────────────
                    global_avg = global_benchmarks.get((source_enum, kpi_name))
                    bic_val    = best_in_class.get((source_enum, kpi_name))

                    # ── Composite score component ──────────────────────
                    composite_component = _composite_component(
                        kpi_name, kpi_val.value_avg,
                        global_benchmarks, best_in_class,
                        source_enum
                    )

                    # ── Build and upsert result ────────────────────────
                    comp = _build_comparison(
                        run_month=run_month,
                        client_name=client,
                        location_name=location,
                        source=source_enum,
                        kpi_name=kpi_name,
                        current=kpi_val,
                        company=company_val,
                        onco=onco_val,
                        prior=prior_val,
                        z_score=z_score,
                        percentile=percentile,
                        is_outlier=is_outlier,
                        outlier_reason=outlier_reason,
                        mom_meaningful=mom_meaningful,
                        volatility_score=volatility_score,
                        volatility_label=volatility_label,
                        trend_slope=trend_slope,
                        trend_r2=trend_r2,
                        trend_label=trend_label,
                        streak_count=streak_count,
                        streak_direction=streak_direction,
                        ma3=ma3,
                        ma6=ma6,
                        global_avg=global_avg,
                        best_in_class=bic_val,
                        composite_component=composite_component,
                        run_id=run_id,
                    )

                    existing = session.query(ChrComparisonResult).filter_by(
                        run_month=run_month, client_name=client,
                        location_name=location, source=source_enum,
                        kpi_name=kpi_name,
                    ).first()

                    if existing:
                        for k, v in comp.items():
                            setattr(existing, k, v)
                    else:
                        session.add(ChrComparisonResult(**comp))

                    total += 1

            session.commit()

        # ── Composite score: aggregate components per location ─────────
        _compute_composite_scores(session, client, run_month, run_id)

        # ── Correlation analysis ───────────────────────────────────────
        _compute_correlations(session, client, run_month, run_id)

        session.commit()
        log.info(f"[{client}] {run_month}: comparisons complete")

    return total


# ─────────────────────────────────────────────────────────────
# BENCHMARKING
# ─────────────────────────────────────────────────────────────

def _compute_global_benchmarks(session, run_month: str) -> Dict:
    """
    Global average per KPI across ALL clients and ALL clinic locations this month.
    This is the true network-wide average — different from any single client's company avg.
    """
    from app.db.models import ChrKpiValue, RowType
    rows = session.query(ChrKpiValue).filter_by(
        run_month=run_month, row_type=RowType.CLINIC
    ).filter(ChrKpiValue.value_avg.isnot(None)).all()

    buckets: Dict[Tuple, List[float]] = {}
    for r in rows:
        key = (r.source, r.kpi_name)
        buckets.setdefault(key, []).append(r.value_avg)

    return {
        key: round(statistics.mean(vals), 4)
        for key, vals in buckets.items() if vals
    }


def _compute_best_in_class(session) -> Dict:
    """
    Top-decile (90th percentile) value across ALL clients, ALL months, ALL clinic locations.
    This is the aspirational benchmark — "what the best clinics achieve."
    Only computed once from full history.
    """
    from app.db.models import ChrKpiValue, RowType
    rows = session.query(ChrKpiValue).filter_by(
        row_type=RowType.CLINIC
    ).filter(ChrKpiValue.value_avg.isnot(None)).all()

    buckets: Dict[Tuple, List[float]] = {}
    for r in rows:
        key = (r.source, r.kpi_name)
        buckets.setdefault(key, []).append(r.value_avg)

    result = {}
    for key, vals in buckets.items():
        if not vals:
            continue
        kpi_name = key[1]
        higher   = HIGHER_IS_BETTER.get(kpi_name)
        sorted_v = sorted(vals)
        idx      = int(len(sorted_v) * 0.9)
        # Top decile: 90th pct for "higher=better", 10th pct for "lower=better"
        if higher is False:
            idx  = max(0, int(len(sorted_v) * 0.1))
        result[key] = round(sorted_v[min(idx, len(sorted_v)-1)], 4)
    return result


def _rolling_avg(session, client_name, location_name, source, kpi_name, run_month, n) -> Optional[float]:
    """Rolling n-month average ending at run_month (inclusive)."""
    from app.db.models import ChrKpiValue, RowType
    rows = session.query(ChrKpiValue.value_avg).filter(
        ChrKpiValue.client_name    == client_name,
        ChrKpiValue.location_name  == location_name,
        ChrKpiValue.source         == source,
        ChrKpiValue.kpi_name       == kpi_name,
        ChrKpiValue.row_type       == RowType.CLINIC,
        ChrKpiValue.run_month      <= run_month,
        ChrKpiValue.value_avg.isnot(None),
    ).order_by(ChrKpiValue.run_month.desc()).limit(n).all()

    vals = [r[0] for r in rows if r[0] is not None]
    if len(vals) < 2:
        return None
    return round(statistics.mean(vals), 4)


# ─────────────────────────────────────────────────────────────
# STATISTICAL LAYER
# ─────────────────────────────────────────────────────────────

def _z_score(value: Optional[float], stats: Optional[Tuple[float, float]]) -> Optional[float]:
    """Z-score vs the company group this month. Positive = above mean."""
    if value is None or stats is None:
        return None
    mean, std = stats
    if std == 0:
        return 0.0
    return round((value - mean) / std, 3)


def _percentile_rank(location: str, kpi_name: str, value: Optional[float],
                     kpi_group_values: Dict[str, List[float]]) -> Optional[float]:
    """
    0-100 percentile rank where 100 = best performer (direction-aware).
    Uses the company group this month.
    """
    if value is None:
        return None
    all_vals = kpi_group_values.get(kpi_name, [])
    if len(all_vals) < MIN_N_FOR_STATS:
        return None
    higher   = HIGHER_IS_BETTER.get(kpi_name, True)
    sorted_v = sorted(all_vals)
    rank     = sum(1 for v in sorted_v if v <= value)
    raw_pct  = rank / len(sorted_v) * 100
    return round((100 - raw_pct) if higher is False else raw_pct, 1)


def _detect_outlier(kpi_name: str, value: Optional[float],
                    stats: Optional[Tuple[float, float]],
                    z_score: Optional[float]) -> Tuple[bool, Optional[str]]:
    """
    Outlier if |z| >= OUTLIER_Z_THRESHOLD (default 1.5 std devs).
    Returns (is_outlier, human-readable reason).
    """
    if value is None or z_score is None or stats is None:
        return False, None
    if abs(z_score) < OUTLIER_Z_THRESHOLD:
        return False, None
    mean, std = stats
    direction = 'above' if z_score > 0 else 'below'
    higher    = HIGHER_IS_BETTER.get(kpi_name)
    # Determine if this outlier is a good or bad thing
    is_good   = (z_score > 0 and higher is True) or (z_score < 0 and higher is False)
    qualifier = 'strong performer' if is_good else 'needs attention'
    return True, (
        f"{abs(z_score):.1f}σ {direction} group mean ({mean:.1f}) — {qualifier}"
    )


def _historical_std(session, client_name, location_name, source, kpi_name, run_month,
                    n_months: int = 6) -> Optional[float]:
    """Std dev of this location's KPI over the last n_months (excluding current)."""
    from app.db.models import ChrKpiValue, RowType
    rows = session.query(ChrKpiValue.value_avg).filter(
        ChrKpiValue.client_name   == client_name,
        ChrKpiValue.location_name == location_name,
        ChrKpiValue.source        == source,
        ChrKpiValue.kpi_name      == kpi_name,
        ChrKpiValue.row_type      == RowType.CLINIC,
        ChrKpiValue.run_month     < run_month,
        ChrKpiValue.value_avg.isnot(None),
    ).order_by(ChrKpiValue.run_month.desc()).limit(n_months).all()

    vals = [r[0] for r in rows if r[0] is not None]
    if len(vals) < 2:
        return None
    return statistics.stdev(vals)


def _is_mom_meaningful(current: Optional[float], prior: Optional[float],
                       hist_std: Optional[float]) -> Optional[bool]:
    """
    Is the MoM change statistically meaningful?
    Meaningful if |delta| > MEANINGFUL_CHANGE_THRESHOLD * historical_std.
    Returns None if insufficient history to judge.
    """
    if current is None or prior is None:
        return None
    delta = abs(current - prior)
    if hist_std is None or hist_std == 0:
        # No history — use a 3% absolute threshold as fallback
        return delta > 3.0
    return delta > (MEANINGFUL_CHANGE_THRESHOLD * hist_std)


def _volatility_score(session, client_name, location_name, source, kpi_name,
                      run_month) -> Optional[float]:
    """
    Std dev of last 6 months of this KPI at this location.
    Higher = more volatile performance.
    """
    return _historical_std(session, client_name, location_name, source, kpi_name, run_month, 6)


def _volatility_label(vol_score: Optional[float], hist_std: Optional[float]) -> Optional[str]:
    if vol_score is None:
        return None
    if hist_std is None:
        return 'unknown'
    # Compare volatility to the historical std — rough z-score concept
    if vol_score > hist_std * VOLATILITY_HIGH_THRESHOLD:
        return 'high'
    if vol_score > hist_std * 0.8:
        return 'moderate'
    return 'stable'


# ─────────────────────────────────────────────────────────────
# TREND LAYER
# ─────────────────────────────────────────────────────────────

def _compute_trend(session, client_name, location_name, source, kpi_name,
                   run_month) -> Tuple[Optional[float], Optional[float],
                                       Optional[str], Optional[int], Optional[str]]:
    """
    Returns (slope, R², trend_label, streak_count, streak_direction).

    slope: units-per-month (positive = going up)
    R²: 0-1, how consistent is the trend (1 = perfectly linear)
    trend_label: 'improving' | 'declining' | 'stable' | None
    streak_count: how many consecutive months in same direction
    streak_direction: 'improving' | 'declining' | None
    """
    from app.db.models import ChrKpiValue, RowType

    rows = session.query(ChrKpiValue.run_month, ChrKpiValue.value_avg).filter(
        ChrKpiValue.client_name   == client_name,
        ChrKpiValue.location_name == location_name,
        ChrKpiValue.source        == source,
        ChrKpiValue.kpi_name      == kpi_name,
        ChrKpiValue.row_type      == RowType.CLINIC,
        ChrKpiValue.run_month     <= run_month,
        ChrKpiValue.value_avg.isnot(None),
    ).order_by(ChrKpiValue.run_month.asc()).limit(6).all()

    if len(rows) < 3:
        return None, None, None, None, None

    # x = month index (0, 1, 2...), y = value
    x = list(range(len(rows)))
    y = [r[1] for r in rows]

    slope, r2 = _linear_regression(x, y)

    if slope is None:
        return None, None, None, None, None

    higher     = HIGHER_IS_BETTER.get(kpi_name)
    flat       = abs(slope) < TREND_FLAT_THRESHOLD

    if flat:
        trend_label = 'stable'
    elif higher is True:
        trend_label = 'improving' if slope > 0 else 'declining'
    elif higher is False:
        trend_label = 'improving' if slope < 0 else 'declining'
    else:
        trend_label = 'stable'

    # Streak detection — last N consecutive months in same direction
    streak_count, streak_dir = _compute_streak(y, higher)

    return (
        round(slope, 4),
        round(r2, 3),
        trend_label,
        streak_count,
        streak_dir,
    )


def _linear_regression(x: List[float], y: List[float]) -> Tuple[Optional[float], Optional[float]]:
    """Simple OLS: returns (slope, R²)."""
    n = len(x)
    if n < 2:
        return None, None
    try:
        x_mean = statistics.mean(x)
        y_mean = statistics.mean(y)
        ss_xy  = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
        ss_xx  = sum((xi - x_mean) ** 2 for xi in x)
        if ss_xx == 0:
            return 0.0, 0.0
        slope  = ss_xy / ss_xx
        # R²
        y_pred = [y_mean + slope * (xi - x_mean) for xi in x]
        ss_res = sum((yi - yp) ** 2 for yi, yp in zip(y, y_pred))
        ss_tot = sum((yi - y_mean) ** 2 for yi in y)
        r2     = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
        return slope, max(0.0, r2)
    except Exception:
        return None, None


def _compute_streak(values: List[float], higher_is_better: Optional[bool]) -> Tuple[Optional[int], Optional[str]]:
    """
    How many consecutive recent months has this location been improving or declining?
    Returns (streak_length, 'improving'|'declining'|None).
    """
    if len(values) < 2 or higher_is_better is None:
        return None, None

    # Walk backwards from most recent
    streak    = 1
    direction = None

    for i in range(len(values) - 1, 0, -1):
        delta = values[i] - values[i-1]
        if abs(delta) < 0.05:  # flat
            break
        current_dir = 'improving' if (
            (delta > 0 and higher_is_better is True) or
            (delta < 0 and higher_is_better is False)
        ) else 'declining'

        if direction is None:
            direction = current_dir
        if current_dir != direction:
            break
        streak += 1

    return streak if streak >= 2 else None, direction


# ─────────────────────────────────────────────────────────────
# CORRELATION vs CAUSATION LAYER
# ─────────────────────────────────────────────────────────────

def _compute_correlations(session, client_name: str, run_month: str, run_id: str):
    """
    Compute pairwise Pearson correlations across clinic locations for this client/month.

    CRITICAL: Correlation ≠ Causation.
    Every correlated pair is tagged with a relationship_type from CAUSAL_MAP.
    The AI prompt must use this tag to choose appropriate language.

    - likely_causal: AI can say "may be driving"
    - plausible_causal: AI can say "may be contributing to"
    - correlated_confounded: AI must say "are both associated with" (no causal language)
    - spurious: AI should NOT mention — statistical noise
    """
    from app.db.models import ChrKpiValue, ChrKpiCorrelation, RowType, KpiSource

    # Delete existing correlations for this client/month
    session.query(ChrKpiCorrelation).filter_by(
        run_month=run_month, client_name=client_name
    ).delete()

    for source_enum in [KpiSource.IOPTIMIZE, KpiSource.IASSIGN]:
        rows = session.query(ChrKpiValue).filter_by(
            run_month=run_month, client_name=client_name,
            source=source_enum, row_type=RowType.CLINIC,
        ).filter(ChrKpiValue.value_avg.isnot(None)).all()

        if not rows:
            continue

        # Build {location: {kpi_name: value}} map
        by_location: Dict[str, Dict[str, float]] = {}
        for r in rows:
            by_location.setdefault(r.location_name, {})[r.kpi_name] = r.value_avg

        locations = list(by_location.keys())
        if len(locations) < MIN_N_FOR_STATS:
            continue  # too few locations for meaningful correlation

        kpi_names = list({kpi for loc_d in by_location.values() for kpi in loc_d})

        # Pairwise Pearson r
        for i, kpi1 in enumerate(kpi_names):
            for kpi2 in kpi_names[i+1:]:
                vals1 = [by_location[loc].get(kpi1) for loc in locations]
                vals2 = [by_location[loc].get(kpi2) for loc in locations]

                # Drop pairs where either is missing
                pairs = [(a, b) for a, b in zip(vals1, vals2) if a is not None and b is not None]
                if len(pairs) < MIN_N_FOR_STATS:
                    continue

                x = [p[0] for p in pairs]
                y = [p[1] for p in pairs]
                r = _pearson_r(x, y)

                if r is None or abs(r) < 0.5:  # only store meaningful correlations
                    continue

                # Look up causal classification
                rel_type, rel_narrative = CAUSAL_MAP.get(
                    (kpi1, kpi2),
                    CAUSAL_MAP.get(
                        (kpi2, kpi1),
                        ('correlated_unknown',
                         f'Statistical correlation (r={r:.2f}) detected. '
                         f'No established operational mechanism — treat with caution.')
                    )
                )

                # should_highlight only for likely/plausible causal, not confounded or spurious
                should_highlight = rel_type in ('likely_causal', 'plausible_causal') and abs(r) >= 0.7

                session.add(ChrKpiCorrelation(
                    run_month=run_month,
                    client_name=client_name,
                    location_name='_group',  # group-level, not single location
                    kpi1_source=source_enum,
                    kpi1_name=kpi1,
                    kpi1_change_pct=round(r, 3),  # reusing field for Pearson r
                    kpi2_source=source_enum,
                    kpi2_name=kpi2,
                    kpi2_change_pct=round(abs(r), 3),
                    correlation_type=rel_type,
                    narrative_quality=rel_narrative,
                    should_highlight=should_highlight,
                    run_id=run_id,
                ))

    session.commit()


def _pearson_r(x: List[float], y: List[float]) -> Optional[float]:
    """Pearson correlation coefficient."""
    n = len(x)
    if n < 3:
        return None
    try:
        x_mean = statistics.mean(x)
        y_mean = statistics.mean(y)
        num    = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
        den_x  = (sum((xi - x_mean) ** 2 for xi in x)) ** 0.5
        den_y  = (sum((yi - y_mean) ** 2 for yi in y)) ** 0.5
        if den_x == 0 or den_y == 0:
            return None
        return round(num / (den_x * den_y), 4)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# COMPOSITE PERFORMANCE SCORE
# ─────────────────────────────────────────────────────────────

def _composite_component(kpi_name: str, value: Optional[float],
                          global_benchmarks: Dict, best_in_class: Dict,
                          source) -> Optional[float]:
    """
    Normalise one KPI to 0-100 for the composite score.
    Uses global avg as 50-point baseline and best-in-class as 100-point ceiling.

    Formula:
      normalised = (value - global_avg) / (best_in_class - global_avg) * 50 + 50
      clamped to [0, 100]

    For lower-is-better KPIs, the direction is inverted.
    """
    if value is None or kpi_name not in COMPOSITE_WEIGHTS:
        return None
    higher   = HIGHER_IS_BETTER.get(kpi_name)
    if higher is None:
        return None

    g_avg = global_benchmarks.get((source, kpi_name))
    bic   = best_in_class.get((source, kpi_name))

    if g_avg is None or bic is None or abs(bic - g_avg) < 0.001:
        return 50.0  # no benchmark data — neutral score

    if higher is False:
        # Lower is better: invert so lower value = higher score
        normed = (g_avg - value) / abs(bic - g_avg) * 50 + 50
    else:
        normed = (value - g_avg) / abs(bic - g_avg) * 50 + 50

    return round(max(0.0, min(100.0, normed)), 2)


def _compute_composite_scores(session, client_name: str, run_month: str, run_id: str):
    """
    Compute the weighted composite score (0-100) per location.
    Applies a volatility penalty: score * (1 - 0.1 * volatility_factor)
    Stored in ChrComparisonResult.composite_score field.
    """
    from app.db.models import ChrComparisonResult, KpiSource

    locations = [r[0] for r in session.query(ChrComparisonResult.location_name).filter_by(
        run_month=run_month, client_name=client_name, source=KpiSource.IOPTIMIZE,
    ).distinct().all()]

    for location in locations:
        components: List[Tuple[float, float]] = []  # (weight, component_score)
        volatility_scores: List[float] = []

        for kpi_name, weight in COMPOSITE_WEIGHTS.items():
            row = session.query(ChrComparisonResult).filter_by(
                run_month=run_month, client_name=client_name,
                location_name=location, source=KpiSource.IOPTIMIZE,
                kpi_name=kpi_name,
            ).first()

            if row and row.composite_component is not None:
                components.append((weight, row.composite_component))
            if row and row.volatility_score is not None:
                volatility_scores.append(row.volatility_score)

        if not components:
            continue

        # Weighted average
        total_weight = sum(w for w, _ in components)
        raw_score    = sum(w * s for w, s in components) / total_weight

        # Volatility penalty (0-10% reduction)
        if volatility_scores:
            avg_vol = statistics.mean(volatility_scores)
            # Normalise volatility penalty: cap at 10% reduction
            vol_penalty = min(0.10, avg_vol / 100)
            final_score = raw_score * (1 - vol_penalty)
        else:
            final_score = raw_score

        final_score = round(max(0.0, min(100.0, final_score)), 2)

        # Write composite score back to all KPI rows for this location
        session.query(ChrComparisonResult).filter_by(
            run_month=run_month, client_name=client_name,
            location_name=location, source=KpiSource.IOPTIMIZE,
        ).update({'composite_score': final_score})


# ─────────────────────────────────────────────────────────────
# COMPARISON RESULT BUILDER
# ─────────────────────────────────────────────────────────────

def _build_comparison(run_month, client_name, location_name, source, kpi_name,
                       current, company, onco, prior,
                       z_score, percentile, is_outlier, outlier_reason,
                       mom_meaningful, volatility_score, volatility_label,
                       trend_slope, trend_r2, trend_label,
                       streak_count, streak_direction,
                       ma3, ma6, global_avg, best_in_class,
                       composite_component, run_id) -> dict:

    cur_avg  = current.value_avg
    cur_med  = current.value_median
    higher   = HIGHER_IS_BETTER.get(kpi_name)

    # vs Company Avg
    co_val      = company.value_avg if company else None
    vs_co_delta = _delta(cur_avg, co_val)
    vs_co_pct   = _pct_delta(cur_avg, co_val)

    # vs Onco Benchmark
    on_val      = onco.value_avg if onco else None
    vs_on_delta = _delta(cur_avg, on_val)
    vs_on_pct   = _pct_delta(cur_avg, on_val)
    vs_on_dir   = None
    if vs_on_delta is not None:
        vs_on_dir = 'above' if vs_on_delta > 0 else ('below' if vs_on_delta < 0 else 'at')

    # vs Global (all clients this month)
    vs_global_delta = _delta(cur_avg, global_avg)
    vs_global_pct   = _pct_delta(cur_avg, global_avg)

    # vs Best-in-Class
    vs_bic_delta = _delta(cur_avg, best_in_class)
    vs_bic_pct   = _pct_delta(cur_avg, best_in_class)

    # MoM
    pr_avg        = prior.value_avg if prior else None
    pr_med        = prior.value_median if prior else None
    mom_delta_avg = _delta(cur_avg, pr_avg)
    mom_delta_pct = _pct_delta(cur_avg, pr_avg)
    mom_dir  = None
    mom_good = None
    if mom_delta_avg is not None:
        mom_dir  = 'up' if mom_delta_avg > 0 else ('down' if mom_delta_avg < 0 else 'flat')
        if higher is True:
            mom_good = mom_delta_avg > 0
        elif higher is False:
            mom_good = mom_delta_avg < 0

    return dict(
        run_month=run_month,
        client_name=client_name,
        location_name=location_name,
        source=source,
        kpi_name=kpi_name,

        # Current
        current_avg=cur_avg,
        current_median=cur_med,

        # MoM
        prior_month=prior.run_month if prior else None,
        prior_avg=pr_avg,
        prior_median=pr_med,
        mom_delta_avg=mom_delta_avg,
        mom_delta_avg_pct=mom_delta_pct,
        mom_delta_median=_delta(cur_med, pr_med),
        mom_delta_median_pct=_pct_delta(cur_med, pr_med),
        mom_direction=mom_dir,
        mom_is_good=mom_good,
        mom_is_meaningful=mom_meaningful,

        # vs Company
        company_avg_value=co_val,
        vs_company_delta=vs_co_delta,
        vs_company_delta_pct=vs_co_pct,
        vs_company_rank=percentile,

        # vs Onco
        onco_value=on_val,
        vs_onco_delta=vs_on_delta,
        vs_onco_delta_pct=vs_on_pct,
        vs_onco_direction=vs_on_dir,

        # vs Global (all clients this month)
        global_avg_value=global_avg,
        vs_global_delta=vs_global_delta,
        vs_global_delta_pct=vs_global_pct,

        # vs Best-in-Class (top decile all history)
        best_in_class_value=best_in_class,
        vs_best_in_class_pct=vs_bic_pct,

        # Statistical
        z_score=z_score,
        percentile_rank=percentile,
        is_outlier=is_outlier,
        outlier_reason=outlier_reason,

        # Volatility
        volatility_score=volatility_score,
        volatility_label=volatility_label,

        # Trend
        trend_slope=trend_slope,
        trend_r2=trend_r2,
        trend_label=trend_label,
        streak_count=streak_count,
        streak_direction=streak_direction,

        # Rolling averages
        rolling_avg_3m=ma3,
        rolling_avg_6m=ma6,

        # Composite score component (filled in later)
        composite_component=composite_component,
        composite_score=None,  # filled by _compute_composite_scores

        run_id=run_id,
    )


# ─────────────────────────────────────────────────────────────
# WIDE ROW UPSERT
# ─────────────────────────────────────────────────────────────

def _upsert_wide_row(session, run_month, client_name, location_name,
                     row_type, source_enum, vals_dict, run_id, issue_number):
    from app.db.models import ChrKpiWide

    def v(kpi):
        val = vals_dict.get(kpi)
        return val.value_avg if val else None

    def m(kpi):
        val = vals_dict.get(kpi)
        return val.value_median if val else None

    data = dict(
        run_month=run_month, client_name=client_name,
        location_name=location_name, row_type=row_type, source=source_enum,
        scheduler_compliance=v('scheduler_compliance'),
        delay_avg=v('avg_delay_mins'), delay_median=m('avg_delay_mins'),
        treatments_avg=v('avg_treatments_per_day'), treatments_median=m('avg_treatments_per_day'),
        tx_mins_avg=v('avg_treatment_mins_per_patient'), tx_mins_median=m('avg_treatment_mins_per_patient'),
        chair_util_avg=v('avg_chair_utilization'), chair_util_median=m('avg_chair_utilization'),
        iassign_utilization=v('iassign_utilization'),
        patients_per_nurse_avg=v('avg_patients_per_nurse'), patients_per_nurse_median=m('avg_patients_per_nurse'),
        chairs_per_nurse_avg=v('avg_chairs_per_nurse'), chairs_per_nurse_median=m('avg_chairs_per_nurse'),
        nurse_util_avg=v('avg_nurse_to_patient_chair_time'), nurse_util_median=m('avg_nurse_to_patient_chair_time'),
        issue_number=issue_number, run_id=run_id,
    )

    existing = session.query(ChrKpiWide).filter_by(
        run_month=run_month, client_name=client_name,
        location_name=location_name, source=source_enum,
    ).first()

    if existing:
        for k, val in data.items():
            setattr(existing, k, val)
    else:
        session.add(ChrKpiWide(**data))


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _delta(a, b):
    if a is None or b is None:
        return None
    return round(a - b, 4)

def _pct_delta(a, b):
    if a is None or b is None or b == 0:
        return None
    return round((a - b) / abs(b) * 100, 2)

def _get_prior_month(session, client_name, run_month):
    """Most recent month before run_month that has real clinic KPI data."""
    from app.db.models import ChrKpiValue, RowType
    result = session.query(ChrKpiValue.run_month).filter(
        ChrKpiValue.client_name == client_name,
        ChrKpiValue.run_month   < run_month,
        ChrKpiValue.row_type    == RowType.CLINIC,
        ChrKpiValue.value_avg.isnot(None),
    ).order_by(ChrKpiValue.run_month.desc()).first()
    return result[0] if result else None

def _get_prior_value(session, client_name, location_name, source, kpi_name, prior_month):
    """
    Fetch the prior-month KPI row for this location.

    Strategy:
      1. Exact match on location_name (fast path, covers 95% of cases).
      2. Fuzzy match via difflib if the exact name changed between months
         (e.g. "Blue Pod" in Feb → "LHCP - Blue" in Mar).
         Requires similarity >= 0.72 to reduce false positives.
    """
    if not prior_month:
        return None
    from app.db.models import ChrKpiValue, RowType

    # ── Fast path: exact name match ──────────────────────────────────
    result = session.query(ChrKpiValue).filter_by(
        run_month=prior_month, client_name=client_name,
        location_name=location_name, source=source, kpi_name=kpi_name,
    ).first()
    if result:
        return result

    # ── Fuzzy path: location was renamed between months ───────────────
    prior_locs = [
        r[0] for r in session.query(ChrKpiValue.location_name).filter_by(
            run_month=prior_month, client_name=client_name,
            source=source, row_type=RowType.CLINIC,
        ).distinct().all()
    ]
    if not prior_locs:
        return None

    matches = difflib.get_close_matches(location_name, prior_locs, n=1, cutoff=0.72)
    if not matches:
        return None

    fuzzy_name = matches[0]
    log.debug(
        "Fuzzy location match: '%s' → '%s' (%s / %s)",
        location_name, fuzzy_name, client_name, prior_month
    )
    return session.query(ChrKpiValue).filter_by(
        run_month=prior_month, client_name=client_name,
        location_name=fuzzy_name, source=source, kpi_name=kpi_name,
    ).first()