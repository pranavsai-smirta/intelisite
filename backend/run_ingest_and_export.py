"""
One-shot script: ingest 6-month raw CSVs for DEMO client, then re-export all JSON files.
Run from the backend/ directory with the venv activated.
"""
import os
import sys
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

RAW_DATA_PATH = "/Users/pranavvishnuvajjhula/Downloads/6 Months raw data"
CLIENT        = "DEMO"
OUTPUT_DIR    = "../frontend/public/data"

# ── Pre-step: Wipe existing DEMO raw rows ─────────────────────────────────────
from app.db.session import get_session
from app.db.models import (
    ChrRawDailyOperations, ChrRawSchedulerProductivity, ChrRawNurseUtilization,
    ChrRawStaffingMetrics, ChrRawServiceDistribution, ChrRawServiceTotals,
    ChrRawTimeBlockDistribution, ChrRawScheduleList, ChrRawVisitList, ChrRawDataSummary,
)

_RAW_TABLES = [
    ChrRawDailyOperations, ChrRawSchedulerProductivity, ChrRawNurseUtilization,
    ChrRawStaffingMetrics, ChrRawServiceDistribution, ChrRawServiceTotals,
    ChrRawTimeBlockDistribution, ChrRawScheduleList, ChrRawVisitList, ChrRawDataSummary,
]

print(f"\n=== Pre-step: Wiping existing raw rows for {CLIENT} ===")
with get_session() as session:
    for model in _RAW_TABLES:
        deleted = session.query(model).filter_by(client_name=CLIENT).delete(
            synchronize_session=False
        )
        print(f"  {model.__tablename__}: deleted {deleted} rows")
print("Pre-step complete.")

# ── Step 1: Ingest raw CSVs ───────────────────────────────────────────────────
from app.parsers.raw_data_parser import find_csv_files, ingest_csv
from app.engine.raw_data_aggregator import compute_rollups

run_id = f"ingest_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
print(f"\n=== Step 1: Ingesting raw data for {CLIENT} (run_id={run_id}) ===")

csv_files = find_csv_files(RAW_DATA_PATH)
print(f"Found {len(csv_files)} CSV file(s)")

total_inserted = 0
with get_session() as session:
    for i, csv_path in enumerate(csv_files):
        # Per-file ingest_id prevents _clear_for_ingest from wiping sibling files
        # of the same type that share the same run (e.g. 6 schedule_list CSVs).
        file_ingest_id = f"{run_id}_{i:03d}"
        result = ingest_csv(session, CLIENT, csv_path, file_ingest_id)
        status = "OK" if not result.errors else f"ERROR: {result.errors[0]}"
        print(f"  [{result.csv_type or 'UNKNOWN':30s}] {csv_path.name:50s} "
              f"parsed={result.rows_parsed} inserted={result.rows_inserted} {status}")
        total_inserted += result.rows_inserted

    print(f"\nTotal rows inserted: {total_inserted}")
    print("\nComputing weekly + monthly rollups...")
    # all_ingests=True because rows are spread across per-file ingest_ids
    rollup_counts = compute_rollups(session, CLIENT, run_id, all_ingests=True)
    for key, count in sorted(rollup_counts.items()):
        print(f"  {key}: {count} rows")

print("\n=== Step 1 complete ===")

# ── Step 2: Re-export ALL client JSON files ───────────────────────────────────
from app.db.models import ChrKpiWide, RowType
from app.engine.json_exporter import export_json

print(f"\n=== Step 2: Exporting JSON files to {OUTPUT_DIR} ===")

with get_session() as session:
    # Use the most recent run_month present in the DB
    latest = (
        session.query(ChrKpiWide.run_month)
        .filter(ChrKpiWide.row_type == RowType.CLINIC)
        .order_by(ChrKpiWide.run_month.desc())
        .first()
    )
    run_month = latest[0] if latest else "2026-03"
    print(f"Using run_month={run_month}")

    clients = [
        r[0] for r in session.query(ChrKpiWide.client_name)
        .filter_by(run_month=run_month, row_type=RowType.CLINIC)
        .distinct().all()
    ]
    print(f"Clients to export: {clients}")

    count = export_json(session, clients, run_month, OUTPUT_DIR)

print(f"\n=== Step 2 complete: {count} JSON files written ===")

# ── Step 3: Patch DEMO.json with full god-level chatbot_context ───────────────
# Runs directly against the DB so it works even when HOGONC KPI pipeline data
# isn't present in this environment.
import json as _json
from app.engine.json_exporter import (
    _raw_data_context as _get_raw_ctx,
    KPI_DEFINITIONS, DATA_NOTES, BUSINESS_RULES, GLOSSARY, DATA_LIMITATIONS,
)
from app.engine.precise_kpi_aggregator import compute_precise_kpis

DEMO_JSON = Path(OUTPUT_DIR) / "DEMO.json"
print(f"\n=== Step 3: Patching DEMO.json with god-level chatbot_context ===")

with get_session() as session:
    raw_ctx      = _get_raw_ctx(session, CLIENT)
    print("  Computing precise KPIs from raw visit + schedule data...")
    precise_ctx  = compute_precise_kpis(session, CLIENT)
    monthly_precise = len(precise_ctx.get("per_month", []))
    weekly_precise  = len(precise_ctx.get("per_week", []))
    print(f"  Precise KPIs: {monthly_precise} monthly + {weekly_precise} weekly rows")

if DEMO_JSON.exists():
    with open(DEMO_JSON, "r", encoding="utf-8") as f:
        demo_data = _json.load(f)
    if "chatbot_context" not in demo_data:
        demo_data["chatbot_context"] = {}
    ctx = demo_data["chatbot_context"]
    ctx["kpi_definitions"]  = KPI_DEFINITIONS
    ctx["data_notes"]       = DATA_NOTES
    ctx["business_rules"]   = BUSINESS_RULES
    ctx["glossary"]         = GLOSSARY
    ctx["data_limitations"] = DATA_LIMITATIONS
    ctx["raw_data_context"] = raw_ctx
    ctx["precise_kpis"]     = precise_ctx
    DEMO_JSON.write_text(
        _json.dumps(demo_data, ensure_ascii=True, indent=2, default=str),
        encoding="utf-8",
    )
    monthly_n = len(raw_ctx.get("monthly_summaries", []))
    weekly_n  = len(raw_ctx.get("weekly_summaries", []))
    print(f"  raw_data_context: {monthly_n} monthly + {weekly_n} weekly narratives")
    print(f"  precise_kpis: {monthly_precise} monthly + {weekly_precise} weekly rows")
    print(f"  kpi_definitions, business_rules, glossary, data_limitations: injected")
    size_kb = DEMO_JSON.stat().st_size // 1024
    print(f"  DEMO.json size: {size_kb} KB")
else:
    print(f"  WARNING: {DEMO_JSON} not found -- skipping")

print("\n=== Step 3 complete ===")
print("\nDone! Chatbot is now god-level. Refresh http://localhost:5173")
