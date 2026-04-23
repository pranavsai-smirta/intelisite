"""
JSON Exporter -- Step 7 of the CHR pipeline.

Reads from PostgreSQL and writes one JSON file per client plus manifest.json
to the configured output directory (JSON_EXPORT_PATH env var).

The pipeline NEVER touches React source files. Only public/data/ is written.
All json.dumps calls use ensure_ascii=True -- required to prevent blank-page
bugs on GitHub Pages.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.models import (
    ChrAiInsight, ChrComparisonResult, ChrKpiWide, ChrMLAnalytics,
    ChrRawDataSummary, KpiSource, RowType,
)
from app.engine.demo_injector import (
    inject_demo_practice, DEMO_CODE, DEMO_DISPLAY_NAME, KEEP_LOCATIONS,
)
from app.engine.precise_kpi_aggregator import compute_precise_kpis

log = logging.getLogger(__name__)

NON_CLINIC_NAMES = {
    'global avg', 'global average', 'network avg', 'network average',
    'onco avg', 'onco average', 'oncosmart avg', 'oncosmart average',
    'company avg', 'company average', 'all clinics',
    'onco', 'total', 'grand total', 'overall',
}

# Names that should never appear as individual location rows in the JSON output.
# This is a superset of NON_CLINIC_NAMES that also excludes the "Company Avg"
# row — wait, no: "Company Avg" IS intentionally exported as a benchmark row.
# We only need to purge network/global aggregates that leaked in as RowType.CLINIC
# before the _resolve_row_type() fix.
_AGGREGATE_LOCATION_NAMES = {
    'global avg', 'global average',
    'network avg', 'network average',
    'all clinics', 'all clinic',
    'total', 'grand total', 'overall',
}

KPI_DEFINITIONS: Dict[str, Any] = {
    "scheduler_compliance": {
        "label": "Scheduler Compliance",
        "unit": "%",
        "higher_is_better": True,
        "explanation": (
            "Percentage of appointments scheduled following iOptimize recommendations. "
            "Higher is better. Company average is typically 60-70%. "
            "OncoSmart benchmark target is 75%."
        ),
        "formula": (
            "(count(appointment_type = 'E') + count(appointment_type = 'A')) "
            "/ count(all appointments) * 100. "
            "Per scheduler, take the LATEST entry per patient per day before counting."
        ),
        "filters": [
            "Rows where scheduled_services contains 'Treatment'.",
            "Appointment types: E = Exact (followed recommendation), "
            "A = Approximate (close to recommendation), M = Manual (ignored). "
            "E and A count as compliant.",
        ],
        "edge_cases": [
            "Scheduler compliance is only valid for data from mid-October 2024 onward; "
            "earlier data uses a pre-redefinition convention.",
            "If a patient was rescheduled, only the LATEST scheduler entry for that "
            "patient on that day counts.",
            "NULL values mean the clinic did not submit scheduler data -- "
            "absence does NOT equal poor performance.",
        ],
        "business_context": (
            "Measures whether clinicians follow the OncoSmart AI scheduling "
            "recommendation. Low SC often precedes higher delays as manual "
            "scheduling packs the schedule suboptimally."
        ),
        "data_gap": (
            "IMPORTANT: The values currently stored for this KPI were computed using "
            "the pre-2024-10 formula (legacy scheduler_id method). The correct formula "
            "requires a per-visit appointment_type (E/A/M) column that is not yet "
            "ingested. Treat stored values as directional, not authoritative."
        ),
    },
    "avg_delay_mins": {
        "label": "Avg Delay",
        "unit": "mins",
        "higher_is_better": False,
        "explanation": (
            "Average daily schedule delay in minutes. Lower is better. "
            "Measures how far behind the clinic is running on average."
        ),
        "formula": (
            "AVG(actual_service_start_time - scheduled_service_start_time) in minutes, "
            "computed across ALL Treatment visits in the period "
            "(including zero-delay and early arrivals)."
        ),
        "filters": [
            "service_type_name = 'Treatment' only. Lab, MD, MA, Injection excluded.",
        ],
        "edge_cases": [
            "Denominator is TOTAL Treatment visits, not just delayed ones. "
            "Zero-delay visits are included.",
            "Negative delays (patient arrived early) are clamped to 0 -- "
            "early arrivals do not credit the average.",
            "Rounded to whole minutes; sub-minute delays register as 0.",
        ],
        "business_context": (
            "Delay is the single most visible operational metric to patients. "
            "It is operationally linked to Scheduler Compliance: "
            "low SC tends to cause higher delays."
        ),
        "data_gap": None,
    },
    "avg_treatments_per_day": {
        "label": "Tx Past Close/Day",
        "unit": "count",
        "higher_is_better": False,
        "explanation": (
            "Average treatments running past treatment close per day "
            "(overtime patients per day). Lower is better."
        ),
        "formula": (
            "COUNT(Treatment visits where actual_end_time > preferred_treatment_end_time) "
            "/ COUNT(DISTINCT schedule_date in schedule list). "
            "Denominator = days clinic was open (from scheduled appointments), "
            "NOT from visit list."
        ),
        "filters": [
            "service_type_name = 'Treatment' only.",
            "Only rows where minutes_past_closing > 0 count in the numerator.",
        ],
        "edge_cases": [
            "Days-open denominator comes from chr_raw_schedule_list, not visit_list. "
            "Walk-in visits on non-scheduled days are excluded from the denominator.",
            "Sanity range: 2-3 patients/day past close is typical. "
            ">10/day is a flag for investigation.",
        ],
        "business_context": (
            "Directly drives staff overtime. Zero is ideal. "
            "High values indicate poor capacity management or late-day scheduling."
        ),
        "data_gap": None,
    },
    "avg_treatment_mins_per_patient": {
        "label": "Tx Mins Past Close/Patient",
        "unit": "mins",
        "higher_is_better": False,
        "explanation": (
            "Average treatment minutes past closing time per patient. "
            "Lower is better."
        ),
        "formula": (
            "SUM(minutes_past_closing) / COUNT(Treatment visits past close). "
            "Both numerator and denominator are scoped to past-close rows only "
            "(minutes_past_closing > 0)."
        ),
        "filters": [
            "service_type_name = 'Treatment' only.",
            "Only rows where minutes_past_closing > 0.",
        ],
        "edge_cases": [
            "This is NOT the same as KPI 3. KPI 3 counts patients; KPI 4 measures minutes.",
            "Denominator is count of past-close treatments, not days open.",
        ],
        "business_context": (
            "Quantifies how far past close the clinic runs on overtime days. "
            "Combined with KPI 3, it gives the total overtime burden."
        ),
        "data_gap": None,
    },
    "avg_chair_utilization": {
        "label": "Chair Utilization",
        "unit": "%",
        "higher_is_better": True,
        "explanation": "Average chair utilization rate. Higher is better.",
        "formula": (
            "SUM(total_visit_service_duration_minutes) / "
            "((operating_minutes_per_day - 60_ramp_up - 45_ramp_down) * 0.80 * num_chairs * days_open) * 100. "
            "Ramp-up = 60 min (first chair occupied), ramp-down = 45 min (last chair freed). "
            "0.80 = usable capacity factor."
        ),
        "filters": [
            "Treatment visits only (numerator from chr_raw_visit_list where service_type_name='Treatment').",
        ],
        "edge_cases": [
            ">100% = overbooking, NOT a data error. "
            "It means patients were scheduled beyond usable capacity.",
            "Numerator and denominator must share the same time window. "
            "Never divide a monthly total by a per-day denominator.",
            "num_chairs is a clinic-specific constant. "
            "Our system derives it from max-concurrent Treatment visits in 30-min windows; "
            "the team should provide the authoritative chair count to override.",
        ],
        "business_context": (
            "Measures infusion room efficiency. "
            "Target: 85-95%. Below 70% suggests underutilized capacity. "
            "Above 100% means overbooking and is a root cause of overtime."
        ),
        "data_gap": (
            "Chair count (num_chairs) is derived from data, not provided by the team. "
            "Values are directional. When the team provides exact chair counts per clinic, "
            "override via config for authoritative utilization figures."
        ),
    },
    "iassign_utilization": {
        "label": "iAssign Utilization",
        "unit": "%",
        "higher_is_better": True,
        "explanation": (
            "Percentage of nurse assignments completed via iAssign. "
            "Higher means more consistent, optimized assignments."
        ),
        "formula": (
            "COUNT(DISTINCT schedule_date where iassign_used = 1) "
            "/ COUNT(DISTINCT schedule_date) * 100. "
            "iassign_used is a per-day binary flag: 1 if the tool's recommendation "
            "was accepted that day."
        ),
        "filters": [
            "Applies clinic-wide (not treatment-specific).",
        ],
        "edge_cases": [
            "iassign_used is NOT the same as manual_entry_flag. "
            "The prior implementation used manual_entry_flag -- this was explicitly "
            "identified as wrong by Bhaskar (recording-2.txt:225-229).",
        ],
        "business_context": (
            "Measures adoption of the AI nurse-assignment tool. "
            "High utilization correlates with optimized nurse-to-patient ratios."
        ),
        "data_gap": (
            "IMPORTANT: Stored values for this KPI were computed using "
            "manual_entry_flag, which Bhaskar identified as the wrong formula. "
            "The correct source column (iassign_used per day) is not yet ingested. "
            "Treat stored values as directional, not authoritative."
        ),
    },
    "avg_patients_per_nurse": {
        "label": "Patients/Nurse/Day",
        "unit": "count",
        "higher_is_better": None,
        "explanation": (
            "Average patients per nurse per day. Context-dependent -- "
            "too high means understaffing, too low means inefficiency."
        ),
        "formula": (
            "patients_per_day / SUM(nurse_availability_fraction). "
            "nurse_availability_fraction is a per-nurse fractional value "
            "(0, 0.25, 0.5, 0.75, 1.0, 1.5+) derived from 15-minute time slots "
            "across an 8-hour shift. 0 = nurse was closed-out / unavailable."
        ),
        "filters": [
            "Denominator excludes nurses with fraction = 0.",
        ],
        "edge_cases": [
            "If a clinic does not close out nurse schedules, fractions default to 1.0 "
            "even when the nurse saw only one patient -- this inflates the denominator "
            "and makes the metric appear better than it is.",
            "Optimal range: 7-8 patients/nurse/day. Below 5 = overstaffing risk. Above 9 = understaffing.",
        ],
        "business_context": (
            "Directly sets staffing levels. Used with KPI 8 "
            "(chairs/nurse) to determine optimal nurse count for any given census."
        ),
        "data_gap": (
            "Stored values are approximate -- computed from aggregate percentages, "
            "not from per-nurse nurse_availability_fraction records. "
            "Values may differ from the team's authoritative calculation."
        ),
    },
    "avg_chairs_per_nurse": {
        "label": "Chairs/Nurse",
        "unit": "count",
        "higher_is_better": None,
        "explanation": "Average chairs assigned per nurse. Context-dependent.",
        "formula": (
            "total_chairs / SUM(nurse_availability_fraction per day). "
            "Uses the same fractional denominator as KPI 7."
        ),
        "filters": [
            "Same fractional-nurse denominator as Patients/Nurse/Day.",
        ],
        "edge_cases": [
            "Inherits all data-quality caveats from KPI 7 "
            "(closed-out nurses, inflate-to-1.0 problem).",
            "Optimal range: 3-4 chairs/RN.",
        ],
        "business_context": (
            "Staffing safety metric. Too many chairs per nurse means nurses are "
            "spread thin and response times suffer."
        ),
        "data_gap": (
            "Inherits KPI 7 data gap: aggregate percentages used instead of "
            "per-nurse fractional records."
        ),
    },
    "avg_nurse_to_patient_chair_time": {
        "label": "Nurse Utilization",
        "unit": "%",
        "higher_is_better": True,
        "explanation": (
            "Average nurse-to-patient in-chair time per day. Higher is better."
        ),
        "formula": (
            "Time nurse has >= 1 patient in chair / shift time. "
            "Per-patient factor: 0.25 (1 patient = 25%, 2 patients = 50%, etc.). "
            "Treatment START = 100% weight; Treatment STOP = 50% weight. "
            "NOTE: definition deferred -- not finalized by team."
        ),
        "filters": [
            "Treatment visits only.",
        ],
        "edge_cases": [
            "Definition was deferred in the 2026-04 meeting. "
            "Current values are computed on a provisional formula.",
        ],
        "business_context": (
            "Measures how productively nurses use their time. "
            "Minimum target: >= 50%. Below 50% = overstaffed."
        ),
        "data_gap": (
            "KPI 9 definition was NOT finalized in the team meeting. "
            "Any value shown is computed on a provisional basis. "
            "Do not make precise comparisons until the definition is confirmed with Bhaskar."
        ),
    },
}


BUSINESS_RULES: Dict[str, str] = {
    "treatment_filter": (
        "Unless the user explicitly asks about a different service type, ALL KPI "
        "computations filter to 'Treatment' rows (service_type_name = 'Treatment', "
        "equivalent to service_type_id = 6 in the team's system). "
        "Lab, MD, MA, and Injection visits are separate service types and MUST NOT "
        "be included in KPI calculations unless requested."
    ),
    "days_clinic_open": (
        "The canonical denominator 'days clinic open' = "
        "COUNT(DISTINCT schedule_date FROM chr_raw_schedule_list) "
        "for Treatment appointments. "
        "Do NOT use visit_list for the denominator -- walk-in visits on non-scheduled "
        "days would inflate the count and distort per-day KPIs."
    ),
    "time_range_normalization": (
        "Numerator and denominator MUST share the same time window. "
        "Never divide a monthly numerator by a per-day denominator or vice versa. "
        "This was the root cause of the >100% utilization bug Bhaskar flagged in "
        "recording-2.txt."
    ),
    "timestamp_1899_artifact": (
        "Excel exports time-only columns (like scheduled_start_time, visit_start_time) "
        "as '1899-12-30 HH:MM:SS'. The 1899-12-30 prefix is an Excel artifact and "
        "should be ignored -- use only the HH:MM:SS portion. "
        "The real date is in the accompanying schedule_date or visit_date column."
    ),
    "past_close_definition": (
        "'Treatment past close' means the actual service end time exceeded the clinic's "
        "preferred_treatment_end_time. In our data, this corresponds to rows where "
        "minutes_past_closing > 0."
    ),
    "walk_in_vs_scheduled": (
        "Walk-in visit = row present in visit_list but with no matching entry in "
        "schedule_list for that patient + date. Walk-ins count toward chair utilization "
        "(KPI 5) but NOT toward scheduler compliance (KPI 1). "
        "No-show = row in schedule_list with no matching entry in visit_list for that date."
    ),
    "scheduler_data_freshness": (
        "Scheduler Compliance (KPI 1) data is only valid from mid-October 2024 onward. "
        "Data before this date used a different definition and should not be compared "
        "directly to post-October 2024 values."
    ),
}


GLOSSARY: Dict[str, str] = {
    "Treatment": (
        "Chemotherapy or infusion service. The primary service class for all KPI calculations. "
        "In the team's system: service_type_id = 6, service_type_name = 'Treatment'. "
        "Distinct from: Lab (blood draw), MD (physician visit), MA (medical assistant visit), "
        "Injection."
    ),
    "Appointment Type (E/A/M)": (
        "The three values for the scheduler compliance column: "
        "E = Exact (clinician followed the scheduler's exact recommendation), "
        "A = Approximate (clinician followed the spirit but not the exact slot), "
        "M = Manual (clinician ignored the scheduler and made an independent choice). "
        "E and A count as 'compliant' for KPI 1."
    ),
    "iAssign Used": (
        "A per-day binary flag: 1 means the iAssign nurse-assignment tool's recommendation "
        "was accepted for at least part of that day. "
        "This is NOT the same as 'manual_entry_flag' -- the original implementation "
        "confused these two. Bhaskar explicitly corrected this in the 2026-04 meeting."
    ),
    "Nurse Availability Fraction": (
        "A fractional value per nurse per day representing shift coverage, derived from "
        "15-minute time slots across an 8-hour shift. "
        "Values: 0 = closed-out / unavailable, 0.25 = quarter-day, 0.5 = half-day, "
        "0.75 = three-quarters, 1.0 = full day, 1.5+ = extended coverage. "
        "0 means the nurse was scheduled but not available (shift closed out)."
    ),
    "Chair Utilization Denominator": (
        "(operating_minutes_per_day - 60 ramp-up - 45 ramp-down) * 0.80 usable_factor * num_chairs. "
        "The 60+45 = 105 minutes accounts for the time the infusion room is warming up and winding "
        "down at the start and end of the day. The 0.80 factor reflects realistic sustainable capacity. "
        "100% = the room is fully booked against realistic capacity."
    ),
    "Composite Score (0-100)": (
        "Weighted overall performance score. 50 = network average. 65+ = strong performance. "
        "<40 = needs attention. "
        "Weights: SC 25%, Avg Delay 20%, Chair Utilization 20%, iAssign 15%, "
        "Tx Past Close 10%, Nurse Utilization 10%. "
        "Includes a volatility penalty -- inconsistent clinics score lower even with the same mean."
    ),
    "Company Average": (
        "The mean across THIS client's own clinic locations for the given month. "
        "NOT a network average or industry figure. "
        "Serves as an internal benchmark."
    ),
    "Onco Benchmark": (
        "The network-wide oncology standard computed across all OncoSmart clients. "
        "The aspirational target. Higher than Company Average for most KPIs."
    ),
    "Long Duration Treatment": (
        "A treatment visit whose actual duration exceeds the 90th-percentile duration "
        "threshold for that clinic (computed over the full 6-month data window). "
        "When answering questions about 'long' treatments, always cite the threshold in minutes."
    ),
    "Duration Deviation": (
        "The difference between a visit's actual duration and its scheduled duration, "
        "expressed as a ratio. "
        ">110% = visit ran 10% longer than scheduled (over). "
        "<90% = visit ended 10% shorter than scheduled (under). "
        "Computed only for treatment visits where both scheduled and actual durations exist."
    ),
}


DATA_LIMITATIONS: Dict[str, Dict[str, str]] = {
    "kpi_1_scheduler_compliance": {
        "issue": (
            "The correct formula requires appointment_type (E/A/M) per scheduled visit. "
            "Our chr_raw_scheduler_productivity table is aggregated (one row per scheduler, "
            "not per visit) and does not have the appointment_type column."
        ),
        "effect": (
            "Values shown for Scheduler Compliance pre-date the team's October 2024 "
            "re-definition. They reflect a legacy formula based on scheduler_id, "
            "which Bhaskar explicitly called incorrect (recording-3.txt:99-103). "
            "Treat as directional only. If asked to compute a precise value, "
            "decline and cite this limitation."
        ),
        "remediation": (
            "Ask the team to export per-visit scheduler records with the "
            "appointment_type column. Once ingested, the precise aggregator "
            "can apply the (E+A)/(E+A+M) formula."
        ),
    },
    "kpi_6_iassign_utilization": {
        "issue": (
            "The correct formula is COUNT(DISTINCT schedule_date where iassign_used=1) "
            "/ days_clinic_open. Our chr_raw_nurse_utilization column was computed "
            "from manual_entry_flag, which Bhaskar explicitly said was wrong "
            "(recording-2.txt:225-229)."
        ),
        "effect": (
            "Stored iAssign utilization values may not match the team's current "
            "definition. Values are directional -- trend direction is likely correct "
            "but absolute numbers should not be cited as precise."
        ),
        "remediation": (
            "Ingest nurse_assignment_detail table with the iassign_used flag per day. "
            "The precise aggregator is ready to compute this KPI once the column is available."
        ),
    },
    "kpi_7_patients_per_nurse": {
        "issue": (
            "The correct formula requires nurse_availability_fraction (fractional shift "
            "coverage) per nurse per day. Our chr_raw_staffing_metrics table has only "
            "aggregate daily percentages, not per-nurse fractions."
        ),
        "effect": (
            "Values are approximate. Additional caveat: if a clinic does not close out "
            "nurse schedules at the end of the day, fractions default to 1.0 even when "
            "the nurse saw only one patient -- inflating the denominator and "
            "making the metric appear better than reality."
        ),
        "remediation": (
            "Request per-nurse per-day fraction records from the team with "
            "15-minute-slot granularity."
        ),
    },
    "kpi_8_chairs_per_nurse": {
        "issue": "Inherits the data gap from KPI 7 (nurse_availability_fraction).",
        "effect": "Same approximation error as KPI 7. Treat as directional.",
        "remediation": "Resolved when KPI 7 source data is ingested.",
    },
    "kpi_9_nurse_utilization": {
        "issue": (
            "The precise definition was deferred by the team in the April 2026 meeting. "
            "The POC PDF describes it as 'time nurse has >= 1 patient in chair / shift time' "
            "with a 0.25 per-patient factor, but the implementer found the definition unclear."
        ),
        "effect": (
            "Any value shown for this KPI is provisional. "
            "Do not make precise comparisons or cite this value in reports "
            "until the definition is confirmed with Bhaskar."
        ),
        "remediation": "Confirm the exact definition with Bhaskar, then rebuild.",
    },
    "scheduler_narratives_date_gap": {
        "issue": (
            "The scheduler productivity CSV the team exports has no date column. "
            "All 6 months of scheduler data collapse into a single October 2025 bucket "
            "in chr_raw_data_summary."
        ),
        "effect": (
            "When a user asks about scheduler behavior in November 2025 or later, "
            "the chatbot can only reference October 2025 scheduler narratives. "
            "Acknowledge this limitation explicitly when the user asks about a "
            "specific month other than October 2025."
        ),
        "remediation": (
            "Ask the team to export scheduler CSVs with a date column so "
            "monthly scheduler narratives can be generated per period."
        ),
    },
    "chair_count_derivation": {
        "issue": (
            "The infusion room chair count per clinic (num_chairs) is derived from data "
            "(90th-percentile of max-concurrent Treatment visits in 30-minute windows) "
            "rather than provided by the team as a hard constant."
        ),
        "effect": (
            "Chair utilization values (KPI 5) are directionally correct but may differ "
            "from the team's authoritative calculation. Always describe num_chairs as "
            "'derived from data' and suggest the team override with the actual count."
        ),
        "remediation": "Team provides exact chair counts per clinic (single config entry).",
    },
}

DATA_NOTES = (
    "Company Avg rows represent the network average across all locations for this "
    "client in the given month. Onco rows are global oncology benchmarks from the "
    "OncoSmart network. Rows named Global Avg, Network Avg, Total, or Overall are "
    "network-wide aggregates, not individual clinic locations. "
    "MoM (Month-over-Month) deltas compare the current month to the prior month. "
    "Composite scores are weighted 0 to 100 where 100 is best-in-class performance."
)


def _r(val: Optional[float], d: int = 2) -> Optional[float]:
    """Round a float or return None."""
    return round(val, d) if val is not None else None


def _clean(name: str) -> str:
    """Replace underscores with spaces and strip whitespace."""
    return name.replace("_", " ").strip()


def _get_months(session: Session, client_name: str, limit: int = 6) -> List[str]:
    """Return up to `limit` most-recent months with CLINIC data for this client."""
    rows = (
        session.query(ChrKpiWide.run_month)
        .filter(
            ChrKpiWide.client_name == client_name,
            ChrKpiWide.row_type == RowType.CLINIC,
        )
        .distinct()
        .order_by(ChrKpiWide.run_month.desc())
        .limit(limit)
        .all()
    )
    return sorted(r.run_month for r in rows)


def _ioptimize_rows(session: Session, client_name: str, month: str) -> List[Dict]:
    rows = (
        session.query(ChrKpiWide)
        .filter(
            ChrKpiWide.client_name == client_name,
            ChrKpiWide.run_month == month,
            ChrKpiWide.source == KpiSource.IOPTIMIZE,
            ChrKpiWide.row_type.in_([RowType.CLINIC, RowType.COMPANY_AVG]),
        )
        .order_by(ChrKpiWide.location_name)
        .all()
    )
    # Purge global/network aggregate rows that may have been stored with the wrong
    # RowType before the _resolve_row_type() fix (defense-in-depth guard).
    rows = [r for r in rows if r.location_name.lower().strip() not in _AGGREGATE_LOCATION_NAMES]
    return [
        {
            "location": _clean(r.location_name),
            "scheduler_compliance_avg": _r(r.scheduler_compliance),
            "scheduler_compliance_median": None,
            "avg_delay_avg": _r(r.delay_avg),
            "avg_delay_median": _r(r.delay_median),
            "chair_utilization_avg": _r(r.chair_util_avg),
            "chair_utilization_median": _r(r.chair_util_median),
            "tx_past_close_avg": _r(r.treatments_avg),
            "tx_past_close_median": _r(r.treatments_median),
            "tx_mins_past_close_avg": _r(r.tx_mins_avg),
            "tx_mins_past_close_median": _r(r.tx_mins_median),
            "mom_deltas": {},
            "vs_company": {},
            "outlier_flags": [],
        }
        for r in rows
    ]


def _iassign_rows(session: Session, client_name: str, month: str) -> List[Dict]:
    rows = (
        session.query(ChrKpiWide)
        .filter(
            ChrKpiWide.client_name == client_name,
            ChrKpiWide.run_month == month,
            ChrKpiWide.source == KpiSource.IASSIGN,
            ChrKpiWide.row_type.in_([RowType.CLINIC, RowType.COMPANY_AVG]),
        )
        .order_by(ChrKpiWide.location_name)
        .all()
    )
    # Same defense-in-depth guard as ioptimize_rows.
    rows = [r for r in rows if r.location_name.lower().strip() not in _AGGREGATE_LOCATION_NAMES]
    return [
        {
            "location": _clean(r.location_name),
            "iassign_utilization_avg": _r(r.iassign_utilization),
            "patients_per_nurse_avg": _r(r.patients_per_nurse_avg),
            "patients_per_nurse_median": _r(r.patients_per_nurse_median),
            "chairs_per_nurse_avg": _r(r.chairs_per_nurse_avg),
            "chairs_per_nurse_median": _r(r.chairs_per_nurse_median),
            "nurse_utilization_avg": _r(r.nurse_util_avg),
            "nurse_utilization_median": _r(r.nurse_util_median),
            "mom_deltas": {},
            "vs_company": {},
            "outlier_flags": [],
        }
        for r in rows
    ]


def _enrich(
    session: Session,
    client_name: str,
    month: str,
    iopt: List[Dict],
    iasg: List[Dict],
) -> None:
    """Mutate iopt and iasg rows in-place with comparison data."""
    comps = (
        session.query(ChrComparisonResult)
        .filter(
            ChrComparisonResult.client_name == client_name,
            ChrComparisonResult.run_month == month,
        )
        .all()
    )
    idx: Dict[str, Dict[str, Any]] = {}
    for c in comps:
        loc = _clean(c.location_name)
        idx.setdefault(loc, {})[c.kpi_name] = c

    for row in iopt + iasg:
        kpis = idx.get(row["location"], {})
        for kpi_name, comp in kpis.items():
            if comp.mom_delta_avg is not None:
                row["mom_deltas"][kpi_name] = _r(comp.mom_delta_avg)
            if comp.vs_company_delta is not None:
                row["vs_company"][kpi_name] = (
                    "above" if comp.vs_company_delta > 0 else "below"
                )
            if comp.is_outlier:
                row["outlier_flags"].append(kpi_name)


def _benchmarks(session: Session, client_name: str, month: str) -> Dict:
    def _extract(row) -> Dict:
        if row is None:
            return {}
        return {
            "scheduler_compliance_avg": _r(row.scheduler_compliance),
            "avg_delay_avg": _r(row.delay_avg),
            "chair_utilization_avg": _r(row.chair_util_avg),
            "tx_past_close_avg": _r(row.treatments_avg),
        }

    company = (
        session.query(ChrKpiWide)
        .filter(
            ChrKpiWide.client_name == client_name,
            ChrKpiWide.run_month == month,
            ChrKpiWide.row_type == RowType.COMPANY_AVG,
            ChrKpiWide.source == KpiSource.IOPTIMIZE,
        )
        .first()
    )
    onco = (
        session.query(ChrKpiWide)
        .filter(
            ChrKpiWide.client_name == client_name,
            ChrKpiWide.run_month == month,
            ChrKpiWide.row_type == RowType.ONCO,
            ChrKpiWide.source == KpiSource.IOPTIMIZE,
        )
        .first()
    )
    return {"company_avg": _extract(company), "onco_benchmark": _extract(onco)}


def _ai_insights(session: Session, client_name: str, month: str) -> Dict:
    rows = (
        session.query(ChrAiInsight)
        .filter(
            ChrAiInsight.client_name == client_name,
            ChrAiInsight.run_month == month,
        )
        .order_by(ChrAiInsight.priority.desc())
        .all()
    )
    result: Dict[str, Any] = {
        "executive_summary": "",
        "highlights": [],
        "concerns": [],
        "recommendations": [],
    }
    for row in rows:
        if row.insight_type == "executive_summary":
            result["executive_summary"] = row.insight_text
        elif row.insight_type == "highlight":
            result["highlights"].append(row.insight_text)
        elif row.insight_type == "concern":
            result["concerns"].append(row.insight_text)
        elif row.insight_type == "recommendation":
            result["recommendations"].append(row.insight_text)
    return result


def _composite_score(
    session: Session, client_name: str, month: str
) -> Optional[float]:
    """Average composite score across all CLINIC locations for this client/month."""
    rows = (
        session.query(
            ChrComparisonResult.location_name,
            ChrComparisonResult.composite_score,
        )
        .filter(
            ChrComparisonResult.client_name == client_name,
            ChrComparisonResult.run_month == month,
            ChrComparisonResult.composite_score.isnot(None),
        )
        .distinct(ChrComparisonResult.location_name)
        .all()
    )
    scores = [
        r.composite_score
        for r in rows
        if r.location_name.strip().lower() not in NON_CLINIC_NAMES
    ]
    return _r(sum(scores) / len(scores), 1) if scores else None


def _historical_kpis(
    session: Session, client_name: str, months: List[str]
) -> List[Dict]:
    """iOptimize KPIs across all clinic locations + all months (chatbot context)."""
    rows = (
        session.query(ChrKpiWide)
        .filter(
            ChrKpiWide.client_name == client_name,
            ChrKpiWide.run_month.in_(months),
            ChrKpiWide.source == KpiSource.IOPTIMIZE,
            ChrKpiWide.row_type == RowType.CLINIC,
        )
        .order_by(ChrKpiWide.run_month, ChrKpiWide.location_name)
        .all()
    )
    return [
        {
            "month": r.run_month,
            "location": _clean(r.location_name),
            "scheduler_compliance_avg": _r(r.scheduler_compliance),
            "avg_delay_avg": _r(r.delay_avg),
            "chair_utilization_avg": _r(r.chair_util_avg),
            "tx_past_close_avg": _r(r.treatments_avg),
        }
        for r in rows
    ]


def _ml_analytics(session: Session, client_name: str, month: str) -> Dict:
    """
    Return the ML analytics payload for one client/month.

    Structure:
      {
        "locations": {
          "<location_name>": {
            "is_anomaly_client":    bool|null,
            "anomaly_score_client": float|null,
            "is_anomaly_network":   bool|null,
            "anomaly_score_network": float|null,
            "lag_sc_to_chair_r":    float|null,
            "lag_sc_to_chair_n":    int|null,
            "forecasts": {
              "<kpi_name>": {
                "forecast": float|null,
                "lower_95": float|null,
                "upper_95": float|null,
                "n_months": int|null,
                "method":   "arima"|"moving_avg"|null,
                "converged": bool|null
              }, ...
            }
          }, ...
        }
      }
    """
    rows = (
        session.query(ChrMLAnalytics)
        .filter(
            ChrMLAnalytics.client_name == client_name,
            ChrMLAnalytics.run_month   == month,
        )
        .order_by(ChrMLAnalytics.location_name, ChrMLAnalytics.kpi_name)
        .all()
    )

    payload: Dict[str, Any] = {"locations": {}}

    for row in rows:
        loc = _clean(row.location_name)
        if loc not in payload["locations"]:
            payload["locations"][loc] = {
                "is_anomaly_client":     None,
                "anomaly_score_client":  None,
                "is_anomaly_network":    None,
                "anomaly_score_network": None,
                "lag_sc_to_chair_r":     None,
                "lag_sc_to_chair_n":     None,
                "forecasts":             {},
            }

        if row.kpi_name == "_anomaly":
            payload["locations"][loc].update({
                "is_anomaly_client":     row.is_anomaly_client,
                "anomaly_score_client":  _r(row.anomaly_score_client, 6),
                "is_anomaly_network":    row.is_anomaly_network,
                "anomaly_score_network": _r(row.anomaly_score_network, 6),
                "lag_sc_to_chair_r":     _r(row.lag_sc_to_chair_r, 4),
                "lag_sc_to_chair_n":     row.lag_sc_to_chair_n,
            })
        else:
            payload["locations"][loc]["forecasts"][row.kpi_name] = {
                "forecast": _r(row.arima_forecast, 4),
                "lower_95": _r(row.arima_lower_95, 4),
                "upper_95": _r(row.arima_upper_95, 4),
                "n_months": row.arima_n_months,
                "method":   row.arima_method,
                "converged": row.arima_converged,
            }

    return payload


def _raw_data_context(session: Session, client_name: str) -> Dict[str, List[Dict]]:
    """Package monthly + weekly narratives from chr_raw_data_summary for chatbot use."""
    rows = (
        session.query(ChrRawDataSummary)
        .filter(ChrRawDataSummary.client_name == client_name)
        .filter(ChrRawDataSummary.period_type.in_(("monthly", "weekly")))
        .order_by(
            ChrRawDataSummary.period_type,
            ChrRawDataSummary.location_name,
            ChrRawDataSummary.period_start.desc(),
            ChrRawDataSummary.category,
        )
        .all()
    )
    monthly: List[Dict] = []
    weekly: List[Dict] = []
    for r in rows:
        if not r.narrative_text:
            continue
        entry = {
            "location": _clean(r.location_name),
            "period": r.period_start.strftime("%Y-%m-%d") if r.period_start else "",
            "category": r.category,
            "summary": r.narrative_text,
        }
        if r.period_type == "monthly":
            entry["period"] = r.period_start.strftime("%Y-%m") if r.period_start else ""
            monthly.append(entry)
        else:
            weekly.append(entry)
    return {"monthly_summaries": monthly, "weekly_summaries": weekly}


def build_client_json(
    session: Session, client_name: str, run_month: str
) -> Dict:
    """Assemble the complete JSON payload for one client."""
    months = _get_months(session, client_name, limit=6)
    months_data: Dict[str, Any] = {}

    for month in months:
        iopt = _ioptimize_rows(session, client_name, month)
        iasg = _iassign_rows(session, client_name, month)
        _enrich(session, client_name, month, iopt, iasg)
        months_data[month] = {
            "composite_score": _composite_score(session, client_name, month),
            "ioptimize":       iopt,
            "iassign":         iasg,
            "benchmarks":      _benchmarks(session, client_name, month),
            "ai_insights":     _ai_insights(session, client_name, month),
            "ml_analytics":    _ml_analytics(session, client_name, month),
        }

    return {
        "meta": {
            "client_code": client_name,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "months_available": months,
        },
        "months": months_data,
        "chatbot_context": {
            "kpi_definitions":  KPI_DEFINITIONS,
            "data_notes":       DATA_NOTES,
            "business_rules":   BUSINESS_RULES,
            "glossary":         GLOSSARY,
            "data_limitations": DATA_LIMITATIONS,
            "historical_kpis":  _historical_kpis(session, client_name, months),
            "raw_data_context": _raw_data_context(session, client_name),
            "precise_kpis":     compute_precise_kpis(session, client_name),
        },
    }


def build_manifest(
    session: Session, clients: List[str], run_month: str
) -> Dict:
    """Assemble manifest.json summarising all clients."""
    entries = []
    all_scores: List[float] = []

    for client in clients:
        months = _get_months(session, client, limit=2)
        if not months:
            continue
        latest = months[-1]

        loc_count = (
            session.query(ChrKpiWide.location_name)
            .filter(
                ChrKpiWide.client_name == client,
                ChrKpiWide.run_month == latest,
                ChrKpiWide.source == KpiSource.IOPTIMIZE,
                ChrKpiWide.row_type == RowType.CLINIC,
            )
            .distinct()
            .count()
        )

        score = _composite_score(session, client, latest)
        if score is not None:
            all_scores.append(score)

        mom_trend = "flat"
        if len(months) >= 2:
            prior = _composite_score(session, client, months[-2])
            if score is not None and prior is not None:
                if score > prior + 1:
                    mom_trend = "up"
                elif score < prior - 1:
                    mom_trend = "down"

        entries.append({
            "code": client,
            "display_name": client,
            "latest_month": latest,
            "location_count": loc_count,
            "composite_score": score,
            "mom_trend": mom_trend,
        })

    entries.sort(key=lambda x: x["composite_score"] or 0, reverse=True)
    avg = _r(sum(all_scores) / len(all_scores), 1) if all_scores else None
    top = entries[0]["code"] if entries else None
    improving = [e for e in entries if e["mom_trend"] == "up"]

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "latest_month": run_month,
        "clients": entries,
        "network_summary": {
            "avg_composite_score": avg,
            "top_performer": top,
            "most_improved": improving[0]["code"] if improving else None,
        },
    }


def _inject_demo_manifest_entry(
    manifest: Dict, demo_payload: Dict, hogonc_entry: Dict
) -> None:
    """Append the DEMO entry to manifest['clients'] in-place and re-sort."""
    months = demo_payload.get("meta", {}).get("months_available", [])
    latest = months[-1] if months else hogonc_entry.get("latest_month", "")
    demo_entry = {
        "code": DEMO_CODE,
        "display_name": DEMO_DISPLAY_NAME,
        "latest_month": latest,
        "location_count": KEEP_LOCATIONS,
        "composite_score": hogonc_entry["composite_score"],
        "mom_trend": hogonc_entry["mom_trend"],
    }
    manifest["clients"].append(demo_entry)
    manifest["clients"].sort(key=lambda x: x["composite_score"] or 0, reverse=True)


def export_json(
    session: Session,
    clients: List[str],
    run_month: str,
    output_dir: str,
) -> int:
    """Write {CLIENT}.json + manifest.json. Returns count of files written."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = 0
    hogonc_payload: Optional[Dict] = None

    for client in clients:
        payload = build_client_json(session, client, run_month)
        if client == "HOGONC":
            hogonc_payload = payload
        dest = out / f"{client}.json"
        dest.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2, default=str),
            encoding="utf-8",
        )
        log.info("  Wrote %s (%dKB)", dest.name, dest.stat().st_size // 1024)
        written += 1

    # --- Demo Practice injection (in-memory only, no DB writes) ---
    demo_payload: Optional[Dict] = None
    if hogonc_payload is not None:
        demo_payload = inject_demo_practice(hogonc_payload, session=session)
        demo_dest = out / f"{DEMO_CODE}.json"
        demo_dest.write_text(
            json.dumps(demo_payload, ensure_ascii=True, indent=2, default=str),
            encoding="utf-8",
        )
        log.info("  Wrote %s (%dKB)", demo_dest.name, demo_dest.stat().st_size // 1024)
        written += 1

    manifest = build_manifest(session, clients, run_month)

    # Inject DEMO into manifest if we produced a demo payload
    if demo_payload is not None:
        hogonc_entry = next(
            (e for e in manifest.get("clients", []) if e["code"] == "HOGONC"), None
        )
        if hogonc_entry is not None:
            _inject_demo_manifest_entry(manifest, demo_payload, hogonc_entry)

    manifest_dest = out / "manifest.json"
    manifest_dest.write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2, default=str),
        encoding="utf-8",
    )
    log.info("  Wrote manifest.json")
    return written + 1
