"""
Raw Daily Data Parser

Auto-detects and ingests 9 operational CSV types into the raw-data tables:

  daily_operations        → chr_raw_daily_operations
  scheduler_productivity  → chr_raw_scheduler_productivity
  nurse_utilization       → chr_raw_nurse_utilization
  staffing_metrics        → chr_raw_staffing_metrics
  service_distribution    → chr_raw_service_distribution
  service_totals          → chr_raw_service_totals
  time_block_distribution → chr_raw_time_block_distribution
  schedule_list           → chr_raw_schedule_list
  visit_list              → chr_raw_visit_list

Idempotent: a re-run for the same (client, ingest_id, csv_type) deletes
existing rows with that ingest_id for that table before re-inserting.
"""
from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass
from datetime import datetime, time as datetime_time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.db.models import (
    ChrRawDailyOperations,
    ChrRawSchedulerProductivity,
    ChrRawNurseUtilization,
    ChrRawStaffingMetrics,
    ChrRawServiceDistribution,
    ChrRawServiceTotals,
    ChrRawTimeBlockDistribution,
    ChrRawScheduleList,
    ChrRawVisitList,
)

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Location mapping per client
# CSVs use raw clinic IDs — the app shows anonymised names.
# ─────────────────────────────────────────────────────────────
LOCATION_MAPS: Dict[str, Dict[str, str]] = {
    "DEMO": {
        "Clinic 4001": "Clinic 1",
        "Clinic 4002": "Clinic 2",
        "Clinic 4003": "Clinic 3",
        "Clinic 4004": "Clinic 4",
    }
}


# ─────────────────────────────────────────────────────────────
# CSV type detection — based on header column names
# ─────────────────────────────────────────────────────────────
CSV_DAILY_OPERATIONS       = "daily_operations"
CSV_SCHEDULER_PRODUCTIVITY = "scheduler_productivity"
CSV_NURSE_UTILIZATION      = "nurse_utilization"
CSV_STAFFING_METRICS       = "staffing_metrics"
CSV_SERVICE_DISTRIBUTION   = "service_distribution"
CSV_SERVICE_TOTALS         = "service_totals"
CSV_TIME_BLOCK             = "time_block_distribution"
CSV_SCHEDULE_LIST          = "schedule_list"
CSV_VISIT_LIST             = "visit_list"

ALL_CSV_TYPES = (
    CSV_DAILY_OPERATIONS,
    CSV_SCHEDULER_PRODUCTIVITY,
    CSV_NURSE_UTILIZATION,
    CSV_STAFFING_METRICS,
    CSV_SERVICE_DISTRIBUTION,
    CSV_SERVICE_TOTALS,
    CSV_TIME_BLOCK,
    CSV_SCHEDULE_LIST,
    CSV_VISIT_LIST,
)


def detect_csv_type(headers: Iterable[str]) -> Optional[str]:
    """Return one of the CSV_* constants, or None if unrecognised."""
    norm = {_norm_header(h) for h in headers}

    if _has(norm, "average service delay"):
        return CSV_DAILY_OPERATIONS
    if _has(norm, "scheduler name") and _has(norm, "appttype"):
        return CSV_SCHEDULER_PRODUCTIVITY
    if any("iassign_nurse_utilization" in h for h in norm):
        return CSV_NURSE_UTILIZATION
    if any("iassign_average_chairs_per_rn" in h for h in norm):
        return CSV_STAFFING_METRICS
    if _has(norm, "md count") or _has(norm, "total md"):
        return CSV_SERVICE_DISTRIBUTION
    if _has(norm, "delay (mins)") and _has(norm, "service count"):
        return CSV_SERVICE_TOTALS
    if any("fraction_by_time_block" in h for h in norm) or _has(norm, "timeblockdescription"):
        return CSV_TIME_BLOCK
    if _has(norm, "scheduled_start_time"):
        return CSV_SCHEDULE_LIST
    if _has(norm, "visit_start_time"):
        return CSV_VISIT_LIST
    return None


def _norm_header(h: str) -> str:
    """Lowercase, strip BOM + whitespace — nothing else (preserves spaces)."""
    return (h or "").lstrip("\ufeff").strip().lower()


def _has(norm: set, key: str) -> bool:
    return key in norm


# ─────────────────────────────────────────────────────────────
# Value parsers
# ─────────────────────────────────────────────────────────────

def _parse_pct(val: Optional[str]) -> Optional[float]:
    """'110.86 %' → 110.86 ; '' or None → None."""
    if val is None:
        return None
    s = str(val).strip().rstrip("%").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_float(val: Optional[str]) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_int(val: Optional[str], default: Optional[int] = None) -> Optional[int]:
    if val is None:
        return default
    s = str(val).strip()
    if not s:
        return default
    try:
        return int(float(s))
    except ValueError:
        return default


def _parse_int_zero(val: Optional[str]) -> int:
    """Blank/missing numeric cells → 0 (for count columns)."""
    out = _parse_int(val, default=0)
    return out if out is not None else 0


def _parse_float_zero(val: Optional[str]) -> float:
    out = _parse_float(val)
    return out if out is not None else 0.0


def _parse_date(val: Optional[str]) -> Optional[datetime]:
    """'2026-03-25 00:00:00' or '2026-03-25' → datetime."""
    if not val:
        return None
    s = str(val).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    log.warning("Could not parse date: %r", val)
    return None


def _parse_time(val: Optional[str]) -> Optional[datetime_time]:
    """'1899-12-30 11:00:00' or '11:00:00' → datetime.time — Excel time-only encoding."""
    if not val:
        return None
    s = str(val).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    log.warning("Could not parse time: %r", val)
    return None


_FRACTION_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")


def _parse_fraction(val: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    """'11/69' → (11, 69). Returns (None, None) on failure."""
    if not val:
        return None, None
    m = _FRACTION_RE.match(str(val).strip())
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


# ─────────────────────────────────────────────────────────────
# service_type inference
# ─────────────────────────────────────────────────────────────

_SERVICE_TYPES = {"Treatment", "Injection", "MD", "Lab", "Outside Infusion", "Research"}


def _infer_service_type(service_name: str) -> str:
    """
    For the current DEMO data, service_name == service_type.
    For future clients (pod names, etc.), map back to the broad category.
    """
    if not service_name:
        return "Treatment"
    s = service_name.strip()
    if s in _SERVICE_TYPES:
        return s
    lower = s.lower()
    if "injection" in lower or lower == "inj":
        return "Injection"
    if "infusion" in lower:
        return "Outside Infusion"
    if lower == "md":
        return "MD"
    if lower == "lab":
        return "Lab"
    # Pod/area names default to Treatment
    return "Treatment"


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

@dataclass
class IngestResult:
    csv_path: str
    csv_type: Optional[str]
    rows_parsed: int
    rows_inserted: int
    errors: List[str]


def find_csv_files(path: str) -> List[Path]:
    """Recursively return every .csv under *path*, sorted for determinism."""
    root = Path(path)
    if not root.exists():
        raise FileNotFoundError(f"Raw data path not found: {path}")
    return sorted(root.rglob("*.csv"))


def _read_csv(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    """
    Return (headers, rows). Handles BOM gracefully.
    Row keys are normalised (lowercased, BOM-stripped) so callers can
    use _get_row(row, 'location') regardless of the source casing.
    """
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        raw_headers = list(reader.fieldnames or [])
        headers = [_norm_header(h) for h in raw_headers]
        # Map raw → normalised so we can rebuild each row dict with normalised keys
        key_map = {raw: norm for raw, norm in zip(raw_headers, headers)}
        rows = [
            {key_map[k]: v for k, v in row.items() if k in key_map}
            for row in reader
        ]
    return headers, rows


def _map_location(client: str, location: str) -> Optional[str]:
    """Apply LOCATION_MAPS or pass through if unknown."""
    if not location:
        return None
    loc_map = LOCATION_MAPS.get(client, {})
    mapped = loc_map.get(location.strip())
    return mapped if mapped is not None else location.strip()


def _clear_for_ingest(session: Session, model, client: str, ingest_id: str) -> None:
    """Delete existing rows for this (model, client, ingest_id) — idempotent re-runs."""
    session.query(model).filter_by(client_name=client, ingest_id=ingest_id).delete(
        synchronize_session=False
    )


def _get_row(row: Dict[str, str], *aliases: str) -> Optional[str]:
    """Look up a row value by one or more lowercase header aliases."""
    for a in aliases:
        v = row.get(a)
        if v is not None and str(v).strip() != "":
            return v
    # Fall-through for keys that exist but are empty
    for a in aliases:
        if a in row:
            return row.get(a)
    return None


# ─────────────────────────────────────────────────────────────
# Per-CSV-type ingest routines
# Each returns count of rows inserted.
# ─────────────────────────────────────────────────────────────

def _ingest_daily_operations(
    session: Session, client: str, rows: List[Dict[str, str]], ingest_id: str
) -> int:
    inserted = 0
    for row in rows:
        loc = _map_location(client, _get_row(row, "location") or "")
        date = _parse_date(_get_row(row, "date"))
        svc_name = (_get_row(row, "service name") or "").strip()
        if not loc or date is None or not svc_name:
            continue
        session.add(ChrRawDailyOperations(
            client_name=client,
            location_name=loc,
            schedule_date=date,
            service_type=_infer_service_type(svc_name),
            service_name=svc_name,
            avg_service_delay=_parse_float(_get_row(row, "average service delay")),
            median_avg_delay=_parse_float(_get_row(row, "median average delay")),
            overtime_patients_per_day=_parse_int_zero(_get_row(row, "overtime patient per day")),
            median_overtime_patients=_parse_int_zero(_get_row(row, "median overtime patient")),
            overtime_mins_per_patient=_parse_float_zero(_get_row(
                row,
                "overtime mins per dayper patient",
                "overtime mins per day per patient",
            )),
            median_overtime_mins=_parse_float_zero(_get_row(
                row, "median overtime mins per day per patient"
            )),
            chair_utilization_pct=_parse_pct(_get_row(row, "chair utilization%")),
            median_chair_utilization=_parse_pct(_get_row(row, "median chair utilization")),
            ingest_id=ingest_id,
        ))
        inserted += 1
    return inserted


def _ingest_scheduler_productivity(
    session: Session, client: str, rows: List[Dict[str, str]], ingest_id: str
) -> int:
    inserted = 0
    for row in rows:
        loc = _map_location(client, _get_row(row, "location") or "")
        scheduler = (_get_row(row, "scheduler name") or "").strip()
        appt_type = (_get_row(row, "appttype") or "").strip().upper()
        if not loc or not scheduler or appt_type not in ("E", "A", "M"):
            continue
        session.add(ChrRawSchedulerProductivity(
            client_name=client,
            location_name=loc,
            scheduler_name=scheduler,
            appt_type=appt_type,
            patient_count=_parse_int_zero(_get_row(row, "patient")),
            ingest_id=ingest_id,
        ))
        inserted += 1
    return inserted


def _ingest_nurse_utilization(
    session: Session, client: str, rows: List[Dict[str, str]], ingest_id: str
) -> int:
    inserted = 0
    for row in rows:
        loc = _map_location(client, _get_row(row, "location_name") or "")
        date = _parse_date(_get_row(row, "schedule_date"))
        if not loc or date is None:
            continue
        session.add(ChrRawNurseUtilization(
            client_name=client,
            location_name=loc,
            schedule_date=date,
            fractional_minutes=_parse_float(_get_row(
                row, "iassign_new_nurse_utilization_fractional_minute"
            )),
            shift_mins=_parse_float(_get_row(row, "shift mins")),
            nurse_utilization_pct=_parse_pct(_get_row(row, "iassign_nurse_utilization")),
            median_nurse_utilization=_parse_pct(_get_row(row, "median nurse utilization")),
            ingest_id=ingest_id,
        ))
        inserted += 1
    return inserted


def _ingest_staffing_metrics(
    session: Session, client: str, rows: List[Dict[str, str]], ingest_id: str
) -> int:
    inserted = 0
    for row in rows:
        loc = _map_location(client, _get_row(row, "location_name") or "")
        date = _parse_date(_get_row(row, "schedule_date"))
        if not loc or date is None:
            continue
        session.add(ChrRawStaffingMetrics(
            client_name=client,
            location_name=loc,
            schedule_date=date,
            avg_chairs_per_rn=_parse_float(_get_row(row, "iassign_average_chairs_per_rn")),
            median_chairs_per_rn=_parse_float(_get_row(row, "median avg chair per rn")),
            avg_patients=_parse_float(_get_row(row, "average patients")),
            median_avg_patients=_parse_float(_get_row(
                row, "median avearge patient", "median average patient"
            )),
            ingest_id=ingest_id,
        ))
        inserted += 1
    return inserted


def _ingest_service_distribution(
    session: Session, client: str, rows: List[Dict[str, str]], ingest_id: str
) -> int:
    inserted = 0
    for row in rows:
        loc = _map_location(client, _get_row(row, "location_name") or "")
        date = _parse_date(_get_row(row, "date"))
        if not loc or date is None:
            continue
        session.add(ChrRawServiceDistribution(
            client_name=client,
            location_name=loc,
            schedule_date=date,
            md_count=_parse_int_zero(_get_row(row, "md count", "total md")),
            md_without_tx_inj=_parse_int_zero(_get_row(row, "md w/o tx/inj")),
            md_with_tx=_parse_int_zero(_get_row(row, "md with tx")),
            md_with_inj=_parse_int_zero(_get_row(row, "md with inj")),
            treatment_without_md=_parse_int_zero(_get_row(row, "treatment w/o md")),
            injection_without_md=_parse_int_zero(_get_row(row, "injection w/o md")),
            ingest_id=ingest_id,
        ))
        inserted += 1
    return inserted


def _ingest_service_totals(
    session: Session, client: str, rows: List[Dict[str, str]], ingest_id: str
) -> int:
    inserted = 0
    for row in rows:
        loc = _map_location(client, _get_row(row, "location") or "")
        date = _parse_date(_get_row(row, "date"))
        svc_name = (_get_row(row, "service name", "service_type_name", "type") or "").strip()
        if not loc or date is None or not svc_name:
            continue
        session.add(ChrRawServiceTotals(
            client_name=client,
            location_name=loc,
            schedule_date=date,
            day_name=(_get_row(row, "day name") or "").strip() or None,
            service_type=_infer_service_type(svc_name),
            service_name=svc_name,
            delay_mins_total=_parse_float_zero(_get_row(row, "delay (mins)")),
            service_count=_parse_int_zero(_get_row(row, "service count")),
            mins_past_closing=_parse_float_zero(_get_row(row, "mins past closing")),
            count_past_closing=_parse_int_zero(_get_row(row, "count past closing")),
            visit_duration_mins=_parse_float_zero(_get_row(row, "visit duration (mins)")),
            ingest_id=ingest_id,
        ))
        inserted += 1
    return inserted


def _ingest_time_block(
    session: Session, client: str, rows: List[Dict[str, str]], ingest_id: str
) -> int:
    inserted = 0
    for row in rows:
        loc = _map_location(client, _get_row(row, "location_name") or "")
        date = _parse_date(_get_row(row, "date"))
        svc_name = (_get_row(row, "service name", "service_type_name", "name") or "").strip()
        duration = _parse_int(_get_row(row, "duration in mins"))
        time_block = (_get_row(row, "timeblockdescription") or "").strip()
        if not loc or date is None or not svc_name or duration is None or not time_block:
            continue
        num, den = _parse_fraction(_get_row(
            row, "treatment_by_starttime_and_duration_page_fraction_by_time_block"
        ))
        session.add(ChrRawTimeBlockDistribution(
            client_name=client,
            location_name=loc,
            service_type=_infer_service_type(svc_name),
            service_name=svc_name,
            duration_mins=duration,
            schedule_date=date,
            fraction_numerator=num,
            fraction_denominator=den,
            time_block=time_block,
            ingest_id=ingest_id,
        ))
        inserted += 1
    return inserted


def _ingest_schedule_list(
    session: Session, client: str, rows: List[Dict[str, str]], ingest_id: str
) -> int:
    inserted = 0
    for row in rows:
        loc = _map_location(client, _get_row(row, "location_name") or "")
        date = _parse_date(_get_row(row, "schedule_date"))
        if not loc or date is None:
            continue
        session.add(ChrRawScheduleList(
            client_name=client,
            location_name=loc,
            schedule_date=date,
            service_type_name=(_get_row(row, "service_type_name") or "").strip() or None,
            service_name=(_get_row(row, "service  name", "service name") or "").strip() or None,
            patient_id=(_get_row(row, "patient_id") or "").strip() or None,
            mrn_number=(_get_row(row, "mrn_number") or "").strip() or None,
            scheduled_start_time=_parse_time(_get_row(row, "scheduled_start_time")),
            total_service_duration=_parse_int(_get_row(row, "totalserviceduration")),
            ingest_id=ingest_id,
        ))
        inserted += 1
    return inserted


def _ingest_visit_list(
    session: Session, client: str, rows: List[Dict[str, str]], ingest_id: str
) -> int:
    inserted = 0
    for row in rows:
        loc = _map_location(client, _get_row(row, "location_name") or "")
        date = _parse_date(_get_row(row, "date"))
        if not loc or date is None:
            continue
        session.add(ChrRawVisitList(
            client_name=client,
            location_name=loc,
            visit_date=date,
            service_type_name=(_get_row(row, "service_type_name") or "").strip() or None,
            service_name=(_get_row(row, "service name") or "").strip() or None,
            patient_id=(_get_row(row, "patient_id") or "").strip() or None,
            mrn_number=(_get_row(row, "mrn_number") or "").strip() or None,
            visit_start_time=_parse_time(_get_row(row, "visit_start_time")),
            visit_end_time=_parse_time(_get_row(row, "visit_end_time")),
            total_visit_service_duration=_parse_int(_get_row(row, "totalvisitserviceduration")),
            ingest_id=ingest_id,
        ))
        inserted += 1
    return inserted


_INGESTERS = {
    CSV_DAILY_OPERATIONS:       (ChrRawDailyOperations,        _ingest_daily_operations),
    CSV_SCHEDULER_PRODUCTIVITY: (ChrRawSchedulerProductivity,  _ingest_scheduler_productivity),
    CSV_NURSE_UTILIZATION:      (ChrRawNurseUtilization,       _ingest_nurse_utilization),
    CSV_STAFFING_METRICS:       (ChrRawStaffingMetrics,        _ingest_staffing_metrics),
    CSV_SERVICE_DISTRIBUTION:   (ChrRawServiceDistribution,    _ingest_service_distribution),
    CSV_SERVICE_TOTALS:         (ChrRawServiceTotals,          _ingest_service_totals),
    CSV_TIME_BLOCK:             (ChrRawTimeBlockDistribution,  _ingest_time_block),
    CSV_SCHEDULE_LIST:          (ChrRawScheduleList,           _ingest_schedule_list),
    CSV_VISIT_LIST:             (ChrRawVisitList,              _ingest_visit_list),
}


def ingest_csv(
    session: Session,
    client: str,
    path: Path,
    ingest_id: str,
    dry_run: bool = False,
) -> IngestResult:
    """Parse and (optionally) store one CSV file."""
    headers, rows = _read_csv(path)
    csv_type = detect_csv_type(headers)
    result = IngestResult(
        csv_path=str(path),
        csv_type=csv_type,
        rows_parsed=len(rows),
        rows_inserted=0,
        errors=[],
    )
    if csv_type is None:
        result.errors.append("unrecognised header — no ingester matched")
        return result

    model, fn = _INGESTERS[csv_type]
    try:
        if not dry_run:
            _clear_for_ingest(session, model, client, ingest_id)
            result.rows_inserted = fn(session, client, rows, ingest_id)
            session.flush()
        else:
            # Dry-run: simulate by counting parseable rows without writes
            result.rows_inserted = fn(session, client, rows, ingest_id)
            session.rollback()
    except Exception as e:
        log.exception("ingest_csv failed for %s", path)
        result.errors.append(str(e))
        session.rollback()
    return result
