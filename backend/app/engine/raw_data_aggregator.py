"""
Raw Daily Data Aggregator

Reads the raw daily tables populated by raw_data_parser and writes
weekly + monthly rollups into chr_raw_data_summary. Each summary row
carries both a JSON metrics blob (for downstream lookup) and a short
human narrative the AI chatbot and insight engine can quote directly.

Categories (one per (client, location, period) combo):
  operations      → delay / overtime / chair utilization
  scheduler       → E/A/M counts + compliance, best/worst scheduler
  nurse           → nurse utilization stats
  staffing        → chairs/RN, patients/nurse
  service_dist    → MD + Tx + Inj coordination totals
  service_totals  → Treatment volume, visit duration, overtime minutes
  time_blocks     → % of Treatments in each time block (frontloading check)
"""
from __future__ import annotations

import json
import logging
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.db.models import (
    ChrRawDailyOperations,
    ChrRawDataSummary,
    ChrRawNurseUtilization,
    ChrRawSchedulerProductivity,
    ChrRawServiceDistribution,
    ChrRawServiceTotals,
    ChrRawStaffingMetrics,
    ChrRawTimeBlockDistribution,
)

log = logging.getLogger(__name__)


PERIOD_MONTHLY = "monthly"
PERIOD_WEEKLY  = "weekly"


# ─────────────────────────────────────────────────────────────
# Period helpers
# ─────────────────────────────────────────────────────────────

def _month_bounds(d: datetime) -> Tuple[datetime, datetime]:
    start = datetime(d.year, d.month, 1)
    end = datetime(d.year, d.month, monthrange(d.year, d.month)[1])
    return start, end


def _iso_week_bounds(d: datetime) -> Tuple[datetime, datetime]:
    # Monday of the ISO week → Sunday
    start_date = d.date() - timedelta(days=d.weekday())
    start = datetime(start_date.year, start_date.month, start_date.day)
    end = start + timedelta(days=6)
    return start, end


def _month_label(d: datetime) -> str:
    return d.strftime("%b %Y")


def _iso_week_label(d: datetime) -> str:
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _day_label(d: datetime) -> str:
    return d.strftime("%b %d")


# ─────────────────────────────────────────────────────────────
# Small arithmetic helpers
# ─────────────────────────────────────────────────────────────

def _avg(vals: Iterable[Optional[float]]) -> Optional[float]:
    xs = [v for v in vals if v is not None]
    return sum(xs) / len(xs) if xs else None


def _sum(vals: Iterable[Optional[float]]) -> float:
    return sum(v for v in vals if v is not None)


def _fmt(v: Optional[float], digits: int = 1, suffix: str = "") -> str:
    if v is None:
        return "—"
    return f"{v:.{digits}f}{suffix}"


# ─────────────────────────────────────────────────────────────
# Summary row writer (idempotent per ingest_id)
# ─────────────────────────────────────────────────────────────

def _write_summary(
    session: Session,
    client: str,
    location: str,
    period_type: str,
    period_start: datetime,
    period_end: datetime,
    category: str,
    metrics: dict,
    narrative: str,
    ingest_id: str,
) -> None:
    """
    Delete then insert. We delete ALL prior summaries for
    (client, location, period_type, period_start, category) regardless of
    ingest_id so re-runs always leave a single canonical narrative.
    """
    session.query(ChrRawDataSummary).filter_by(
        client_name=client,
        location_name=location,
        period_type=period_type,
        period_start=period_start,
        category=category,
    ).delete(synchronize_session=False)

    session.add(ChrRawDataSummary(
        client_name=client,
        location_name=location,
        period_type=period_type,
        period_start=period_start,
        period_end=period_end,
        category=category,
        metrics_json=json.dumps(metrics, default=str),
        narrative_text=narrative,
        ingest_id=ingest_id,
    ))


# ─────────────────────────────────────────────────────────────
# Category builders — operate on a list of raw rows for one period
# Each returns (metrics_dict, narrative_text) or (None, None) if no data
# ─────────────────────────────────────────────────────────────

def _build_operations(rows: List[ChrRawDailyOperations], location: str, period_label: str):
    if not rows:
        return None, None
    treatments = [r for r in rows if r.service_name == "Treatment"]
    source = treatments or rows

    delays = [r.avg_service_delay for r in source if r.avg_service_delay is not None]
    utils  = [r.chair_utilization_pct for r in source if r.chair_utilization_pct is not None]

    avg_delay = _avg(delays)
    peak_delay = max(delays) if delays else None
    peak_delay_row = max(
        (r for r in source if r.avg_service_delay is not None),
        key=lambda r: r.avg_service_delay,
        default=None,
    )
    peak_delay_date = peak_delay_row.schedule_date if peak_delay_row else None

    total_overtime = int(_sum(r.overtime_patients_per_day for r in source))
    avg_util = _avg(utils)
    peak_util_row = max(
        (r for r in source if r.chair_utilization_pct is not None),
        key=lambda r: r.chair_utilization_pct,
        default=None,
    )
    peak_util = peak_util_row.chair_utilization_pct if peak_util_row else None
    peak_util_date = peak_util_row.schedule_date if peak_util_row else None

    metrics = {
        "avg_delay": avg_delay,
        "peak_delay": peak_delay,
        "peak_delay_date": peak_delay_date.isoformat() if peak_delay_date else None,
        "total_overtime_patients": total_overtime,
        "avg_chair_utilization": avg_util,
        "peak_chair_utilization": peak_util,
        "peak_chair_utilization_date": peak_util_date.isoformat() if peak_util_date else None,
        "days_observed": len({r.schedule_date for r in source}),
    }

    parts = [f"{location} {period_label}: Treatment avg delay {_fmt(avg_delay, 1, ' min')}"]
    if peak_delay is not None and peak_delay_date is not None:
        parts.append(f"peak {_fmt(peak_delay, 1, ' min')} on {_day_label(peak_delay_date)}")
    parts.append(f"{total_overtime} overtime patients")
    narrative = (
        f"{', '.join(parts)}. Chair util averaged {_fmt(avg_util, 1, '%')}"
    )
    if peak_util is not None and peak_util_date is not None:
        narrative += f" (peak {_fmt(peak_util, 1, '%')} on {_day_label(peak_util_date)})."
    else:
        narrative += "."
    return metrics, narrative


def _build_scheduler(rows: List[ChrRawSchedulerProductivity], location: str, period_label: str):
    if not rows:
        return None, None
    totals = {"E": 0, "A": 0, "M": 0}
    per_scheduler: Dict[str, Dict[str, int]] = defaultdict(lambda: {"E": 0, "A": 0, "M": 0})
    for r in rows:
        if r.appt_type in totals:
            totals[r.appt_type] += r.patient_count
            per_scheduler[r.scheduler_name][r.appt_type] += r.patient_count

    denom = totals["E"] + totals["A"] + totals["M"]
    compliance = (totals["E"] + totals["A"]) / denom * 100 if denom else None

    def _sched_compliance(counts: Dict[str, int]) -> Optional[float]:
        d = counts["E"] + counts["A"] + counts["M"]
        return (counts["E"] + counts["A"]) / d * 100 if d else None

    ranked = [
        (name, _sched_compliance(counts), sum(counts.values()))
        for name, counts in per_scheduler.items()
    ]
    ranked = [r for r in ranked if r[1] is not None]
    ranked.sort(key=lambda x: x[1], reverse=True)

    best = ranked[0] if ranked else None
    worst = ranked[-1] if ranked else None

    metrics = {
        "total_exact": totals["E"],
        "total_approx": totals["A"],
        "total_manual": totals["M"],
        "compliance_pct": compliance,
        "scheduler_count": len(per_scheduler),
        "best_scheduler": {
            "name": best[0], "compliance_pct": best[1], "patients": best[2]
        } if best else None,
        "worst_scheduler": {
            "name": worst[0], "compliance_pct": worst[1], "patients": worst[2]
        } if worst else None,
    }

    parts = [
        f"{location} scheduler compliance: {_fmt(compliance, 1, '%')}"
        f" across {len(per_scheduler)} scheduler{'s' if len(per_scheduler) != 1 else ''} in {period_label}"
    ]
    if best and worst and best[0] != worst[0]:
        parts.append(
            f"Best: {best[0]} ({_fmt(best[1], 1, '%')}); Worst: {worst[0]} ({_fmt(worst[1], 1, '%')})"
        )
    parts.append(
        f"{totals['E']} Exact, {totals['A']} Approx, {totals['M']} Manual appointments"
    )
    narrative = ". ".join(parts) + "."
    return metrics, narrative


def _build_nurse(rows: List[ChrRawNurseUtilization], location: str, period_label: str):
    if not rows:
        return None, None
    utils = [r.nurse_utilization_pct for r in rows if r.nurse_utilization_pct is not None]
    if not utils:
        return None, None
    avg = sum(utils) / len(utils)
    lo, hi = min(utils), max(utils)
    metrics = {
        "avg_nurse_utilization_pct": avg,
        "min_nurse_utilization_pct": lo,
        "max_nurse_utilization_pct": hi,
        "days_observed": len(rows),
    }
    narrative = (
        f"{location} nurse utilization averaged {_fmt(avg, 1, '%')} in {period_label} "
        f"(range {_fmt(lo, 1, '%')}–{_fmt(hi, 1, '%')})."
    )
    return metrics, narrative


def _build_staffing(rows: List[ChrRawStaffingMetrics], location: str, period_label: str):
    if not rows:
        return None, None
    chairs = _avg(r.avg_chairs_per_rn for r in rows)
    patients = _avg(r.avg_patients for r in rows)
    metrics = {
        "avg_chairs_per_rn": chairs,
        "avg_patients_per_nurse": patients,
        "days_observed": len(rows),
    }
    narrative = (
        f"{location} averaged {_fmt(chairs, 2, '')} chairs/RN and "
        f"{_fmt(patients, 1, '')} patients/nurse in {period_label}."
    )
    return metrics, narrative


def _build_service_dist(rows: List[ChrRawServiceDistribution], location: str, period_label: str):
    if not rows:
        return None, None
    md_total = int(_sum(r.md_count for r in rows))
    md_with_tx = int(_sum(r.md_with_tx for r in rows))
    md_with_inj = int(_sum(r.md_with_inj for r in rows))
    tx_without_md = int(_sum(r.treatment_without_md for r in rows))
    inj_without_md = int(_sum(r.injection_without_md for r in rows))
    md_without_tx_inj = int(_sum(r.md_without_tx_inj for r in rows))
    ratio_tx_no_md_to_md_tx = (
        tx_without_md / md_with_tx if md_with_tx else None
    )
    metrics = {
        "total_md_visits": md_total,
        "total_md_with_tx": md_with_tx,
        "total_md_with_inj": md_with_inj,
        "total_treatment_without_md": tx_without_md,
        "total_injection_without_md": inj_without_md,
        "total_md_without_tx_inj": md_without_tx_inj,
        "ratio_tx_without_md_to_md_with_tx": ratio_tx_no_md_to_md_tx,
    }
    narrative = (
        f"{location} in {period_label}: {md_total} total MD visits, "
        f"{md_with_tx} MD+TX same-day, {tx_without_md} treatments without same-day MD visit."
    )
    return metrics, narrative


def _build_service_totals(rows: List[ChrRawServiceTotals], location: str, period_label: str):
    if not rows:
        return None, None
    treatments = [r for r in rows if r.service_name == "Treatment"]
    source = treatments or rows
    total_count = int(_sum(r.service_count for r in source))
    overtime_mins = int(_sum(r.mins_past_closing for r in source))
    # Visit duration avg: weight by service_count
    weighted_num = sum(
        (r.visit_duration_mins or 0) for r in source
    )
    weighted_den = sum(1 for r in source if r.visit_duration_mins is not None)
    avg_duration_per_day = (weighted_num / weighted_den) if weighted_den else None
    # Rough per-treatment average
    per_treatment = (weighted_num / total_count) if total_count else None

    metrics = {
        "total_treatments": total_count,
        "avg_visit_duration_per_day_mins": avg_duration_per_day,
        "avg_visit_duration_per_treatment_mins": per_treatment,
        "total_overtime_mins": overtime_mins,
        "days_observed": len({r.schedule_date for r in source}),
    }
    narrative = (
        f"{location} in {period_label}: {total_count} treatments, "
        f"avg visit duration {_fmt(per_treatment, 1, ' min')}, "
        f"{overtime_mins} total overtime mins past closing."
    )
    return metrics, narrative


def _build_time_blocks(rows: List[ChrRawTimeBlockDistribution], location: str, period_label: str):
    if not rows:
        return None, None
    treatments = [r for r in rows if r.service_name == "Treatment"]
    source = treatments or rows

    # Aggregate numerator/denominator across rows to get % in each block
    block_totals: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
    for r in source:
        if r.fraction_numerator is None or r.fraction_denominator is None:
            continue
        if r.fraction_denominator == 0:
            continue
        block_totals[r.time_block].append((r.fraction_numerator, r.fraction_denominator))

    # Convert to weighted percentages: sum_num / sum_den
    block_pct: Dict[str, float] = {}
    for block, pairs in block_totals.items():
        n = sum(p[0] for p in pairs)
        d = sum(p[1] for p in pairs)
        if d:
            block_pct[block] = n / d * 100

    ordered_blocks = ["Before 10am", "10am - 12pm", "12pm - 2pm", "2pm and Later"]
    short_duration_rows = [
        r for r in source if r.duration_mins is not None and r.duration_mins <= 60
    ]
    short_morning_pct = None
    if short_duration_rows:
        morning_pairs = [
            (r.fraction_numerator, r.fraction_denominator)
            for r in short_duration_rows
            if r.time_block in ("Before 10am", "10am - 12pm")
            and r.fraction_numerator is not None
            and r.fraction_denominator
        ]
        if morning_pairs:
            n = sum(p[0] for p in morning_pairs)
            d = sum(p[1] for p in morning_pairs)
            if d:
                short_morning_pct = n / d * 100

    metrics = {
        "block_pct": {b: block_pct.get(b) for b in ordered_blocks},
        "short_duration_morning_pct": short_morning_pct,
        "frontloaded": (short_morning_pct is not None and short_morning_pct > 60),
    }

    dist_str = ", ".join(
        f"{int(round(block_pct[b]))}% {b.lower()}"
        for b in ordered_blocks
        if b in block_pct
    )
    narrative = (
        f"{location} Treatment distribution in {period_label}: {dist_str or 'no data'}."
    )
    if metrics["frontloaded"]:
        narrative += (
            f" Short-duration treatments are frontloaded "
            f"({_fmt(short_morning_pct, 0, '%')} before noon)."
        )
    return metrics, narrative


# ─────────────────────────────────────────────────────────────
# Period grouping + orchestration
# ─────────────────────────────────────────────────────────────

def _group_by_period(
    rows: list, period_type: str
) -> Dict[Tuple[datetime, datetime], list]:
    """
    Group rows by the period they fall into. Rows must expose a
    'schedule_date' attribute. For scheduler rows (no date) this is
    not used — scheduler is aggregated across all rows for the ingest.
    """
    groups: Dict[Tuple[datetime, datetime], list] = defaultdict(list)
    for r in rows:
        d = r.schedule_date
        if d is None:
            continue
        if period_type == PERIOD_MONTHLY:
            start, end = _month_bounds(d)
        else:
            start, end = _iso_week_bounds(d)
        groups[(start, end)].append(r)
    return groups


def _locations_in(rows: list) -> List[str]:
    return sorted({r.location_name for r in rows})


def _label_for(period_type: str, start: datetime) -> str:
    return _month_label(start) if period_type == PERIOD_MONTHLY else _iso_week_label(start)


def compute_rollups(
    session: Session,
    client: str,
    ingest_id: str,
) -> Dict[str, int]:
    """
    Compute monthly and weekly rollups for every category and write to
    chr_raw_data_summary. Returns a dict of counts per category (monthly+weekly combined).
    """
    counts: Dict[str, int] = defaultdict(int)

    # Helper to process one category for one period granularity
    def process(period_type: str, rows: list, category: str, builder):
        groups = _group_by_period(rows, period_type)
        for (start, end), group in sorted(groups.items()):
            by_loc: Dict[str, list] = defaultdict(list)
            for r in group:
                by_loc[r.location_name].append(r)
            label = _label_for(period_type, start)
            for loc, loc_rows in sorted(by_loc.items()):
                metrics, narrative = builder(loc_rows, loc, label)
                if metrics is None:
                    continue
                _write_summary(
                    session, client, loc, period_type,
                    start, end, category, metrics, narrative, ingest_id,
                )
                counts[f"{category}_{period_type}"] += 1

    # ── operations ──
    ops_rows = session.query(ChrRawDailyOperations).filter_by(
        client_name=client, ingest_id=ingest_id
    ).all()
    process(PERIOD_MONTHLY, ops_rows, "operations", _build_operations)
    process(PERIOD_WEEKLY,  ops_rows, "operations", _build_operations)

    # ── nurse ──
    nurse_rows = session.query(ChrRawNurseUtilization).filter_by(
        client_name=client, ingest_id=ingest_id
    ).all()
    process(PERIOD_MONTHLY, nurse_rows, "nurse", _build_nurse)
    process(PERIOD_WEEKLY,  nurse_rows, "nurse", _build_nurse)

    # ── staffing ──
    staffing_rows = session.query(ChrRawStaffingMetrics).filter_by(
        client_name=client, ingest_id=ingest_id
    ).all()
    process(PERIOD_MONTHLY, staffing_rows, "staffing", _build_staffing)
    process(PERIOD_WEEKLY,  staffing_rows, "staffing", _build_staffing)

    # ── service_dist ──
    dist_rows = session.query(ChrRawServiceDistribution).filter_by(
        client_name=client, ingest_id=ingest_id
    ).all()
    process(PERIOD_MONTHLY, dist_rows, "service_dist", _build_service_dist)
    process(PERIOD_WEEKLY,  dist_rows, "service_dist", _build_service_dist)

    # ── service_totals ──
    totals_rows = session.query(ChrRawServiceTotals).filter_by(
        client_name=client, ingest_id=ingest_id
    ).all()
    process(PERIOD_MONTHLY, totals_rows, "service_totals", _build_service_totals)
    process(PERIOD_WEEKLY,  totals_rows, "service_totals", _build_service_totals)

    # ── time_blocks ──
    tb_rows = session.query(ChrRawTimeBlockDistribution).filter_by(
        client_name=client, ingest_id=ingest_id
    ).all()
    process(PERIOD_MONTHLY, tb_rows, "time_blocks", _build_time_blocks)
    process(PERIOD_WEEKLY,  tb_rows, "time_blocks", _build_time_blocks)

    # ── scheduler (no schedule_date on these rows — span the full ingest) ──
    sched_rows = session.query(ChrRawSchedulerProductivity).filter_by(
        client_name=client, ingest_id=ingest_id
    ).all()
    if sched_rows:
        # Anchor the scheduler rollup to the month covered by the operations rows
        # (scheduler CSV has no explicit date column).
        anchor = min((r.schedule_date for r in ops_rows), default=None) or datetime.utcnow()
        m_start, m_end = _month_bounds(anchor)
        w_start, w_end = _iso_week_bounds(anchor)
        by_loc: Dict[str, list] = defaultdict(list)
        for r in sched_rows:
            by_loc[r.location_name].append(r)
        for loc, loc_rows in sorted(by_loc.items()):
            # Monthly
            metrics, narrative = _build_scheduler(loc_rows, loc, _month_label(m_start))
            if metrics is not None:
                _write_summary(
                    session, client, loc, PERIOD_MONTHLY,
                    m_start, m_end, "scheduler", metrics, narrative, ingest_id,
                )
                counts["scheduler_monthly"] += 1
            # Weekly
            metrics_w, narrative_w = _build_scheduler(loc_rows, loc, _iso_week_label(w_start))
            if metrics_w is not None:
                _write_summary(
                    session, client, loc, PERIOD_WEEKLY,
                    w_start, w_end, "scheduler", metrics_w, narrative_w, ingest_id,
                )
                counts["scheduler_weekly"] += 1

    session.flush()
    return dict(counts)
