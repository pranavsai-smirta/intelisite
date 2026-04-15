"""
RAG chatbot endpoint  —  POST /api/chat

Pipeline:
  1. Receive { messages, client_code, run_month? } from the React frontend
  2. Query ChrKpiWide + ChrComparisonResult + ChrMLAnalytics from PostgreSQL
  3. Build an enriched system prompt (KPIs + outliers + MoM + ML analytics)
  4. Stream Anthropic's response as SSE, in the exact format the
     frontend's streamChat() async-generator parser expects:
       data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"..."}}\n\n
"""
import json
import os
from typing import AsyncIterator, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Belt-and-suspenders: server.py loads .env before importing this module,
# but guard against direct `uvicorn app.api.chat:app` invocation too.
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

app = FastAPI(title="CHR Analytics API", docs_url=None, redoc_url=None)

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 2000


# ─── Pydantic request model ───────────────────────────────────────────────────

class _Msg(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[_Msg]
    client_code: Optional[str] = None
    run_month: Optional[str] = None


# ─── Formatting helper ────────────────────────────────────────────────────────

def _f(v) -> str:
    """Format float to 2 d.p., or em-dash when None."""
    return f"{v:.2f}" if v is not None else "\u2014"


# ─── DB context builder ───────────────────────────────────────────────────────

def _latest_run_month(session, client_code: Optional[str]) -> Optional[str]:
    from app.db.models import ChrKpiWide
    q = session.query(ChrKpiWide.run_month).order_by(ChrKpiWide.run_month.desc())
    if client_code:
        q = q.filter(ChrKpiWide.client_name == client_code)
    row = q.first()
    return row[0] if row else None


def _build_db_context(session, client_code: str, run_month: str) -> str:
    from app.db.models import (
        ChrKpiWide, ChrMLAnalytics, ChrComparisonResult, RowType,
    )

    sections: list[str] = []

    # ── 1. Current-month clinic KPIs ─────────────────────────────────────
    clinic_rows = (
        session.query(ChrKpiWide)
        .filter(
            ChrKpiWide.client_name == client_code,
            ChrKpiWide.run_month == run_month,
            ChrKpiWide.row_type == RowType.CLINIC,
        )
        .order_by(ChrKpiWide.location_name)
        .all()
    )

    if clinic_rows:
        lines = [f"## CURRENT KPIs \u2014 {client_code} / {run_month}"]
        lines.append(
            "Location | SC% | AvgDelay | MedianDelay | CU% | Treatments | "
            "iAssign% | PtsPerNurse | NurseUtil%"
        )
        for r in clinic_rows:
            lines.append(
                f"{r.location_name} | {_f(r.scheduler_compliance)} | "
                f"{_f(r.delay_avg)} | {_f(r.delay_median)} | "
                f"{_f(r.chair_util_avg)} | {_f(r.treatments_avg)} | "
                f"{_f(r.iassign_utilization)} | {_f(r.patients_per_nurse_avg)} | "
                f"{_f(r.nurse_util_avg)}"
            )
        sections.append("\n".join(lines))

    # ── 2. Benchmark rows (Company Avg + Onco) ───────────────────────────
    bench_rows = (
        session.query(ChrKpiWide)
        .filter(
            ChrKpiWide.client_name == client_code,
            ChrKpiWide.run_month == run_month,
            ChrKpiWide.row_type.in_([RowType.COMPANY_AVG, RowType.ONCO]),
        )
        .all()
    )

    if bench_rows:
        lines = ["## BENCHMARKS"]
        for r in bench_rows:
            label = "Company Avg" if r.row_type == RowType.COMPANY_AVG else "Onco Benchmark"
            lines.append(
                f"{label}: SC={_f(r.scheduler_compliance)}% | "
                f"Delay={_f(r.delay_avg)} min | CU={_f(r.chair_util_avg)}% | "
                f"iAssign={_f(r.iassign_utilization)}%"
            )
        sections.append("\n".join(lines))

    # ── 3. Statistical outliers + MoM deltas ────────────────────────────
    cmp_rows = (
        session.query(ChrComparisonResult)
        .filter(
            ChrComparisonResult.client_name == client_code,
            ChrComparisonResult.run_month == run_month,
        )
        .all()
    )

    outliers = [r for r in cmp_rows if r.is_outlier]
    if outliers:
        lines = ["## STATISTICAL OUTLIERS (MAD z-score flagged)"]
        lines.append("Location | KPI | z-score | Percentile | Reason")
        for r in outliers:
            z = f"{r.z_score:.2f}" if r.z_score is not None else "\u2014"
            pct = f"{r.percentile_rank:.0f}th" if r.percentile_rank is not None else "\u2014"
            lines.append(
                f"{r.location_name} | {r.kpi_name} | z={z} | "
                f"{pct} | {r.outlier_reason or '\u2014'}"
            )
        sections.append("\n".join(lines))

    mom: dict[str, list[str]] = {}
    for r in cmp_rows:
        if r.mom_delta_avg is not None and abs(r.mom_delta_avg) > 0.01:
            sign = "+" if r.mom_delta_avg > 0 else ""
            mom.setdefault(r.location_name, []).append(
                f"{r.kpi_name}: {sign}{r.mom_delta_avg:.2f}"
            )
    if mom:
        lines = ["## MONTH-OVER-MONTH DELTAS (vs prior month)"]
        for loc, deltas in sorted(mom.items()):
            lines.append(f"  {loc}: {', '.join(deltas)}")
        sections.append("\n".join(lines))

    # ── 4. ML analytics (Isolation Forest + ARIMA) ──────────────────────
    ml_rows = (
        session.query(ChrMLAnalytics)
        .filter(
            ChrMLAnalytics.client_name == client_code,
            ChrMLAnalytics.run_month == run_month,
        )
        .order_by(ChrMLAnalytics.location_name, ChrMLAnalytics.kpi_name)
        .all()
    )

    anomaly_rows = [r for r in ml_rows if r.kpi_name == "_anomaly"]
    forecast_rows = [r for r in ml_rows if r.kpi_name != "_anomaly"]

    if anomaly_rows:
        lines = ["## ISOLATION FOREST ANOMALY DETECTION"]
        lines.append(
            "Location | ClientAnomaly | ClientScore | NetworkAnomaly | NetworkScore | "
            "LagSC\u2192Chair(r) | LagSC\u2192Chair(n)"
        )
        for r in anomaly_rows:
            ca = "YES" if r.is_anomaly_client else ("no" if r.is_anomaly_client is False else "\u2014")
            na = "YES" if r.is_anomaly_network else ("no" if r.is_anomaly_network is False else "\u2014")
            cs = f"{r.anomaly_score_client:.4f}" if r.anomaly_score_client is not None else "\u2014"
            ns = f"{r.anomaly_score_network:.4f}" if r.anomaly_score_network is not None else "\u2014"
            lr = f"{r.lag_sc_to_chair_r:.3f}" if r.lag_sc_to_chair_r is not None else "\u2014"
            ln = str(r.lag_sc_to_chair_n) if r.lag_sc_to_chair_n is not None else "\u2014"
            lines.append(
                f"{r.location_name} | {ca} | {cs} | {na} | {ns} | {lr} | {ln}"
            )
        sections.append("\n".join(lines))

    if forecast_rows:
        lines = ["## ARIMA FORECASTS (next-month projection, 95% CI)"]
        lines.append(
            "Location | KPI | Forecast | Lower95 | Upper95 | N_months | Method | Converged"
        )
        for r in forecast_rows:
            conv = "yes" if r.arima_converged else ("no" if r.arima_converged is False else "\u2014")
            lines.append(
                f"{r.location_name} | {r.kpi_name} | {_f(r.arima_forecast)} | "
                f"{_f(r.arima_lower_95)} | {_f(r.arima_upper_95)} | "
                f"{r.arima_n_months or '\u2014'} | {r.arima_method or '\u2014'} | {conv}"
            )
        sections.append("\n".join(lines))

    # ── 5. Historical KPIs (last 6 months) ──────────────────────────────
    hist_rows = (
        session.query(ChrKpiWide)
        .filter(
            ChrKpiWide.client_name == client_code,
            ChrKpiWide.run_month < run_month,
            ChrKpiWide.row_type == RowType.CLINIC,
        )
        .order_by(ChrKpiWide.run_month.desc(), ChrKpiWide.location_name)
        .limit(300)
        .all()
    )

    # Keep at most 6 distinct prior months
    seen_months: set[str] = set()
    filtered: list = []
    for r in hist_rows:
        seen_months.add(r.run_month)
        if len(seen_months) > 6:
            break
        filtered.append(r)

    if filtered:
        lines = ["## HISTORICAL KPIs (prior months, oldest \u2192 newest)"]
        for r in sorted(filtered, key=lambda x: (x.run_month, x.location_name)):
            lines.append(
                f"{r.run_month} | {r.location_name} | "
                f"SC={_f(r.scheduler_compliance)}% | Delay={_f(r.delay_avg)} min | "
                f"CU={_f(r.chair_util_avg)}%"
            )
        sections.append("\n".join(lines))

    return "\n\n".join(sections) if sections else "(no data found in database for this client/month)"


# ─── Network-wide context builder (client_code=None) ─────────────────────────

def _build_network_context(session, run_month: str) -> str:
    from app.db.models import (
        ChrKpiWide, ChrMLAnalytics, ChrComparisonResult, RowType,
    )

    sections: list[str] = []

    # ── 1. Per-client company averages ──────────────────────────────────
    client_avg_rows = (
        session.query(ChrKpiWide)
        .filter(
            ChrKpiWide.run_month == run_month,
            ChrKpiWide.row_type == RowType.COMPANY_AVG,
        )
        .order_by(ChrKpiWide.client_name)
        .all()
    )

    if client_avg_rows:
        lines = [f"## NETWORK CLIENT AVERAGES \u2014 {run_month}"]
        lines.append(
            "Client | SC% | AvgDelay | CU% | iAssign% | PtsPerNurse | NurseUtil%"
        )
        for r in client_avg_rows:
            lines.append(
                f"{r.client_name} | {_f(r.scheduler_compliance)} | "
                f"{_f(r.delay_avg)} | {_f(r.chair_util_avg)} | "
                f"{_f(r.iassign_utilization)} | {_f(r.patients_per_nurse_avg)} | "
                f"{_f(r.nurse_util_avg)}"
            )
        sections.append("\n".join(lines))

    # ── 2. Onco benchmark row (any client — value is global, identical) ──
    onco_row = (
        session.query(ChrKpiWide)
        .filter(
            ChrKpiWide.run_month == run_month,
            ChrKpiWide.row_type == RowType.ONCO,
        )
        .first()
    )

    if onco_row:
        lines = ["## ONCO NETWORK BENCHMARK"]
        lines.append(
            f"SC={_f(onco_row.scheduler_compliance)}% | "
            f"Delay={_f(onco_row.delay_avg)} min | "
            f"CU={_f(onco_row.chair_util_avg)}% | "
            f"iAssign={_f(onco_row.iassign_utilization)}%"
        )
        sections.append("\n".join(lines))

    # ── 3. Top cross-network statistical outliers ────────────────────────
    network_outliers = (
        session.query(ChrComparisonResult)
        .filter(
            ChrComparisonResult.run_month == run_month,
            ChrComparisonResult.is_outlier == True,
        )
        .order_by(ChrComparisonResult.z_score.desc())
        .limit(25)
        .all()
    )

    if network_outliers:
        lines = ["## TOP NETWORK STATISTICAL OUTLIERS (MAD z-score)"]
        lines.append("Client | Location | KPI | z-score | Percentile | Reason")
        for r in network_outliers:
            z = f"{r.z_score:.2f}" if r.z_score is not None else "\u2014"
            pct = f"{r.percentile_rank:.0f}th" if r.percentile_rank is not None else "\u2014"
            lines.append(
                f"{r.client_name} | {r.location_name} | {r.kpi_name} | "
                f"z={z} | {pct} | {r.outlier_reason or '\u2014'}"
            )
        sections.append("\n".join(lines))

    # ── 4. Highest network-level Isolation Forest anomalies ──────────────
    network_anomaly_rows = (
        session.query(ChrMLAnalytics)
        .filter(
            ChrMLAnalytics.run_month == run_month,
            ChrMLAnalytics.kpi_name == "_anomaly",
            ChrMLAnalytics.is_anomaly_network == True,
        )
        .order_by(ChrMLAnalytics.anomaly_score_network)   # most negative = most anomalous
        .limit(15)
        .all()
    )

    if network_anomaly_rows:
        lines = ["## HIGHEST NETWORK ANOMALIES (Isolation Forest)"]
        lines.append(
            "Client | Location | NetworkScore | ClientAnomaly | ClientScore"
        )
        for r in network_anomaly_rows:
            ca = "YES" if r.is_anomaly_client else ("no" if r.is_anomaly_client is False else "\u2014")
            cs = f"{r.anomaly_score_client:.4f}" if r.anomaly_score_client is not None else "\u2014"
            ns = f"{r.anomaly_score_network:.4f}" if r.anomaly_score_network is not None else "\u2014"
            lines.append(
                f"{r.client_name} | {r.location_name} | {ns} | {ca} | {cs}"
            )
        sections.append("\n".join(lines))

    return "\n\n".join(sections) if sections else "(no network data found for this month)"


# ─── System prompt builder ────────────────────────────────────────────────────

def _build_system_prompt(client_code: Optional[str], run_month: str, db_context: str) -> str:
    scope_line = (
        f"SCOPE: Full network overview | REPORTING MONTH: {run_month}"
        if client_code is None
        else f"CLIENT: {client_code} | REPORTING MONTH: {run_month}"
    )
    return "\n".join([
        "You are an elite Oncology Clinic Operations AI with access to real-time, mathematically verified clinic performance data.",
        "Answer ONLY using the data in the DATABASE CONTEXT section below. Do not hallucinate numbers, locations, or metrics not present there.",
        "If a value shows '\u2014', it is NULL or unavailable \u2014 state that explicitly. Never impute or interpolate.",
        "",
        scope_line,
        "",
        "## RESPONSE STYLE",
        "Lead with the finding. No greetings, no meta-commentary, no closings.",
        "FORBIDDEN: Hi, Hello, Sure, Certainly, Great question, I'll analyze, Looking at the data, I hope this helps.",
        "Format with Markdown: **bold** key numbers, bullet lists, ## headers.",
        "For small talk: one brief professional sentence, then redirect to data.",
        "",
        "## ANALYTICAL STANDARDS",
        "- Every claim requires a specific number from the dataset. No generalities.",
        "- Anchor comparisons with both values: 'BCC MO (**97.9%**) vs. Company Avg (**66.8%**)' \u2014 not 'above average'.",
        "- State magnitudes: 'rose **4.2 min** from 6.1 to 10.3' \u2014 not 'increased significantly'.",
        "- Correlation \u2260 causation. Exception: Scheduler Compliance and Avg Delay have an established operational link.",
        "- For 'why' questions: list 2\u20133 data-supported hypotheses; close with what investigation would confirm.",
        "- A MoM change is meaningful only if |delta| > ~0.5 SD or > 3 absolute units.",
        "",
        "## BENCHMARK DEFINITIONS",
        "- **Company Average**: Mean of THIS client\u2019s own clinic locations only. Not a network figure.",
        "- **Onco Benchmark**: Network-wide oncology standard across all clients. The aspirational target.",
        "- **Composite Score (0\u2013100)**: 50 = network average. 65+ = strong. <40 = needs attention.",
        "",
        "## ML ANALYTICS INTERPRETATION",
        "- **Isolation Forest**: ClientAnomaly=YES \u2192 this location\u2019s KPI vector is statistically unusual within this client\u2019s own clinics.",
        "  NetworkAnomaly=YES \u2192 unusual across ALL clients in the network.",
        "  Score is negative; closer to 0 = more normal, closer to \u22121 = more anomalous.",
        "- **Lag SC\u2192Chair**: does last month\u2019s Scheduler Compliance predict this month\u2019s Chair Utilization?",
        "  r > 0.6 = strong predictive signal. n = number of month-pairs used (minimum 4 required).",
        "- **ARIMA Forecast**: statistical projection for NEXT month with 95% confidence interval.",
        "  method='moving_avg' means insufficient history for ARIMA \u2014 interpret with more caution.",
        "",
        "## DATA VISUALIZATION",
        "When a comparison, trend, or multi-location breakdown aids understanding, you MUST output a chart.",
        "Use charts for: 3+ data point comparisons, multi-location analysis, 6-month trends, benchmark vs. actuals.",
        "Do NOT use charts for: single-value answers, yes/no questions, simple factual lookups.",
        "",
        "Output charts as a Markdown code block tagged `recharts`. Place a brief sentence BEFORE the block.",
        'Bar chart: {"type":"BarChart","title":"...","data":[{"name":"...","value":0}],"xAxisKey":"name","series":[{"dataKey":"value","color":"#0D9488","name":"..."}]}',
        "Colors: #0D9488 teal | #6366F1 indigo | #DC2626 red | #F59E0B amber",
        "Rules: valid JSON only, no trailing commas, no comments, no newlines inside the block.",
        "",
        "## METRIC-SPECIFIC RULES",
        "- Chair Util >100%: overbooking (not a data error). Trending toward 100% = improving capacity management.",
        "- Scheduler Compliance: frequently NULL. Absence \u2260 poor performance.",
        "- Tx Past Close/Day: lower is better. Zero is ideal. High values drive staff overtime.",
        "- Patients/Nurse: context-dependent. Too high = understaffing. Too low = inefficiency.",
        "",
        "=" * 64,
        "DATABASE CONTEXT  (live data from PostgreSQL \u2014 treat as ground truth)",
        "=" * 64,
        db_context,
    ])


# ─── SSE streaming generator ──────────────────────────────────────────────────

async def _sse_stream(
    messages: list[dict],
    system_prompt: str,
) -> AsyncIterator[str]:
    import anthropic

    try:
        client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

        async with client.messages.stream(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=system_prompt,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                payload = json.dumps({
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": text},
                })
                yield f"data: {payload}\n\n"

        yield "data: [DONE]\n\n"

    except Exception as exc:
        payload = json.dumps({"type": "error", "message": str(exc)})
        yield f"data: {payload}\n\n"
        yield "data: [DONE]\n\n"


# ─── Endpoint ─────────────────────────────────────────────────────────────────

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    from app.db.session import get_session

    with get_session() as session:
        run_month = req.run_month or _latest_run_month(session, req.client_code)
        if not run_month:
            detail = (
                "No data found in database."
                if req.client_code is None
                else f"No data found in database for client '{req.client_code}'."
            )
            raise HTTPException(status_code=404, detail=detail)
        if req.client_code:
            db_context = _build_db_context(session, req.client_code, run_month)
        else:
            db_context = _build_network_context(session, run_month)

    system_prompt = _build_system_prompt(req.client_code, run_month, db_context)
    api_messages = [{"role": m.role, "content": m.content} for m in req.messages]

    return StreamingResponse(
        _sse_stream(api_messages, system_prompt),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
