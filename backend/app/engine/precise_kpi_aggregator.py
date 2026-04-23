"""
Precise KPI Aggregator — Bhaskar's 2024-10 Formulas

Computes per-(clinic x month) and per-(clinic x week) KPIs directly from
chr_raw_schedule_list + chr_raw_visit_list + chr_raw_daily_operations.
Persists results to chr_precise_kpi and returns a chatbot_context-ready dict.

KPIs 1, 6, 7, 8, 9 are skipped -- their source columns are not yet ingested.
KPIs 2, 3, 4, 5 + duration deviation metrics are computed from row-level data.
"""
from __future__ import annotations

import logging
import math
from calendar import monthrange
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.db.models import (
    ChrPreciseKpi,
    ChrRawDailyOperations,
    ChrRawScheduleList,
    ChrRawVisitList,
)

log = logging.getLogger(__name__)

FORMULA_VERSION      = "2024-10"
TREATMENT_TYPE       = "Treatment"
OPERATING_MINS_DEF   = 480   # 8-hour default
RAMP_UP_MINS         = 60
RAMP_DOWN_MINS       = 45
USABLE_FACTOR        = 0.80
WINDOW_MINS          = 30    # 30-min concurrent-visit bucket for chair derivation


# ─────────────────────────────────────────────────────────────
# Time helpers
# ─────────────────────────────────────────────────────────────

def _to_mins(t) -> Optional[float]:
    """datetime.time -> total minutes since midnight."""
    if t is None:
        return None
    return t.hour * 60 + t.minute + t.second / 60.0


def _to_date(d):
    return d.date() if hasattr(d, "date") else d


# ─────────────────────────────────────────────────────────────
# Clinic-level constant derivation (run once per clinic)
# ─────────────────────────────────────────────────────────────

def _derive_clinic_constants(
    session: Session, client: str, location: str
) -> Tuple[int, int, Optional[int]]:
    """
    Returns (num_chairs_derived, operating_mins_per_day, long_duration_threshold_mins).

    num_chairs  = 90th-percentile of daily max-concurrent Treatment visits
                  in any WINDOW_MINS-minute bucket (over all 6 months of data).
    op_mins     = median of (latest_visit_end - earliest_visit_start) per active day,
                  clamped to [240, 600].  Defaults to 480 if data is sparse.
    threshold   = 90th percentile of treatment visit durations for this clinic.
    """
    rows = (
        session.query(
            ChrRawVisitList.visit_date,
            ChrRawVisitList.visit_start_time,
            ChrRawVisitList.visit_end_time,
            ChrRawVisitList.total_visit_service_duration,
        )
        .filter(
            ChrRawVisitList.client_name == client,
            ChrRawVisitList.location_name == location,
            ChrRawVisitList.service_type_name == TREATMENT_TYPE,
            ChrRawVisitList.visit_start_time.isnot(None),
        )
        .all()
    )

    if not rows:
        return 4, OPERATING_MINS_DEF, None

    # Group by date
    by_date: Dict = defaultdict(list)
    durations: List[int] = []
    for vdate, start_t, end_t, dur in rows:
        d = _to_date(vdate)
        start_m = _to_mins(start_t)
        end_m   = _to_mins(end_t)
        if start_m is not None:
            by_date[d].append((start_m, end_m))
        if dur is not None and dur > 0:
            durations.append(int(dur))

    # Operating minutes per day (median daily range)
    daily_ranges = []
    for d, visits in by_date.items():
        starts = [s for s, _ in visits]
        ends   = [e for _, e in visits if e is not None]
        if starts and ends:
            daily_ranges.append(max(ends) - min(starts))
    if daily_ranges:
        daily_ranges.sort()
        op_mins = int(daily_ranges[len(daily_ranges) // 2])
        op_mins = max(240, min(600, op_mins))
    else:
        op_mins = OPERATING_MINS_DEF

    # Num chairs: 90th-pctile of per-day max-concurrent
    daily_peak: List[int] = []
    for d, visits in by_date.items():
        buckets: Dict[int, int] = defaultdict(int)
        for start_m, end_m in visits:
            end_m = end_m or (start_m + 60)
            b_start = int(start_m // WINDOW_MINS)
            b_end   = int(math.ceil(end_m / WINDOW_MINS))
            for b in range(b_start, b_end):
                buckets[b] += 1
        if buckets:
            daily_peak.append(max(buckets.values()))

    if daily_peak:
        daily_peak.sort()
        idx = min(len(daily_peak) - 1, int(len(daily_peak) * 0.90))
        num_chairs = max(1, daily_peak[idx])
    else:
        num_chairs = 4

    # Long-duration threshold: 90th pctile of visit durations
    long_dur_threshold: Optional[int] = None
    if durations:
        durations.sort()
        idx = min(len(durations) - 1, int(len(durations) * 0.90))
        long_dur_threshold = durations[idx]

    return num_chairs, op_mins, long_dur_threshold


# ─────────────────────────────────────────────────────────────
# Period helpers
# ─────────────────────────────────────────────────────────────

def _month_periods(session: Session, client: str, location: str):
    """Yield (period_start, period_end, label) for each distinct month with data."""
    from sqlalchemy import func as sqlfunc
    rows = (
        session.query(sqlfunc.date_trunc("month", ChrRawVisitList.visit_date).label("m"))
        .filter(
            ChrRawVisitList.client_name == client,
            ChrRawVisitList.location_name == location,
            ChrRawVisitList.service_type_name == TREATMENT_TYPE,
        )
        .distinct()
        .order_by("m")
        .all()
    )
    for (m,) in rows:
        m_dt = datetime(m.year, m.month, 1) if not isinstance(m, datetime) else datetime(m.year, m.month, 1)
        last_day = monthrange(m_dt.year, m_dt.month)[1]
        end = datetime(m_dt.year, m_dt.month, last_day, 23, 59, 59)
        yield m_dt, end, m_dt.strftime("%Y-%m")


def _week_periods(session: Session, client: str, location: str):
    """Yield (period_start, period_end, label) for each distinct ISO week with data."""
    rows = (
        session.query(ChrRawVisitList.visit_date)
        .filter(
            ChrRawVisitList.client_name == client,
            ChrRawVisitList.location_name == location,
            ChrRawVisitList.service_type_name == TREATMENT_TYPE,
        )
        .distinct()
        .all()
    )
    weeks = set()
    for (d,) in rows:
        dt = datetime(d.year, d.month, d.day) if not isinstance(d, datetime) else d
        monday = dt - timedelta(days=dt.weekday())
        monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
        weeks.add(monday)
    for monday in sorted(weeks):
        sunday = monday + timedelta(days=6, hours=23, minutes=59, seconds=59)
        iso = monday.isocalendar()
        label = f"{iso[0]}-W{iso[1]:02d}"
        yield monday, sunday, label


# ─────────────────────────────────────────────────────────────
# Per-period KPI computation
# ─────────────────────────────────────────────────────────────

def _compute_period(
    session: Session,
    client: str,
    location: str,
    period_start: datetime,
    period_end: datetime,
    num_chairs: int,
    op_mins: int,
    long_dur_threshold: Optional[int],
) -> Optional[dict]:
    """
    Compute all precise KPIs for one (clinic, period) bucket.
    Returns None if no visit data exists for this period.
    """
    # Scheduled rows (Treatment, within period)
    sched_rows = (
        session.query(
            ChrRawScheduleList.patient_id,
            ChrRawScheduleList.schedule_date,
            ChrRawScheduleList.service_name,
            ChrRawScheduleList.scheduled_start_time,
            ChrRawScheduleList.total_service_duration,
        )
        .filter(
            ChrRawScheduleList.client_name == client,
            ChrRawScheduleList.location_name == location,
            ChrRawScheduleList.service_type_name == TREATMENT_TYPE,
            ChrRawScheduleList.schedule_date >= period_start,
            ChrRawScheduleList.schedule_date <= period_end,
        )
        .all()
    )

    # Visit rows (Treatment, within period)
    visit_rows = (
        session.query(
            ChrRawVisitList.patient_id,
            ChrRawVisitList.visit_date,
            ChrRawVisitList.service_name,
            ChrRawVisitList.visit_start_time,
            ChrRawVisitList.visit_end_time,
            ChrRawVisitList.total_visit_service_duration,
        )
        .filter(
            ChrRawVisitList.client_name == client,
            ChrRawVisitList.location_name == location,
            ChrRawVisitList.service_type_name == TREATMENT_TYPE,
            ChrRawVisitList.visit_date >= period_start,
            ChrRawVisitList.visit_date <= period_end,
        )
        .all()
    )

    if not visit_rows:
        return None

    # Days clinic open: distinct scheduled dates (Bhaskar: use schedule list, not visit list)
    sched_dates = {_to_date(r[1]) for r in sched_rows}
    days_open = len(sched_dates) if sched_dates else len({_to_date(r[1]) for r in visit_rows})
    if days_open == 0:
        days_open = 1  # safety guard

    # Daily ops rows (Treatment, for KPIs 3 & 4)
    ops_rows = (
        session.query(ChrRawDailyOperations)
        .filter(
            ChrRawDailyOperations.client_name == client,
            ChrRawDailyOperations.location_name == location,
            ChrRawDailyOperations.service_name == TREATMENT_TYPE,
            ChrRawDailyOperations.schedule_date >= period_start,
            ChrRawDailyOperations.schedule_date <= period_end,
        )
        .all()
    )

    # ── KPI 2: Avg Delay ────────────────────────────────────────────
    # Join on (patient_id, date, service_name); clamp negatives to 0
    sched_map: Dict[Tuple, float] = {}
    for pid, sdate, sname, start_t, _ in sched_rows:
        if start_t is None:
            continue
        key = (str(pid), _to_date(sdate), str(sname or ""))
        sched_map[key] = _to_mins(start_t)

    delays: List[float] = []
    for pid, vdate, sname, vstart_t, _, _ in visit_rows:
        if vstart_t is None:
            continue
        key = (str(pid), _to_date(vdate), str(sname or ""))
        sched_m = sched_map.get(key)
        if sched_m is not None:
            visit_m = _to_mins(vstart_t)
            if visit_m is not None:
                delays.append(max(0.0, visit_m - sched_m))

    # Also average using daily_ops if join matches are too sparse
    ops_delays = [r.avg_service_delay for r in ops_rows if r.avg_service_delay is not None]
    if len(delays) >= 10:
        avg_delay = sum(delays) / len(delays)
        delay_count = len(delays)
    elif ops_delays:
        # Fall back to pre-aggregated per-day avg
        avg_delay = sum(ops_delays) / len(ops_delays)
        delay_count = len(ops_delays)
    else:
        avg_delay = None
        delay_count = 0

    # ── KPI 3: Tx Past Close / Day ───────────────────────────────────
    tx_past_close_total = sum(
        int(r.overtime_patients_per_day or 0)
        for r in ops_rows
        if r.overtime_patients_per_day is not None
    )
    tx_past_close_per_day = tx_past_close_total / days_open if days_open else None

    # ── KPI 4: Mins Past Close / Patient ─────────────────────────────
    total_overtime_mins = 0.0
    for r in ops_rows:
        if r.overtime_mins_per_patient is not None and r.overtime_patients_per_day:
            total_overtime_mins += float(r.overtime_mins_per_patient) * float(r.overtime_patients_per_day)
    mins_past_close_per_pt = (
        total_overtime_mins / tx_past_close_total
        if tx_past_close_total > 0 else None
    )

    # ── KPI 5: Chair Utilization ─────────────────────────────────────
    total_visit_dur = sum(
        int(r[5] or 0) for r in visit_rows if r[5] is not None
    )
    usable_per_day = (op_mins - RAMP_UP_MINS - RAMP_DOWN_MINS) * USABLE_FACTOR
    capacity = usable_per_day * num_chairs * days_open
    chair_util_pct = (total_visit_dur / capacity * 100) if capacity > 0 else None

    # ── Long-duration % ──────────────────────────────────────────────
    long_dur_count = 0
    dur_total = 0
    for _, _, _, _, _, dur in visit_rows:
        if dur is not None and dur > 0:
            dur_total += 1
            if long_dur_threshold is not None and dur >= long_dur_threshold:
                long_dur_count += 1
    long_dur_pct = (
        long_dur_count / dur_total * 100
        if dur_total > 0 and long_dur_threshold is not None else None
    )

    # ── Duration deviation >10% from scheduled ───────────────────────
    sched_dur_map: Dict[Tuple, int] = {}
    for pid, sdate, sname, _, sdur in sched_rows:
        if sdur is None or sdur <= 0:
            continue
        key = (str(pid), _to_date(sdate), str(sname or ""))
        sched_dur_map[key] = int(sdur)

    over_count = 0
    under_count = 0
    matched = 0
    for pid, vdate, sname, _, _, vdur in visit_rows:
        if vdur is None or vdur <= 0:
            continue
        key = (str(pid), _to_date(vdate), str(sname or ""))
        sdur = sched_dur_map.get(key)
        if not sdur or sdur <= 0:
            continue
        matched += 1
        ratio = int(vdur) / sdur
        if ratio > 1.10:
            over_count += 1
        elif ratio < 0.90:
            under_count += 1

    return {
        "avg_delay_mins":              round(avg_delay, 2) if avg_delay is not None else None,
        "delay_treatment_count":       delay_count,
        "delay_days_open":             days_open,
        "tx_past_close_per_day":       round(tx_past_close_per_day, 2) if tx_past_close_per_day is not None else None,
        "tx_past_close_count":         tx_past_close_total,
        "mins_past_close_per_pt":      round(mins_past_close_per_pt, 2) if mins_past_close_per_pt is not None else None,
        "mins_past_close_total":       round(total_overtime_mins, 2),
        "tx_past_close_for_mins":      tx_past_close_total,
        "chair_utilization_pct":       round(chair_util_pct, 2) if chair_util_pct is not None else None,
        "total_visit_duration_mins":   total_visit_dur,
        "num_chairs_derived":          num_chairs,
        "operating_mins_per_day":      op_mins,
        "long_duration_treatment_pct": round(long_dur_pct, 2) if long_dur_pct is not None else None,
        "long_duration_threshold_mins": long_dur_threshold,
        "duration_deviation_over_count":  over_count,
        "duration_deviation_under_count": under_count,
        "duration_matched_pairs_count":   matched,
    }


# ─────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────

def compute_precise_kpis(session: Session, client_name: str) -> dict:
    """
    Compute and persist precise KPI rows for all (clinic x month) and
    (clinic x week) combinations found in the raw visit data.

    Returns a chatbot_context-ready dict with per_month, per_week,
    clinic_constants, and metadata.
    """
    # Discover treatment-active locations
    locations = [
        r[0] for r in
        session.query(ChrRawVisitList.location_name)
        .filter(
            ChrRawVisitList.client_name == client_name,
            ChrRawVisitList.service_type_name == TREATMENT_TYPE,
        )
        .distinct()
        .order_by(ChrRawVisitList.location_name)
        .all()
    ]

    log.info("precise_kpis: %s | locations: %s", client_name, locations)

    # Wipe existing rows for this client
    deleted = session.query(ChrPreciseKpi).filter_by(
        client_name=client_name
    ).delete(synchronize_session=False)
    log.info("precise_kpis: deleted %d stale rows for %s", deleted, client_name)

    clinic_constants: dict = {}
    per_month: List[dict] = []
    per_week: List[dict] = []

    for location in locations:
        num_chairs, op_mins, long_threshold = _derive_clinic_constants(
            session, client_name, location
        )
        clinic_constants[location] = {
            "num_chairs_derived":         num_chairs,
            "derivation_method":          f"90th-pctile of daily max-concurrent Treatment visits in {WINDOW_MINS}-min windows",
            "operating_minutes_per_day":  op_mins,
            "long_duration_threshold_minutes": long_threshold,
            "long_duration_definition":   "90th-percentile of Treatment visit durations for this clinic (6-month window)",
        }

        # Monthly
        for p_start, p_end, label in _month_periods(session, client_name, location):
            metrics = _compute_period(session, client_name, location, p_start, p_end,
                                      num_chairs, op_mins, long_threshold)
            if metrics is None:
                continue
            session.add(ChrPreciseKpi(
                client_name=client_name, location_name=location,
                period_type="monthly", period_start=p_start,
                period_label=label, formula_version=FORMULA_VERSION,
                **metrics,
            ))
            per_month.append({"location": location, "period": label, **metrics})

        # Weekly
        for p_start, p_end, label in _week_periods(session, client_name, location):
            metrics = _compute_period(session, client_name, location, p_start, p_end,
                                      num_chairs, op_mins, long_threshold)
            if metrics is None:
                continue
            session.add(ChrPreciseKpi(
                client_name=client_name, location_name=location,
                period_type="weekly", period_start=p_start,
                period_label=label, formula_version=FORMULA_VERSION,
                **metrics,
            ))
            per_week.append({"location": location, "period": label, **metrics})

    session.flush()
    log.info(
        "precise_kpis: %s | wrote %d monthly + %d weekly rows across %d clinics",
        client_name, len(per_month), len(per_week), len(locations),
    )

    return {
        "source": (
            "Recomputed from chr_raw_schedule_list + chr_raw_visit_list "
            "using Bhaskar's 2024-10 formulas"
        ),
        "formula_version": FORMULA_VERSION,
        "kpis_computed": [
            "avg_delay_mins (KPI 2)",
            "tx_past_close_per_day (KPI 3)",
            "mins_past_close_per_pt (KPI 4)",
            "chair_utilization_pct (KPI 5, with derived chair count)",
            "long_duration_treatment_pct",
            "duration_deviation_over_10pct",
        ],
        "kpis_not_computed": {
            "scheduler_compliance": "Missing appointment_type (E/A/M) per scheduled visit",
            "iassign_utilization":  "Missing iassign_used binary flag per scheduled day",
            "patients_per_nurse":   "Missing nurse_availability_fraction per nurse per day",
            "chairs_per_nurse":     "Inherits patients_per_nurse data gap",
            "nurse_utilization":    "Definition deferred by team (KPI 9)",
        },
        "clinic_constants": clinic_constants,
        "per_month":         per_month,
        "per_week":          per_week,
    }
