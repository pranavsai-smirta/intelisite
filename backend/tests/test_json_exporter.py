"""Unit tests for app/engine/json_exporter.py"""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from app.engine.json_exporter import (
    _r, _clean, _get_months, _ioptimize_rows, _iassign_rows,
    _composite_score, build_client_json, build_manifest, export_json,
)
from app.db.models import RowType, KpiSource


# ── helpers ──────────────────────────────────────────────────────────────────

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


# ── _r ───────────────────────────────────────────────────────────────────────

def test_r_rounds():
    assert _r(9.8123, 2) == 9.81


def test_r_none():
    assert _r(None) is None


def test_r_zero():
    assert _r(0.0) == 0.0


# ── _clean ───────────────────────────────────────────────────────────────────

def test_clean_replaces_underscores():
    assert _clean("BCC_MO") == "BCC MO"


def test_clean_strips_whitespace():
    assert _clean("  BCC MO  ") == "BCC MO"


def test_clean_no_change_when_already_clean():
    assert _clean("BCC MO") == "BCC MO"


# ── _ioptimize_rows ───────────────────────────────────────────────────────────

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


def test_ioptimize_rows_empty_when_no_data():
    session = _make_session(all_return=[])
    result = _ioptimize_rows(session, "HOGONC", "2026-01")
    assert result == []


# ── _iassign_rows ─────────────────────────────────────────────────────────────

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
    assert r["mom_deltas"] == {}
    assert r["outlier_flags"] == []


# ── _composite_score ──────────────────────────────────────────────────────────

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


def test_composite_score_excludes_onco_rows():
    row1 = MagicMock()
    row1.location_name = "onco"
    row1.composite_score = 90.0
    row2 = MagicMock()
    row2.location_name = "Real Clinic"
    row2.composite_score = 60.0
    session = _make_session(all_return=[row1, row2])

    result = _composite_score(session, "HOGONC", "2026-01")

    assert result == 60.0


# ── build_client_json ─────────────────────────────────────────────────────────

def test_build_client_json_structure():
    session = _make_session()

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
    assert "data_notes" in result["chatbot_context"]
    assert "historical_kpis" in result["chatbot_context"]


def test_build_client_json_is_ascii_serialisable():
    session = _make_session()

    with patch("app.engine.json_exporter._get_months", return_value=["2026-01"]), \
         patch("app.engine.json_exporter._ioptimize_rows", return_value=[]), \
         patch("app.engine.json_exporter._iassign_rows", return_value=[]), \
         patch("app.engine.json_exporter._enrich"), \
         patch("app.engine.json_exporter._composite_score", return_value=None), \
         patch("app.engine.json_exporter._benchmarks", return_value={}), \
         patch("app.engine.json_exporter._ai_insights", return_value={}), \
         patch("app.engine.json_exporter._historical_kpis", return_value=[]):

        result = build_client_json(session, "HOGONC", "2026-01")

    serialised = json.dumps(result, ensure_ascii=True)
    # All bytes must be ASCII (no raw non-ASCII characters)
    assert all(ord(c) < 128 for c in serialised)
    assert "HOGONC" in serialised


# ── export_json ───────────────────────────────────────────────────────────────

def test_export_json_writes_files(tmp_path):
    session = MagicMock()

    with patch("app.engine.json_exporter.build_client_json", return_value={"meta": {}}), \
         patch("app.engine.json_exporter.build_manifest", return_value={"clients": []}):

        count = export_json(session, ["HOGONC", "PCI"], "2026-01", str(tmp_path))

    assert count == 4  # 2 client files + DEMO.json + manifest
    assert (tmp_path / "HOGONC.json").exists()
    assert (tmp_path / "PCI.json").exists()
    assert (tmp_path / "DEMO.json").exists()
    assert (tmp_path / "manifest.json").exists()


def test_export_json_uses_ensure_ascii(tmp_path):
    """ensure_ascii=True must escape non-ASCII chars so GitHub Pages never sees raw bytes."""
    session = MagicMock()
    payload = {"text": "em\u2014dash"}  # em dash U+2014

    with patch("app.engine.json_exporter.build_client_json", return_value=payload), \
         patch("app.engine.json_exporter.build_manifest", return_value={}):

        export_json(session, ["HOGONC"], "2026-01", str(tmp_path))

    content = (tmp_path / "HOGONC.json").read_text(encoding="utf-8")
    assert "\\u2014" in content   # escaped form must be present
    assert "\u2014" not in content  # raw em dash must NOT appear


def test_export_json_creates_output_dir(tmp_path):
    nested = tmp_path / "deep" / "nested" / "dir"
    session = MagicMock()

    with patch("app.engine.json_exporter.build_client_json", return_value={}), \
         patch("app.engine.json_exporter.build_manifest", return_value={}):

        export_json(session, ["HOGONC"], "2026-01", str(nested))

    assert nested.is_dir()
