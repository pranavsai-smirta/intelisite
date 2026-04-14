# React Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate 14 static HTML oncology dashboards to a production-grade React SPA on GitHub Pages, with a new pipeline JSON export step and an embedded AI chatbot.

**Architecture:** Vite + React + HashRouter deployed to GitHub Pages via GitHub Actions. The Python pipeline adds one new step (`json_exporter.py`) that writes structured JSON files to `ncs-chr-webpage/public/data/`. The React app reads those JSON files at runtime. These two deliverables are fully independent — Phase 1 (pipeline) and Phases 2–7 (React) can be built in parallel using sample fixture JSON for development.

**Tech Stack:** Python/SQLAlchemy (pipeline), Vite, React 18, react-router-dom v6, Tailwind CSS v3, Recharts, Fontsource Inter, Anthropic API (direct browser fetch)

---

## File Map

### CHR-AUTOMATION-V2 (pipeline repo)

| Action | Path | Purpose |
|--------|------|---------|
| Create | `app/engine/json_exporter.py` | All DB reads + JSON assembly logic |
| Modify | `app/core/orchestrator.py` | Add Step 7 call + stats entry |
| Modify | `.env.example` | Add `JSON_EXPORT_PATH` variable |
| Create | `tests/test_json_exporter.py` | Unit tests with mocked DB session |

### ncs-chr-webpage (dashboard repo — new React app)

| Action | Path | Purpose |
|--------|------|---------|
| Create | `package.json` | Dependencies |
| Create | `vite.config.js` | Vite config with `base: '/ncs-chr-webpage/'` |
| Create | `tailwind.config.js` | Tailwind content paths + Inter font |
| Create | `postcss.config.js` | Tailwind + autoprefixer |
| Create | `index.html` | HTML entry point |
| Create | `src/index.css` | Tailwind directives |
| Create | `src/main.jsx` | React root mount + Fontsource imports |
| Create | `src/App.jsx` | HashRouter + route definitions |
| Create | `src/hooks/useManifest.js` | Fetch + cache manifest.json |
| Create | `src/hooks/useClinicData.js` | Fetch + cache {CLIENT}.json with in-memory cache |
| Create | `src/components/NavBar.jsx` | Top nav with route-aware label |
| Create | `src/components/ScoreBadge.jsx` | Color-coded 0–100 composite score |
| Create | `src/components/KpiCard.jsx` | Hero dark-glass metric card |
| Create | `src/components/KpiTable.jsx` | iOptimize / iAssign data table with color coding |
| Create | `src/components/TrendChart.jsx` | 6-month Recharts AreaChart |
| Create | `src/components/InsightPanel.jsx` | AI prose display with collapsible sections |
| Create | `src/pages/CTOMasterView.jsx` | Network overview — 14 clinic cards |
| Create | `src/pages/ClinicView.jsx` | Single clinic — tables, charts, insights |
| Create | `src/lib/anthropic.js` | Streaming Anthropic API call + system prompt builder |
| Create | `src/components/ChatBot.jsx` | Floating drawer chatbot |
| Create | `.github/workflows/deploy.yml` | Build + deploy to gh-pages on push to main |
| Create | `public/data/manifest.json` | Dev fixture |
| Create | `public/data/HOGONC.json` | Dev fixture |
| Create | `.env.local` | `VITE_ANTHROPIC_API_KEY=...` (never committed) |
| Modify | `.gitignore` | Exclude `.env.local`, `dist/`, `node_modules/` |

---

## Phase 1 — Pipeline JSON Exporter

### Task 1: Create `app/engine/json_exporter.py`

**Files:**
- Create: `app/engine/json_exporter.py`

- [ ] **Step 1: Create the file**

```python
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
    ChrAiInsight, ChrComparisonResult, ChrKpiWide, KpiSource, RowType,
)

log = logging.getLogger(__name__)

NON_CLINIC_NAMES = {
    'global avg', 'global average', 'network avg', 'network average',
    'onco avg', 'onco average', 'oncosmart avg', 'oncosmart average',
    'company avg', 'company average', 'all clinics',
    'onco', 'total', 'grand total', 'overall',
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
        "explanation": (
            "Average chair utilization rate. Higher is better."
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
        "explanation": (
            "Average chairs assigned per nurse. Context-dependent."
        ),
    },
    "avg_nurse_to_patient_chair_time": {
        "label": "Nurse Utilization",
        "unit": "%",
        "higher_is_better": True,
        "explanation": (
            "Average nurse-to-patient in-chair time per day. "
            "Higher is better."
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
            ChrKpiWide.row_type == RowType.CLINIC,
        )
        .order_by(ChrKpiWide.location_name)
        .all()
    )
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
            ChrKpiWide.row_type == RowType.CLINIC,
        )
        .order_by(ChrKpiWide.location_name)
        .all()
    )
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
    # Build index: cleaned location -> kpi_name -> comparison row
    idx: Dict[str, Dict[str, ChrComparisonResult]] = {}
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


def _composite_score(session: Session, client_name: str, month: str) -> Optional[float]:
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
            "ioptimize": iopt,
            "iassign": iasg,
            "benchmarks": _benchmarks(session, client_name, month),
            "ai_insights": _ai_insights(session, client_name, month),
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

    for client in clients:
        payload = build_client_json(session, client, run_month)
        dest = out / f"{client}.json"
        dest.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2, default=str),
            encoding="utf-8",
        )
        log.info("  Wrote %s (%dKB)", dest.name, dest.stat().st_size // 1024)
        written += 1

    manifest = build_manifest(session, clients, run_month)
    manifest_dest = out / "manifest.json"
    manifest_dest.write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2, default=str),
        encoding="utf-8",
    )
    log.info("  Wrote manifest.json")
    return written + 1
```

- [ ] **Step 2: Verify the file is importable**

```bash
cd /Users/pranavvishnuvajjhula/CHR-AUTOMATION-V2
python -c "from app.engine.json_exporter import build_client_json, build_manifest, export_json; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/engine/json_exporter.py
git commit -m "feat: add json_exporter step 7 — writes client JSON + manifest"
```

---

### Task 2: Write unit tests for `json_exporter.py`

**Files:**
- Create: `tests/test_json_exporter.py`

- [ ] **Step 1: Write the tests**

```python
"""Unit tests for app/engine/json_exporter.py"""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call
from app.engine.json_exporter import (
    _r, _clean, _get_months, _ioptimize_rows, _iassign_rows,
    _composite_score, build_client_json, build_manifest, export_json,
)
from app.db.models import RowType, KpiSource


# ── helpers ──────────────────────────────────────────────────────

def _wide_row(**kw):
    r = MagicMock()
    r.run_month = kw.get("run_month", "2026-01")
    r.client_name = kw.get("client_name", "HOGONC")
    r.location_name = kw.get("location_name", "BCC MO")
    r.row_type = kw.get("row_type", RowType.CLINIC)
    r.source = kw.get("source", KpiSource.IOPTIMIZE)
    r.scheduler_compliance = kw.get("scheduler_compliance", 70.0)
    r.delay_avg = kw.get("delay_avg", 8.5)
    r.delay_median = kw.get("delay_median", 7.0)
    r.treatments_avg = kw.get("treatments_avg", 3.0)
    r.treatments_median = kw.get("treatments_median", 2.5)
    r.tx_mins_avg = kw.get("tx_mins_avg", 15.0)
    r.tx_mins_median = kw.get("tx_mins_median", 12.0)
    r.chair_util_avg = kw.get("chair_util_avg", 85.0)
    r.chair_util_median = kw.get("chair_util_median", 87.0)
    r.iassign_utilization = kw.get("iassign_utilization", 90.0)
    r.patients_per_nurse_avg = kw.get("patients_per_nurse_avg", 4.0)
    r.patients_per_nurse_median = kw.get("patients_per_nurse_median", 4.0)
    r.chairs_per_nurse_avg = kw.get("chairs_per_nurse_avg", 3.0)
    r.chairs_per_nurse_median = kw.get("chairs_per_nurse_median", 3.0)
    r.nurse_util_avg = kw.get("nurse_util_avg", 75.0)
    r.nurse_util_median = kw.get("nurse_util_median", 76.0)
    return r


def _make_session(all_return=None, first_return=None, distinct_count=2):
    """Return a mock session where .query().filter()...all() returns all_return."""
    session = MagicMock()
    q = session.query.return_value
    q.filter.return_value = q
    q.filter_by.return_value = q
    q.distinct.return_value = q
    q.order_by.return_value = q
    q.limit.return_value = q
    q.all.return_value = all_return or []
    q.first.return_value = first_return
    q.count.return_value = distinct_count
    return session


# ── _r ───────────────────────────────────────────────────────────

def test_r_rounds():
    assert _r(9.8123, 2) == 9.81


def test_r_none():
    assert _r(None) is None


def test_r_zero():
    assert _r(0.0) == 0.0


# ── _clean ───────────────────────────────────────────────────────

def test_clean_replaces_underscores():
    assert _clean("BCC_MO") == "BCC MO"


def test_clean_strips_whitespace():
    assert _clean("  BCC MO  ") == "BCC MO"


# ── _ioptimize_rows ──────────────────────────────────────────────

def test_ioptimize_rows_maps_columns():
    row = _wide_row()
    session = _make_session(all_return=[row])

    result = _ioptimize_rows(session, "HOGONC", "2026-01")

    assert len(result) == 1
    r = result[0]
    assert r["location"] == "BCC MO"
    assert r["scheduler_compliance_avg"] == 70.0
    assert r["avg_delay_avg"] == 8.5
    assert r["avg_delay_median"] == 7.0
    assert r["chair_utilization_avg"] == 85.0
    assert r["tx_past_close_avg"] == 3.0
    assert r["tx_mins_past_close_avg"] == 15.0
    assert r["mom_deltas"] == {}
    assert r["vs_company"] == {}
    assert r["outlier_flags"] == []


def test_ioptimize_rows_replaces_underscores_in_location():
    row = _wide_row(location_name="BCC_MO_CLINIC")
    session = _make_session(all_return=[row])

    result = _ioptimize_rows(session, "HOGONC", "2026-01")

    assert result[0]["location"] == "BCC MO CLINIC"


def test_ioptimize_rows_handles_none_values():
    row = _wide_row(scheduler_compliance=None, delay_avg=None)
    session = _make_session(all_return=[row])

    result = _ioptimize_rows(session, "HOGONC", "2026-01")

    assert result[0]["scheduler_compliance_avg"] is None
    assert result[0]["avg_delay_avg"] is None


# ── _iassign_rows ────────────────────────────────────────────────

def test_iassign_rows_maps_columns():
    row = _wide_row(source=KpiSource.IASSIGN)
    session = _make_session(all_return=[row])

    result = _iassign_rows(session, "HOGONC", "2026-01")

    assert len(result) == 1
    r = result[0]
    assert r["iassign_utilization_avg"] == 90.0
    assert r["patients_per_nurse_avg"] == 4.0
    assert r["chairs_per_nurse_avg"] == 3.0
    assert r["nurse_utilization_avg"] == 75.0


# ── _composite_score ─────────────────────────────────────────────

def test_composite_score_averages_locations():
    row1 = MagicMock()
    row1.location_name = "BCC MO"
    row1.composite_score = 80.0
    row2 = MagicMock()
    row2.location_name = "MTHMO"
    row2.composite_score = 60.0
    session = _make_session(all_return=[row1, row2])

    result = _composite_score(session, "HOGONC", "2026-01")

    assert result == 70.0


def test_composite_score_excludes_non_clinic_rows():
    row1 = MagicMock()
    row1.location_name = "Company Avg"
    row1.composite_score = 50.0
    row2 = MagicMock()
    row2.location_name = "BCC MO"
    row2.composite_score = 80.0
    session = _make_session(all_return=[row1, row2])

    result = _composite_score(session, "HOGONC", "2026-01")

    assert result == 80.0


def test_composite_score_returns_none_when_no_data():
    session = _make_session(all_return=[])
    result = _composite_score(session, "HOGONC", "2026-01")
    assert result is None


# ── build_client_json ────────────────────────────────────────────

def test_build_client_json_structure():
    session = _make_session(all_return=[])

    # Patch internal helpers to return predictable values
    with patch("app.engine.json_exporter._get_months", return_value=["2026-01"]), \
         patch("app.engine.json_exporter._ioptimize_rows", return_value=[]), \
         patch("app.engine.json_exporter._iassign_rows", return_value=[]), \
         patch("app.engine.json_exporter._enrich"), \
         patch("app.engine.json_exporter._composite_score", return_value=72.5), \
         patch("app.engine.json_exporter._benchmarks", return_value={}), \
         patch("app.engine.json_exporter._ai_insights", return_value={}), \
         patch("app.engine.json_exporter._historical_kpis", return_value=[]):

        result = build_client_json(session, "HOGONC", "2026-01")

    assert result["meta"]["client_code"] == "HOGONC"
    assert "months_available" in result["meta"]
    assert "2026-01" in result["months"]
    assert result["months"]["2026-01"]["composite_score"] == 72.5
    assert "chatbot_context" in result
    assert "kpi_definitions" in result["chatbot_context"]


def test_build_client_json_serialisable():
    session = _make_session(all_return=[])

    with patch("app.engine.json_exporter._get_months", return_value=["2026-01"]), \
         patch("app.engine.json_exporter._ioptimize_rows", return_value=[]), \
         patch("app.engine.json_exporter._iassign_rows", return_value=[]), \
         patch("app.engine.json_exporter._enrich"), \
         patch("app.engine.json_exporter._composite_score", return_value=None), \
         patch("app.engine.json_exporter._benchmarks", return_value={}), \
         patch("app.engine.json_exporter._ai_insights", return_value={}), \
         patch("app.engine.json_exporter._historical_kpis", return_value=[]):

        result = build_client_json(session, "HOGONC", "2026-01")

    # Must not raise
    serialised = json.dumps(result, ensure_ascii=True)
    assert "HOGONC" in serialised
    # ensure_ascii=True means no raw non-ASCII bytes
    assert all(ord(c) < 128 for c in serialised)


# ── export_json ──────────────────────────────────────────────────

def test_export_json_writes_files(tmp_path):
    session = MagicMock()
    clients = ["HOGONC", "PCI"]

    with patch("app.engine.json_exporter.build_client_json", return_value={"meta": {}}), \
         patch("app.engine.json_exporter.build_manifest", return_value={"clients": []}):

        count = export_json(session, clients, "2026-01", str(tmp_path))

    assert count == 3  # 2 client files + manifest
    assert (tmp_path / "HOGONC.json").exists()
    assert (tmp_path / "PCI.json").exists()
    assert (tmp_path / "manifest.json").exists()


def test_export_json_uses_ensure_ascii(tmp_path):
    session = MagicMock()
    payload = {"text": "em\u2014dash"}  # contains non-ASCII (em dash U+2014)

    with patch("app.engine.json_exporter.build_client_json", return_value=payload), \
         patch("app.engine.json_exporter.build_manifest", return_value={}):

        export_json(session, ["HOGONC"], "2026-01", str(tmp_path))

    content = (tmp_path / "HOGONC.json").read_text(encoding="utf-8")
    # ensure_ascii=True should escape the em dash as \u2014
    assert "\\u2014" in content
    assert "\u2014" not in content  # raw em dash must not appear
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
cd /Users/pranavvishnuvajjhula/CHR-AUTOMATION-V2
pytest tests/test_json_exporter.py -v
```

Expected: all tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_json_exporter.py
git commit -m "test: add unit tests for json_exporter"
```

---

### Task 3: Wire Step 7 into orchestrator + update `.env.example`

**Files:**
- Modify: `app/core/orchestrator.py`
- Modify: `.env.example`

- [ ] **Step 1: Update `orchestrator.py`**

In `__init__`, add `'json_exports': 0` to `self.stats`:
```python
self.stats = {
    'issues_fetched': 0,
    'kpis_parsed': 0,
    'kpis_warnings': 0,
    'comparisons': 0,
    'correlations': 0,
    'insights': 0,
    'emails': 0,
    'json_exports': 0,   # ADD THIS LINE
}
```

In `run()`, add Step 7 after Step 6:
```python
self._step(7, "Export JSON for dashboard",  self._export_json)
```

In `_step()`, change `"Step {num}/6"` to `"Step {num}/7"`:
```python
console.print(f"\n[bold cyan]Step {num}/7:[/bold cyan] {label}")
```

Add the `_export_json` method after `_generate_emails`:
```python
# ── Step 7 ────────────────────────────────────────────────────────
def _export_json(self):
    from app.db.session import get_session
    from app.db.models import ChrKpiWide, RowType
    from app.engine.json_exporter import export_json

    output_dir = os.getenv("JSON_EXPORT_PATH", "../ncs-chr-webpage/public/data")
    if not os.path.isdir(os.path.dirname(str(output_dir).rstrip("/"))):
        console.print(
            f"  [yellow]⚠  JSON_EXPORT_PATH not found: {output_dir} — skipping[/yellow]"
        )
        return

    with get_session() as session:
        clients = [
            r[0] for r in session.query(ChrKpiWide.client_name)
            .filter_by(run_month=self.run_month, row_type=RowType.CLINIC)
            .distinct()
            .all()
        ]
        count = export_json(session, clients, self.run_month, output_dir)

    self.stats['json_exports'] = count
    console.print(f"  [green]✓ {count} JSON files written to {output_dir}[/green]")
```

Add summary row in `_print_summary` after "Emails generated":
```python
t.add_row("JSON exports", str(self.stats['json_exports']))
```

- [ ] **Step 2: Add `JSON_EXPORT_PATH` to `.env.example`**

Open `.env.example` and append:
```
# Path where pipeline writes JSON files for the React dashboard
# Set to the absolute path of ncs-chr-webpage/public/data/
JSON_EXPORT_PATH=../ncs-chr-webpage/public/data
```

- [ ] **Step 3: Verify orchestrator imports cleanly**

```bash
cd /Users/pranavvishnuvajjhula/CHR-AUTOMATION-V2
python -c "from app.core.orchestrator import PipelineOrchestrator; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/core/orchestrator.py .env.example
git commit -m "feat: wire json_exporter as Step 7 in pipeline orchestrator"
```

---

## Phase 2 — React App Scaffold + Data Hooks

> All remaining tasks are in the **`ncs-chr-webpage`** repo. Clone it or `cd` into it before starting.

### Task 4: Initialise project with Vite, Tailwind, dependencies

**Files:**
- Create: `package.json`, `vite.config.js`, `tailwind.config.js`, `postcss.config.js`, `index.html`, `.gitignore`

- [ ] **Step 1: Scaffold Vite React project**

```bash
cd /path/to/ncs-chr-webpage
npm create vite@latest . -- --template react
# When prompted "Current directory is not empty", choose "Ignore files and continue"
```

- [ ] **Step 2: Install all dependencies**

```bash
npm install react-router-dom recharts @fontsource/inter
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
```

- [ ] **Step 3: Replace `vite.config.js`**

```js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/ncs-chr-webpage/',
})
```

- [ ] **Step 4: Replace `tailwind.config.js`**

```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui'],
      },
    },
  },
  plugins: [],
}
```

- [ ] **Step 5: Replace `index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>OncoSmart Analytics</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
```

- [ ] **Step 6: Create `.gitignore`**

```
node_modules/
dist/
.env.local
.env*.local
```

- [ ] **Step 7: Verify dev server starts**

```bash
npm run dev
```

Expected: Vite server starts at `http://localhost:5173/ncs-chr-webpage/`

- [ ] **Step 8: Commit**

```bash
git add package.json package-lock.json vite.config.js tailwind.config.js postcss.config.js index.html .gitignore
git commit -m "chore: scaffold Vite React app with Tailwind + Recharts"
```

---

### Task 5: Entry files — `src/index.css`, `src/main.jsx`, `src/App.jsx`

**Files:**
- Create: `src/index.css`, `src/main.jsx`, `src/App.jsx`

- [ ] **Step 1: Create `src/index.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 2: Create `src/main.jsx`**

```jsx
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/inter/700.css'
import './index.css'
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
```

- [ ] **Step 3: Create `src/App.jsx`**

```jsx
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom'
import NavBar from './components/NavBar'
import CTOMasterView from './pages/CTOMasterView'
import ClinicView from './pages/ClinicView'

export default function App() {
  return (
    <HashRouter>
      <div className="min-h-screen bg-slate-50 font-sans">
        <NavBar />
        <main>
          <Routes>
            <Route path="/" element={<CTOMasterView />} />
            <Route path="/clinic/:clientCode" element={<ClinicView />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </HashRouter>
  )
}
```

- [ ] **Step 4: Create placeholder page files so the app compiles**

Create `src/pages/CTOMasterView.jsx`:
```jsx
export default function CTOMasterView() {
  return <div className="p-8 text-slate-700">CTO Master View — coming soon</div>
}
```

Create `src/pages/ClinicView.jsx`:
```jsx
export default function ClinicView() {
  return <div className="p-8 text-slate-700">Clinic View — coming soon</div>
}
```

Create `src/components/NavBar.jsx`:
```jsx
export default function NavBar() {
  return <nav className="bg-[#0F172A] px-6 py-4"><span className="text-white font-semibold">OncoSmart Analytics</span></nav>
}
```

- [ ] **Step 5: Verify app renders in browser**

```bash
npm run dev
```

Open `http://localhost:5173/ncs-chr-webpage/`. Expected: dark nav bar, "CTO Master View — coming soon" text.

- [ ] **Step 6: Commit**

```bash
git add src/
git commit -m "chore: add entry files — main, App, placeholder pages"
```

---

### Task 6: Sample fixture JSON files for development

**Files:**
- Create: `public/data/manifest.json`
- Create: `public/data/HOGONC.json`

- [ ] **Step 1: Create `public/data/manifest.json`**

```json
{
  "generated_at": "2026-03-01T00:00:00Z",
  "latest_month": "2026-02",
  "clients": [
    { "code": "HOGONC", "display_name": "HOGONC", "latest_month": "2026-02", "location_count": 4, "composite_score": 74, "mom_trend": "up" },
    { "code": "PCI",    "display_name": "PCI",    "latest_month": "2026-02", "location_count": 3, "composite_score": 68, "mom_trend": "flat" },
    { "code": "NCS",    "display_name": "NCS",    "latest_month": "2026-02", "location_count": 5, "composite_score": 81, "mom_trend": "up" },
    { "code": "TNO",    "display_name": "TNO",    "latest_month": "2026-02", "location_count": 2, "composite_score": 55, "mom_trend": "down" },
    { "code": "CCBD",   "display_name": "CCBD",   "latest_month": "2026-02", "location_count": 3, "composite_score": 72, "mom_trend": "up" },
    { "code": "CCI",    "display_name": "CCI",    "latest_month": "2026-02", "location_count": 6, "composite_score": 65, "mom_trend": "flat" },
    { "code": "CHC",    "display_name": "CHC",    "latest_month": "2026-02", "location_count": 2, "composite_score": 60, "mom_trend": "flat" },
    { "code": "LOA",    "display_name": "LOA",    "latest_month": "2026-02", "location_count": 2, "composite_score": 70, "mom_trend": "down" },
    { "code": "MOASD",  "display_name": "MOASD",  "latest_month": "2026-02", "location_count": 3, "composite_score": 76, "mom_trend": "up" },
    { "code": "NMCC",   "display_name": "NMCC",   "latest_month": "2026-02", "location_count": 2, "composite_score": 63, "mom_trend": "flat" },
    { "code": "NWMS",   "display_name": "NWMS",   "latest_month": "2026-02", "location_count": 4, "composite_score": 78, "mom_trend": "up" },
    { "code": "NYOH",   "display_name": "NYOH",   "latest_month": "2026-02", "location_count": 7, "composite_score": 69, "mom_trend": "flat" },
    { "code": "PCC",    "display_name": "PCC",    "latest_month": "2026-02", "location_count": 3, "composite_score": 73, "mom_trend": "up" },
    { "code": "AON",    "display_name": "AON",    "latest_month": "2026-02", "location_count": 2, "composite_score": 58, "mom_trend": "down" }
  ],
  "network_summary": {
    "avg_composite_score": 69.4,
    "top_performer": "NCS",
    "most_improved": "HOGONC"
  }
}
```

- [ ] **Step 2: Create `public/data/HOGONC.json`**

```json
{
  "meta": {
    "client_code": "HOGONC",
    "generated_at": "2026-03-01T00:00:00Z",
    "months_available": ["2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-02"]
  },
  "months": {
    "2026-02": {
      "composite_score": 74,
      "ioptimize": [
        {
          "location": "BCC MO",
          "scheduler_compliance_avg": 46.99,
          "scheduler_compliance_median": null,
          "avg_delay_avg": 9.81,
          "avg_delay_median": 8.64,
          "chair_utilization_avg": 82.1,
          "chair_utilization_median": 84.0,
          "tx_past_close_avg": 3.2,
          "tx_past_close_median": 3.0,
          "tx_mins_past_close_avg": 14.5,
          "tx_mins_past_close_median": 12.0,
          "mom_deltas": { "scheduler_compliance": 2.1, "avg_delay_mins": -0.4 },
          "vs_company": { "scheduler_compliance": "below", "avg_delay_mins": "above" },
          "outlier_flags": []
        },
        {
          "location": "BCC KY",
          "scheduler_compliance_avg": 71.5,
          "scheduler_compliance_median": null,
          "avg_delay_avg": 6.2,
          "avg_delay_median": 5.8,
          "chair_utilization_avg": 88.0,
          "chair_utilization_median": 90.0,
          "tx_past_close_avg": 2.1,
          "tx_past_close_median": 2.0,
          "tx_mins_past_close_avg": 10.2,
          "tx_mins_past_close_median": 9.5,
          "mom_deltas": { "scheduler_compliance": 1.5 },
          "vs_company": { "scheduler_compliance": "above" },
          "outlier_flags": []
        }
      ],
      "iassign": [
        {
          "location": "BCC MO",
          "iassign_utilization_avg": 88.5,
          "patients_per_nurse_avg": 4.2,
          "patients_per_nurse_median": 4.0,
          "chairs_per_nurse_avg": 3.1,
          "chairs_per_nurse_median": 3.0,
          "nurse_utilization_avg": 71.0,
          "nurse_utilization_median": 70.0,
          "mom_deltas": {},
          "vs_company": {},
          "outlier_flags": []
        }
      ],
      "benchmarks": {
        "company_avg": { "scheduler_compliance_avg": 61.2, "avg_delay_avg": 7.8, "chair_utilization_avg": 79.0, "tx_past_close_avg": 3.5 },
        "onco_benchmark": { "scheduler_compliance_avg": 75.0, "avg_delay_avg": 6.0, "chair_utilization_avg": 85.0, "tx_past_close_avg": 2.0 }
      },
      "ai_insights": {
        "executive_summary": "HOGONC showed mixed performance in February 2026. BCC KY continues to lead with 71.5% scheduler compliance, while BCC MO remains below the 61.2% company average at 46.99%. Chair utilization is strong network-wide, with both locations above 80%.",
        "highlights": [
          "BCC KY scheduler compliance improved 1.5 points to 71.5%, approaching the 75% OncoSmart benchmark.",
          "Average delay at BCC MO improved 0.4 minutes MoM to 9.81 min, though still above the 7.8 min company average."
        ],
        "concerns": [
          "BCC MO scheduler compliance at 46.99% is 14.2 points below the 61.2% company average and warrants attention."
        ],
        "recommendations": [
          "Focus iOptimize adoption coaching at BCC MO to close the 14-point scheduler compliance gap to company average."
        ]
      }
    },
    "2026-01": {
      "composite_score": 70,
      "ioptimize": [
        {
          "location": "BCC MO",
          "scheduler_compliance_avg": 44.89,
          "scheduler_compliance_median": null,
          "avg_delay_avg": 10.21,
          "avg_delay_median": 9.1,
          "chair_utilization_avg": 80.5,
          "chair_utilization_median": 82.0,
          "tx_past_close_avg": 3.8,
          "tx_past_close_median": 3.5,
          "tx_mins_past_close_avg": 16.0,
          "tx_mins_past_close_median": 14.0,
          "mom_deltas": {},
          "vs_company": { "scheduler_compliance": "below" },
          "outlier_flags": []
        }
      ],
      "iassign": [],
      "benchmarks": {
        "company_avg": { "scheduler_compliance_avg": 60.5, "avg_delay_avg": 8.1, "chair_utilization_avg": 78.0, "tx_past_close_avg": 3.6 },
        "onco_benchmark": { "scheduler_compliance_avg": 75.0, "avg_delay_avg": 6.0, "chair_utilization_avg": 85.0, "tx_past_close_avg": 2.0 }
      },
      "ai_insights": { "executive_summary": "January 2026 baseline.", "highlights": [], "concerns": [], "recommendations": [] }
    }
  },
  "chatbot_context": {
    "kpi_definitions": {
      "scheduler_compliance": { "label": "Scheduler Compliance", "unit": "%", "higher_is_better": true, "explanation": "Percentage of appointments scheduled per iOptimize recommendations." },
      "avg_delay_mins": { "label": "Avg Delay", "unit": "mins", "higher_is_better": false, "explanation": "Average daily schedule delay in minutes. Lower is better." }
    },
    "data_notes": "Company Avg rows are the network average across all locations for this client. Onco rows are global benchmarks. MoM deltas compare current to prior month.",
    "historical_kpis": [
      { "month": "2025-09", "location": "BCC MO", "scheduler_compliance_avg": 42.1, "avg_delay_avg": 11.5, "chair_utilization_avg": 77.0, "tx_past_close_avg": 4.2 },
      { "month": "2025-10", "location": "BCC MO", "scheduler_compliance_avg": 43.5, "avg_delay_avg": 11.0, "chair_utilization_avg": 78.5, "tx_past_close_avg": 4.0 },
      { "month": "2025-11", "location": "BCC MO", "scheduler_compliance_avg": 44.2, "avg_delay_avg": 10.8, "chair_utilization_avg": 79.0, "tx_past_close_avg": 3.9 },
      { "month": "2025-12", "location": "BCC MO", "scheduler_compliance_avg": 44.5, "avg_delay_avg": 10.5, "chair_utilization_avg": 80.0, "tx_past_close_avg": 3.8 },
      { "month": "2026-01", "location": "BCC MO", "scheduler_compliance_avg": 44.89, "avg_delay_avg": 10.21, "chair_utilization_avg": 80.5, "tx_past_close_avg": 3.8 },
      { "month": "2026-02", "location": "BCC MO", "scheduler_compliance_avg": 46.99, "avg_delay_avg": 9.81, "chair_utilization_avg": 82.1, "tx_past_close_avg": 3.2 }
    ]
  }
}
```

- [ ] **Step 3: Verify fixtures are reachable from dev server**

```bash
curl http://localhost:5173/ncs-chr-webpage/data/manifest.json
```

Expected: JSON output with `"clients"` array.

- [ ] **Step 4: Commit**

```bash
git add public/data/
git commit -m "chore: add sample fixture JSON files for development"
```

---

### Task 7: Data hooks — `useManifest.js` + `useClinicData.js`

**Files:**
- Create: `src/hooks/useManifest.js`
- Create: `src/hooks/useClinicData.js`

- [ ] **Step 1: Create `src/hooks/useManifest.js`**

```js
import { useState, useEffect } from 'react'

const BASE = import.meta.env.BASE_URL  // '/ncs-chr-webpage/'

export function useManifest() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch(`${BASE}data/manifest.json`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false))
  }, [])

  return { data, loading, error }
}
```

- [ ] **Step 2: Create `src/hooks/useClinicData.js`**

```js
import { useState, useEffect } from 'react'

const BASE = import.meta.env.BASE_URL
const cache = {}

export function useClinicData(clientCode) {
  const [data, setData] = useState(cache[clientCode] ?? null)
  const [loading, setLoading] = useState(!cache[clientCode])
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!clientCode) return
    if (cache[clientCode]) {
      setData(cache[clientCode])
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    fetch(`${BASE}data/${clientCode}.json`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(d => { cache[clientCode] = d; setData(d) })
      .catch(setError)
      .finally(() => setLoading(false))
  }, [clientCode])

  return { data, loading, error }
}
```

- [ ] **Step 3: Smoke-test hooks by temporarily adding a fetch call in CTOMasterView**

Edit `src/pages/CTOMasterView.jsx`:
```jsx
import { useManifest } from '../hooks/useManifest'

export default function CTOMasterView() {
  const { data, loading, error } = useManifest()
  if (loading) return <p className="p-8">Loading...</p>
  if (error) return <p className="p-8 text-red-500">Error: {error.message}</p>
  return <pre className="p-8 text-xs">{JSON.stringify(data, null, 2)}</pre>
}
```

Open `http://localhost:5173/ncs-chr-webpage/`. Expected: raw JSON of manifest displayed.

- [ ] **Step 4: Revert CTOMasterView to placeholder**

```jsx
export default function CTOMasterView() {
  return <div className="p-8 text-slate-700">CTO Master View \u2014 coming soon</div>
}
```

- [ ] **Step 5: Commit**

```bash
git add src/hooks/ src/pages/CTOMasterView.jsx
git commit -m "feat: add useManifest and useClinicData data hooks"
```

---

## Phase 3 — UI Components

> **Use the `frontend-design` skill** when implementing each component below. Pass the component spec as the prompt. All non-ASCII characters must be unicode escapes — no raw em dashes, arrows, or smart quotes.

### Task 8: `NavBar.jsx` + `ScoreBadge.jsx`

**Files:**
- Create: `src/components/NavBar.jsx`
- Create: `src/components/ScoreBadge.jsx`

- [ ] **Step 1: Replace `src/components/NavBar.jsx`**

```jsx
import { Link, useLocation } from 'react-router-dom'

export default function NavBar() {
  const { pathname } = useLocation()
  const label = pathname === '/' ? 'Network Overview' : 'Clinic Dashboard'

  return (
    <nav className="bg-[#0F172A] border-b border-slate-800 px-6 py-4 flex items-center justify-between">
      <Link to="/" className="text-white font-semibold text-lg tracking-tight hover:text-teal-400 transition-colors">
        OncoSmart Analytics
      </Link>
      <span className="text-slate-400 text-sm">{label}</span>
    </nav>
  )
}
```

- [ ] **Step 2: Create `src/components/ScoreBadge.jsx`**

```jsx
function scoreStyle(score) {
  if (score >= 80) return { bg: '#065F46', text: '#6EE7B7' }
  if (score >= 65) return { bg: '#1E3A5F', text: '#93C5FD' }
  if (score >= 50) return { bg: '#78350F', text: '#FCD34D' }
  return { bg: '#7F1D1D', text: '#FCA5A5' }
}

export default function ScoreBadge({ score, size = 'sm' }) {
  if (score == null) return <span className="text-slate-400 text-sm">N/A</span>

  const { bg, text } = scoreStyle(score)
  const cls = size === 'lg'
    ? 'w-20 h-20 text-3xl font-bold rounded-2xl'
    : 'px-2.5 py-1 text-xs font-bold rounded-lg'

  return (
    <span
      className={`inline-flex items-center justify-center ${cls}`}
      style={{ backgroundColor: bg, color: text }}
    >
      {Math.round(score)}
    </span>
  )
}
```

- [ ] **Step 3: Verify in browser — no console errors**

- [ ] **Step 4: Commit**

```bash
git add src/components/NavBar.jsx src/components/ScoreBadge.jsx
git commit -m "feat: add NavBar and ScoreBadge components"
```

---

### Task 9: `KpiCard.jsx` — hero dark-glass metric card

**Files:**
- Create: `src/components/KpiCard.jsx`

- [ ] **Step 1: Create `src/components/KpiCard.jsx`**

Note: up arrow = `\u2191`, down arrow = `\u2193`, right arrow = `\u2192`

```jsx
export default function KpiCard({ label, value, unit, trend, subtitle }) {
  const arrow = trend === 'up' ? '\u2191' : trend === 'down' ? '\u2193' : '\u2192'
  const arrowColor = trend === 'up' ? '#2DD4BF' : trend === 'down' ? '#F87171' : '#94A3B8'

  return (
    <div
      className="bg-[#0F172A] rounded-2xl p-6 border border-slate-800"
      style={{ boxShadow: '0 0 0 1px rgba(13,148,136,0.12), 0 20px 40px rgba(0,0,0,0.25)' }}
    >
      <p className="text-slate-400 text-xs font-semibold uppercase tracking-widest mb-3">
        {label}
      </p>
      <div className="flex items-end gap-2">
        <span className="text-white text-3xl font-bold leading-none">
          {value ?? 'N/A'}
        </span>
        {unit && (
          <span className="text-slate-500 text-sm mb-0.5">{unit}</span>
        )}
        {trend && (
          <span className="text-lg mb-0.5" style={{ color: arrowColor }}>{arrow}</span>
        )}
      </div>
      {subtitle && (
        <p className="text-slate-500 text-xs mt-2">{subtitle}</p>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add src/components/KpiCard.jsx
git commit -m "feat: add KpiCard hero component"
```

---

### Task 10: `KpiTable.jsx`

**Files:**
- Create: `src/components/KpiTable.jsx`

- [ ] **Step 1: Create `src/components/KpiTable.jsx`**

Column definitions map JSON field keys to display metadata. `kpiName` matches keys in `mom_deltas`, `vs_company`, `outlier_flags` from the JSON schema. Up/down arrows: `\u2191` / `\u2193`. Triangle for outlier: `\u25b2`.

```jsx
const IOPTIMIZE_COLS = [
  { key: 'scheduler_compliance_avg', kpiName: 'scheduler_compliance',        label: 'Sched. Compliance', unit: '%',    higherBetter: true },
  { key: 'avg_delay_avg',            kpiName: 'avg_delay_mins',               label: 'Avg Delay',         unit: ' min', higherBetter: false },
  { key: 'avg_delay_median',         kpiName: 'avg_delay_mins',               label: 'Delay Median',      unit: ' min', higherBetter: false },
  { key: 'chair_utilization_avg',    kpiName: 'avg_chair_utilization',        label: 'Chair Util.',       unit: '%',    higherBetter: true },
  { key: 'tx_past_close_avg',        kpiName: 'avg_treatments_per_day',       label: 'Tx Past Close/Day', unit: '/day', higherBetter: false },
  { key: 'tx_mins_past_close_avg',   kpiName: 'avg_treatment_mins_per_patient', label: 'Mins Past Close', unit: ' min', higherBetter: false },
]

const IASSIGN_COLS = [
  { key: 'iassign_utilization_avg',  kpiName: 'iassign_utilization',          label: 'iAssign Util.',   unit: '%',    higherBetter: true },
  { key: 'patients_per_nurse_avg',   kpiName: 'avg_patients_per_nurse',       label: 'Patients/Nurse',  unit: '',     higherBetter: null },
  { key: 'chairs_per_nurse_avg',     kpiName: 'avg_chairs_per_nurse',         label: 'Chairs/Nurse',    unit: '',     higherBetter: null },
  { key: 'nurse_utilization_avg',    kpiName: 'avg_nurse_to_patient_chair_time', label: 'Nurse Util.', unit: '%',    higherBetter: true },
]

function CellValue({ value, unit, vsCompany, higherBetter, isOutlier }) {
  if (value == null) return <span className="text-slate-300">-</span>

  let colorClass = 'text-slate-700'
  if (higherBetter !== null && vsCompany) {
    const good = (higherBetter && vsCompany === 'above') || (!higherBetter && vsCompany === 'below')
    colorClass = good ? 'text-emerald-700 font-semibold' : 'text-red-600 font-semibold'
  }

  return (
    <span className={colorClass}>
      {typeof value === 'number' ? value.toFixed(1) : value}{unit}
      {isOutlier && (
        <span className="ml-1 text-amber-500 text-xs" title="Statistical outlier">\u25b2</span>
      )}
    </span>
  )
}

export default function KpiTable({ rows, source }) {
  const cols = source === 'iOptimize' ? IOPTIMIZE_COLS : IASSIGN_COLS

  if (!rows || rows.length === 0) {
    return <p className="text-slate-400 text-sm italic">No data available for this period.</p>
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr>
            <th className="bg-[#0F172A] text-white text-xs font-medium text-left px-4 py-3 first:rounded-tl-xl">
              Location
            </th>
            {cols.map(col => (
              <th key={col.key} className="bg-[#0F172A] text-white text-xs font-medium text-right px-4 py-3 last:rounded-tr-xl">
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={row.location} className={i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}>
              <td className="px-4 py-3 font-medium text-slate-800 border-b border-slate-100">
                {row.location}
              </td>
              {cols.map(col => (
                <td key={col.key} className="px-4 py-3 text-right border-b border-slate-100">
                  <CellValue
                    value={row[col.key]}
                    unit={col.unit}
                    vsCompany={row.vs_company?.[col.kpiName]}
                    higherBetter={col.higherBetter}
                    isOutlier={row.outlier_flags?.includes(col.kpiName)}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add src/components/KpiTable.jsx
git commit -m "feat: add KpiTable component with color-coded cells"
```

---

### Task 11: `TrendChart.jsx`

**Files:**
- Create: `src/components/TrendChart.jsx`

- [ ] **Step 1: Create `src/components/TrendChart.jsx`**

```jsx
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'

export default function TrendChart({ data, kpiKey, label, unit }) {
  if (!data || data.length < 2) {
    return (
      <div className="bg-white rounded-xl border border-slate-200 p-4">
        <h4 className="text-slate-600 text-sm font-semibold mb-2">{label}</h4>
        <p className="text-slate-400 text-xs italic">Not enough data for trend.</p>
      </div>
    )
  }

  const TEAL = '#0D9488'

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <h4 className="text-slate-700 text-sm font-semibold mb-3">{label}</h4>
      <ResponsiveContainer width="100%" height={120}>
        <AreaChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id={`grad-${kpiKey}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor={TEAL} stopOpacity={0.2} />
              <stop offset="95%" stopColor={TEAL} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" />
          <XAxis dataKey="month" tick={{ fontSize: 10, fill: '#94A3B8' }} />
          <YAxis tick={{ fontSize: 10, fill: '#94A3B8' }} width={38} />
          <Tooltip
            contentStyle={{ fontSize: 12, border: '1px solid #E2E8F0', borderRadius: 8 }}
            formatter={v => [`${v}${unit}`, label]}
          />
          <Area
            type="monotone"
            dataKey="value"
            stroke={TEAL}
            strokeWidth={2}
            fill={`url(#grad-${kpiKey})`}
            dot={{ fill: TEAL, r: 3 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add src/components/TrendChart.jsx
git commit -m "feat: add TrendChart Recharts AreaChart component"
```

---

### Task 12: `InsightPanel.jsx`

**Files:**
- Create: `src/components/InsightPanel.jsx`

- [ ] **Step 1: Create `src/components/InsightPanel.jsx`**

Down chevron: `\u25bc`, up chevron: `\u25b2`

```jsx
import { useState } from 'react'

function CollapsibleSection({ title, items, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  if (!items || items.length === 0) return null

  return (
    <div className="border-t border-slate-100 pt-3 mt-3">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center justify-between w-full text-left group"
      >
        <span className="text-slate-600 text-sm font-medium group-hover:text-teal-700 transition-colors">
          {title}
          <span className="ml-2 text-slate-400 text-xs bg-slate-100 px-1.5 py-0.5 rounded-full">
            {items.length}
          </span>
        </span>
        <span className="text-slate-400 text-xs">{open ? '\u25b2' : '\u25bc'}</span>
      </button>
      {open && (
        <ul className="mt-3 space-y-2">
          {items.map((item, i) => (
            <li key={i} className="text-slate-600 text-sm leading-relaxed pl-4 border-l-2 border-teal-200">
              {item}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function InsightPanel({ insights }) {
  if (!insights) return null

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-6">
      <div className="flex items-center gap-3 mb-4">
        <div className="w-1 h-7 bg-teal-500 rounded-full" />
        <h3 className="text-slate-800 font-semibold text-base">AI Analysis</h3>
      </div>
      {insights.executive_summary && (
        <p className="text-slate-700 text-sm leading-relaxed">
          {insights.executive_summary}
        </p>
      )}
      <CollapsibleSection title="Highlights"       items={insights.highlights}       defaultOpen={true} />
      <CollapsibleSection title="Concerns"         items={insights.concerns} />
      <CollapsibleSection title="Recommendations"  items={insights.recommendations} />
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add src/components/InsightPanel.jsx
git commit -m "feat: add InsightPanel with collapsible sections"
```

---

## Phase 4 — Pages

### Task 13: `CTOMasterView.jsx`

**Files:**
- Modify: `src/pages/CTOMasterView.jsx`

- [ ] **Step 1: Replace `src/pages/CTOMasterView.jsx`**

Middle dot: `\u00b7`, right arrow: `\u2192`, up: `\u2191`, down: `\u2193`

```jsx
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useManifest } from '../hooks/useManifest'
import KpiCard from '../components/KpiCard'
import ScoreBadge from '../components/ScoreBadge'

export default function CTOMasterView() {
  const { data, loading, error } = useManifest()
  const navigate = useNavigate()
  const [sortBy, setSortBy]       = useState('score')
  const [filterTrend, setFilterTrend] = useState('all')

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <p className="text-slate-400">Loading network data\u2026</p>
    </div>
  )
  if (error) return (
    <div className="flex items-center justify-center h-64">
      <p className="text-red-500">Failed to load manifest: {error.message}</p>
    </div>
  )

  const { clients, network_summary, latest_month, generated_at } = data
  const lastUpdated = new Date(generated_at).toLocaleDateString('en-US', {
    month: 'long', day: 'numeric', year: 'numeric',
  })

  let visible = clients.filter(c => filterTrend === 'all' || c.mom_trend === filterTrend)
  visible = [...visible].sort((a, b) =>
    sortBy === 'score'
      ? (b.composite_score ?? 0) - (a.composite_score ?? 0)
      : a.code.localeCompare(b.code)
  )

  return (
    <div className="max-w-7xl mx-auto px-6 py-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-slate-900">OncoSmart Network Dashboard</h1>
        <p className="text-slate-500 text-sm mt-1">
          {latest_month} \u00b7 Last updated {lastUpdated}
        </p>
      </div>

      {/* Network hero cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-10">
        <KpiCard label="Avg Composite Score" value={network_summary.avg_composite_score} unit="/100" />
        <KpiCard label="Top Performer"       value={network_summary.top_performer}        subtitle="Highest composite score" />
        <KpiCard label="Most Improved"       value={network_summary.most_improved}        subtitle="Largest MoM gain" />
        <KpiCard label="Active Clients"      value={clients.length}                       unit="clinics" />
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-4 mb-6">
        <div className="flex items-center gap-2">
          <label className="text-slate-600 text-sm font-medium">Sort by</label>
          <select
            value={sortBy}
            onChange={e => setSortBy(e.target.value)}
            className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-teal-500"
          >
            <option value="score">Composite Score</option>
            <option value="name">Client Name</option>
          </select>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-slate-600 text-sm font-medium">Trend</label>
          <select
            value={filterTrend}
            onChange={e => setFilterTrend(e.target.value)}
            className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-teal-500"
          >
            <option value="all">All</option>
            <option value="up">Improving</option>
            <option value="down">Declining</option>
            <option value="flat">Flat</option>
          </select>
        </div>
        <span className="text-slate-400 text-sm ml-auto">{visible.length} of {clients.length} clients</span>
      </div>

      {/* Clinic grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {visible.map(client => (
          <ClinicCard key={client.code} client={client} onClick={() => navigate(`/clinic/${client.code}`)} />
        ))}
      </div>
    </div>
  )
}

function ClinicCard({ client, onClick }) {
  const trendIcon  = client.mom_trend === 'up' ? '\u2191' : client.mom_trend === 'down' ? '\u2193' : '\u2192'
  const trendColor = client.mom_trend === 'up' ? 'text-teal-600' : client.mom_trend === 'down' ? 'text-red-500' : 'text-slate-400'

  return (
    <button
      onClick={onClick}
      className="bg-white rounded-xl border border-slate-200 p-5 text-left hover:shadow-lg hover:border-teal-300 transition-all duration-150 group"
    >
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="font-bold text-slate-900 text-lg group-hover:text-teal-700 transition-colors">
            {client.code}
          </h3>
          <p className="text-slate-400 text-xs mt-0.5">
            {client.location_count} location{client.location_count !== 1 ? 's' : ''}
          </p>
        </div>
        <ScoreBadge score={client.composite_score} />
      </div>
      <div className="flex items-center gap-1">
        <span className={`font-semibold ${trendColor}`}>{trendIcon}</span>
        <span className="text-slate-400 text-xs">MoM trend \u00b7 {client.latest_month}</span>
      </div>
    </button>
  )
}
```

- [ ] **Step 2: Verify in browser**

Open `http://localhost:5173/ncs-chr-webpage/`. Expected: 14 clinic cards with scores and trend indicators.

- [ ] **Step 3: Commit**

```bash
git add src/pages/CTOMasterView.jsx
git commit -m "feat: implement CTOMasterView with 14-clinic grid"
```

---

### Task 14: `ClinicView.jsx`

**Files:**
- Modify: `src/pages/ClinicView.jsx`

- [ ] **Step 1: Replace `src/pages/ClinicView.jsx`**

Left arrow (back): `\u2190`, middle dot: `\u00b7`, ellipsis: `\u2026`

```jsx
import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useClinicData } from '../hooks/useClinicData'
import ScoreBadge from '../components/ScoreBadge'
import KpiTable from '../components/KpiTable'
import TrendChart from '../components/TrendChart'
import InsightPanel from '../components/InsightPanel'
import ChatBot from '../components/ChatBot'

export default function ClinicView() {
  const { clientCode } = useParams()
  const { data, loading, error } = useClinicData(clientCode)
  const [selectedMonth, setSelectedMonth] = useState(null)

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <p className="text-slate-400">Loading {clientCode}\u2026</p>
    </div>
  )
  if (error) return (
    <div className="flex items-center justify-center h-64">
      <p className="text-red-500">Failed to load {clientCode}: {error.message}</p>
    </div>
  )

  const months     = data.meta.months_available
  const active     = selectedMonth || months[months.length - 1]
  const monthData  = data.months[active] ?? {}
  const locCount   = monthData.ioptimize?.length ?? 0

  // Build avg trend data across all clinic locations for a given JSON field key
  function trendData(jsonKey) {
    return months.map(m => {
      const rows   = data.months[m]?.ioptimize ?? []
      const vals   = rows.map(r => r[jsonKey]).filter(v => v != null)
      const avg    = vals.length > 0 ? vals.reduce((a, b) => a + b, 0) / vals.length : null
      return { month: m, value: avg !== null ? Math.round(avg * 10) / 10 : null }
    }).filter(d => d.value !== null)
  }

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      {/* Breadcrumb */}
      <Link to="/" className="text-teal-600 text-sm hover:text-teal-800 transition-colors">
        \u2190 All Clinics
      </Link>

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between mt-4 mb-8 gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">{clientCode}</h1>
          <p className="text-slate-500 text-sm mt-1">
            {locCount} location{locCount !== 1 ? 's' : ''} \u00b7 {active}
          </p>
        </div>
        <div className="flex items-center gap-4">
          <select
            value={active}
            onChange={e => setSelectedMonth(e.target.value)}
            className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-teal-500"
          >
            {[...months].reverse().map(m => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
          <ScoreBadge score={monthData.composite_score} size="lg" />
        </div>
      </div>

      {/* AI Insights */}
      {monthData.ai_insights && (
        <div className="mb-8">
          <InsightPanel insights={monthData.ai_insights} />
        </div>
      )}

      {/* iOptimize Table */}
      <section className="mb-8">
        <h2 className="text-slate-800 font-semibold text-base mb-4 flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-teal-500 inline-block" />
          iOptimize KPIs
        </h2>
        <KpiTable rows={monthData.ioptimize} source="iOptimize" />
      </section>

      {/* iAssign Table */}
      {monthData.iassign && monthData.iassign.length > 0 && (
        <section className="mb-8">
          <h2 className="text-slate-800 font-semibold text-base mb-4 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-indigo-500 inline-block" />
            iAssign KPIs
          </h2>
          <KpiTable rows={monthData.iassign} source="iAssign" />
        </section>
      )}

      {/* Trend Charts */}
      <section className="mb-8">
        <h2 className="text-slate-800 font-semibold text-base mb-4 flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-slate-400 inline-block" />
          6-Month Trends (avg across locations)
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <TrendChart data={trendData('scheduler_compliance_avg')} kpiKey="sc"    label="Scheduler Compliance" unit="%" />
          <TrendChart data={trendData('avg_delay_avg')}            kpiKey="delay" label="Avg Delay"            unit=" min" />
          <TrendChart data={trendData('chair_utilization_avg')}    kpiKey="chair" label="Chair Utilization"    unit="%" />
          <TrendChart data={trendData('tx_past_close_avg')}        kpiKey="tx"    label="Tx Past Close/Day"    unit="/day" />
        </div>
      </section>

      {/* Chatbot */}
      <ChatBot clinicData={data} clientCode={clientCode} />
    </div>
  )
}
```

- [ ] **Step 2: Create placeholder `src/components/ChatBot.jsx`** (so the app compiles)

```jsx
export default function ChatBot() { return null }
```

- [ ] **Step 3: Verify in browser**

Navigate to `http://localhost:5173/ncs-chr-webpage/#/clinic/HOGONC`. Expected: full clinic view with insights, tables, and trend charts using HOGONC fixture data.

- [ ] **Step 4: Commit**

```bash
git add src/pages/ClinicView.jsx src/components/ChatBot.jsx
git commit -m "feat: implement ClinicView with tables, charts, and insights"
```

---

## Phase 5 — AI Chatbot

### Task 15: `src/lib/anthropic.js` — streaming API call

**Files:**
- Create: `src/lib/anthropic.js`

- [ ] **Step 1: Create `.env.local`** (if it doesn't exist)

```
VITE_ANTHROPIC_API_KEY=sk-ant-...your-key-here...
VITE_CLAUDE_MODEL=claude-haiku-4-5-20251001
```

Do NOT commit this file. Confirm it is in `.gitignore`.

- [ ] **Step 2: Create `src/lib/anthropic.js`**

Smart apostrophe: `\u2019`, em dash: `\u2014`

```js
const API_KEY = import.meta.env.VITE_ANTHROPIC_API_KEY
const MODEL   = import.meta.env.VITE_CLAUDE_MODEL || 'claude-haiku-4-5-20251001'

/**
 * Async generator that streams text chunks from the Anthropic API.
 * @param {Array<{role: string, content: string}>} messages
 * @param {string} systemPrompt
 */
export async function* streamChat(messages, systemPrompt) {
  const response = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-api-key': API_KEY,
      'anthropic-version': '2023-06-01',
      'anthropic-dangerous-direct-browser-access': 'true',
    },
    body: JSON.stringify({
      model: MODEL,
      max_tokens: 1024,
      system: systemPrompt,
      messages,
      stream: true,
    }),
  })

  if (!response.ok) {
    const err = await response.json().catch(() => ({}))
    throw new Error(err.error?.message || `Anthropic API error ${response.status}`)
  }

  const reader  = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer    = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const raw = line.slice(6).trim()
      if (raw === '[DONE]') return
      try {
        const evt = JSON.parse(raw)
        if (evt.type === 'content_block_delta' && evt.delta?.text) {
          yield evt.delta.text
        }
      } catch {
        // ignore malformed SSE lines
      }
    }
  }
}

/**
 * Build the system prompt from a clinic JSON\u2019s chatbot_context.
 */
export function buildSystemPrompt(clinicData, clientCode) {
  const ctx = clinicData.chatbot_context
  const lines = [
    `You are an analytics assistant for the OncoSmart clinic network. ` +
    `You answer questions about ${clientCode}\u2019s clinic performance data. ` +
    `Be concise. Reference specific numbers. Do not invent data not in the context.`,
    '',
    '## KPI Definitions',
    JSON.stringify(ctx.kpi_definitions, null, 2),
    '',
    '## Data Notes',
    ctx.data_notes,
    '',
    '## Historical KPI Data (up to 6 months)',
    JSON.stringify(ctx.historical_kpis, null, 2),
  ]
  return lines.join('\n')
}
```

- [ ] **Step 3: Commit**

```bash
git add src/lib/anthropic.js .env.local
```

Wait — do NOT add `.env.local`. Only add the lib file:

```bash
git add src/lib/anthropic.js
git commit -m "feat: add Anthropic streaming API client"
```

---

### Task 16: `ChatBot.jsx` — floating drawer

**Files:**
- Modify: `src/components/ChatBot.jsx`

- [ ] **Step 1: Replace `src/components/ChatBot.jsx`**

Em dash: `\u2014`, smart apostrophe: `\u2019`, ellipsis: `\u2026`, times (close): `\u00d7`

```jsx
import { useState, useRef, useEffect } from 'react'
import { streamChat, buildSystemPrompt } from '../lib/anthropic'

export default function ChatBot({ clinicData, clientCode }) {
  const [open,      setOpen]      = useState(false)
  const [messages,  setMessages]  = useState([])
  const [input,     setInput]     = useState('')
  const [streaming, setStreaming] = useState(false)
  const bottomRef   = useRef(null)
  const systemPrompt = buildSystemPrompt(clinicData, clientCode)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function send() {
    const text = input.trim()
    if (!text || streaming) return

    const userMsg = { role: 'user', content: text }
    const next    = [...messages, userMsg]
    setMessages(next)
    setInput('')
    setStreaming(true)

    // Append an empty assistant bubble that we will stream into
    setMessages(prev => [...prev, { role: 'assistant', content: '' }])

    try {
      let accumulated = ''
      const apiMessages = next.map(m => ({ role: m.role, content: m.content }))
      for await (const chunk of streamChat(apiMessages, systemPrompt)) {
        accumulated += chunk
        setMessages(prev => {
          const updated = [...prev]
          updated[updated.length - 1] = { role: 'assistant', content: accumulated }
          return updated
        })
      }
    } catch (err) {
      setMessages(prev => {
        const updated = [...prev]
        updated[updated.length - 1] = { role: 'assistant', content: `Error: ${err.message}` }
        return updated
      })
    } finally {
      setStreaming(false)
    }
  }

  function onKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }

  return (
    <>
      {/* Floating trigger button */}
      <button
        onClick={() => setOpen(true)}
        aria-label="Open analytics assistant"
        className="fixed bottom-6 right-6 bg-[#0F172A] text-white rounded-full w-14 h-14 flex items-center justify-center z-40 hover:bg-slate-800 transition-colors"
        style={{ boxShadow: '0 0 0 1px rgba(13,148,136,0.3), 0 8px 32px rgba(0,0,0,0.4)' }}
      >
        <span className="text-lg font-bold">AI</span>
      </button>

      {/* Drawer */}
      {open && (
        <div className="fixed inset-y-0 right-0 w-full sm:w-[420px] bg-white border-l border-slate-200 shadow-2xl flex flex-col z-50">
          {/* Drawer header */}
          <div className="bg-[#0F172A] px-5 py-4 flex items-center justify-between flex-shrink-0">
            <div>
              <p className="text-white font-semibold text-sm">Analytics Assistant</p>
              <p className="text-slate-400 text-xs mt-0.5">
                {clientCode} \u2014 Ask about performance data
              </p>
            </div>
            <button
              onClick={() => setOpen(false)}
              className="text-slate-400 hover:text-white text-2xl leading-none transition-colors"
              aria-label="Close"
            >
              \u00d7
            </button>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
            {messages.length === 0 && (
              <p className="text-slate-400 text-sm text-center mt-10 px-4">
                Ask me about {clientCode}\u2019s KPI trends, comparisons,
                or what to focus on this month.
              </p>
            )}
            {messages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div
                  className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                    msg.role === 'user'
                      ? 'bg-[#0F172A] text-white rounded-br-sm'
                      : 'bg-slate-100 text-slate-800 rounded-bl-sm'
                  }`}
                >
                  {msg.content || (streaming && i === messages.length - 1 ? '\u2026' : '')}
                </div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>

          {/* Input bar */}
          <div className="px-4 py-3 border-t border-slate-200 flex-shrink-0">
            <div className="flex gap-2">
              <input
                type="text"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={onKey}
                placeholder="Ask a question\u2026"
                disabled={streaming}
                className="flex-1 text-sm border border-slate-200 rounded-xl px-3 py-2 focus:outline-none focus:ring-2 focus:ring-teal-500 disabled:opacity-50"
              />
              <button
                onClick={send}
                disabled={streaming || !input.trim()}
                className="bg-teal-600 text-white rounded-xl px-4 py-2 text-sm font-medium hover:bg-teal-700 disabled:opacity-40 transition-colors"
              >
                Send
              </button>
            </div>
            <p className="text-slate-400 text-xs mt-2 text-center">
              Powered by Claude \u00b7 Reads {clientCode} performance data
            </p>
          </div>
        </div>
      )}
    </>
  )
}
```

- [ ] **Step 2: Verify chatbot opens and closes**

Open `http://localhost:5173/ncs-chr-webpage/#/clinic/HOGONC`. Click the "AI" button — drawer should open. Click `×` — drawer should close.

- [ ] **Step 3: Verify streaming works** (requires `VITE_ANTHROPIC_API_KEY` in `.env.local`)

Type "What is the scheduler compliance trend for BCC MO?" and press Enter. Expected: streaming response with reference to the fixture data.

- [ ] **Step 4: Commit**

```bash
git add src/components/ChatBot.jsx
git commit -m "feat: add ChatBot floating drawer with Anthropic streaming"
```

---

## Phase 6 — GitHub Actions Deployment

### Task 17: Deploy workflow + configure GitHub secrets

**Files:**
- Create: `.github/workflows/deploy.yml`

- [ ] **Step 1: Create `.github/workflows/deploy.yml`**

```yaml
name: Deploy to GitHub Pages

on:
  push:
    branches: [main]

permissions:
  contents: write

jobs:
  build-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm

      - run: npm ci

      - name: Build
        run: npm run build
        env:
          VITE_ANTHROPIC_API_KEY: ${{ secrets.VITE_ANTHROPIC_API_KEY }}
          VITE_CLAUDE_MODEL: claude-haiku-4-5-20251001

      - name: Deploy to gh-pages
        uses: peaceiris/actions-gh-pages@v4
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: ./dist
```

- [ ] **Step 2: Add API key as GitHub Actions secret**

Go to `https://github.com/intern-smirta/ncs-chr-webpage/settings/secrets/actions`.
Add secret named `VITE_ANTHROPIC_API_KEY` with the API key value.

- [ ] **Step 3: Verify build works locally first**

```bash
npm run build
```

Expected: `dist/` directory created with no errors.

- [ ] **Step 4: Commit and push to trigger deployment**

```bash
git add .github/
git commit -m "ci: add GitHub Actions deploy workflow to gh-pages"
git push origin main
```

- [ ] **Step 5: Verify deployment**

```bash
# Watch the workflow run
gh run list --repo intern-smirta/ncs-chr-webpage --limit 3
```

Expected: workflow completes successfully. Check `https://intern-smirta.github.io/ncs-chr-webpage/` in browser.

---

## Phase 7 — Migration Cutover

### Task 18: Remove old HTML files + final smoke test

- [ ] **Step 1: Confirm React app is live and working**

Open `https://intern-smirta.github.io/ncs-chr-webpage/`. Verify:
- `/#/` shows CTO master view with all 14 clinic cards
- `/#/clinic/HOGONC` shows HOGONC clinic view with tables and charts
- Chatbot opens and responds

- [ ] **Step 2: Delete old static HTML files from the repo root**

```bash
cd /path/to/ncs-chr-webpage
git rm *.html
# Do NOT remove index.html if it exists at root — check first
ls *.html
```

Expected: list of old static dashboard files like `HOGONC_dashboard.html`, etc.

- [ ] **Step 3: Commit deletion**

```bash
git commit -m "chore: remove old static HTML dashboards — React app is live"
git push origin main
```

- [ ] **Step 4: Final verification after deployment**

After CI runs (~60 seconds), open `https://intern-smirta.github.io/ncs-chr-webpage/`.
Verify the 14 static HTML files no longer exist as direct URLs and the React app loads correctly.

---

## Self-Review

**Spec coverage:**
- [x] Pipeline JSON exporter (Task 1–3)
- [x] JSON schema matching spec exactly (Task 1 + fixture files Task 6)
- [x] Routing: `/#/` → CTOMasterView, `/#/clinic/:code` → ClinicView (Task 5)
- [x] CTO master view: 14 clinic cards, sort, filter, hero KpiCards (Task 13)
- [x] Clinic view: month selector, InsightPanel, iOptimize + iAssign tables, 4 trend charts (Task 14)
- [x] Chatbot: floating drawer, streaming, system prompt from JSON context (Tasks 15–16)
- [x] GitHub Actions deployment (Task 17)
- [x] Migration cutover (Task 18)
- [x] Unicode escapes: all non-ASCII in JS/JSX use `\uXXXX` — confirmed in all component code
- [x] `ensure_ascii=True` in every `json.dumps` call — confirmed in json_exporter.py
- [x] Tailwind v3 + Recharts + Inter font (Task 4)
- [x] `base: '/ncs-chr-webpage/'` in vite.config.js (Task 4)
- [x] `VITE_ANTHROPIC_API_KEY` from `.env.local` + GitHub Actions secret (Tasks 15, 17)
- [x] All 14 clients in fixture manifest (Task 6)

**No placeholders found.** All code is complete with exact file paths and commands.

**Type consistency:** `KpiTable` uses `source="iOptimize"` / `source="iAssign"` (string) consistently with the `IOPTIMIZE_COLS` / `IASSIGN_COLS` branch in Task 10. `useClinicData` returns `{ data, loading, error }` consumed correctly in ClinicView Task 14. `streamChat` is the export name in `anthropic.js` and the import name in `ChatBot.jsx`.

**Scope:** Each task produces working, committable software. Phases 1 and 2–7 are independently executable.
