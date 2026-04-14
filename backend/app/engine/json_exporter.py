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
    KpiSource, RowType,
)
from app.engine.demo_injector import (
    inject_demo_practice, DEMO_CODE, DEMO_DISPLAY_NAME, KEEP_LOCATIONS,
)

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
    },
    "avg_delay_mins": {
        "label": "Avg Delay",
        "unit": "mins",
        "higher_is_better": False,
        "explanation": (
            "Average daily schedule delay in minutes. Lower is better. "
            "Measures how far behind the clinic is running on average."
        ),
    },
    "avg_treatments_per_day": {
        "label": "Tx Past Close/Day",
        "unit": "count",
        "higher_is_better": False,
        "explanation": (
            "Average treatments running past treatment close per day "
            "(overtime patients per day). Lower is better."
        ),
    },
    "avg_treatment_mins_per_patient": {
        "label": "Tx Mins Past Close/Patient",
        "unit": "mins",
        "higher_is_better": False,
        "explanation": (
            "Average treatment minutes past closing time per patient. "
            "Lower is better."
        ),
    },
    "avg_chair_utilization": {
        "label": "Chair Utilization",
        "unit": "%",
        "higher_is_better": True,
        "explanation": "Average chair utilization rate. Higher is better.",
    },
    "iassign_utilization": {
        "label": "iAssign Utilization",
        "unit": "%",
        "higher_is_better": True,
        "explanation": (
            "Percentage of nurse assignments completed via iAssign. "
            "Higher means more consistent, optimized assignments."
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
    },
    "avg_chairs_per_nurse": {
        "label": "Chairs/Nurse",
        "unit": "count",
        "higher_is_better": None,
        "explanation": "Average chairs assigned per nurse. Context-dependent.",
    },
    "avg_nurse_to_patient_chair_time": {
        "label": "Nurse Utilization",
        "unit": "%",
        "higher_is_better": True,
        "explanation": (
            "Average nurse-to-patient in-chair time per day. Higher is better."
        ),
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
            "kpi_definitions": KPI_DEFINITIONS,
            "data_notes": DATA_NOTES,
            "historical_kpis": _historical_kpis(session, client_name, months),
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
        demo_payload = inject_demo_practice(hogonc_payload)
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
