"""
CHR Automation - Database Models
Architecture: Two-layer storage
  Layer 1 (Raw):  chr_issue_snapshot, chr_kpi_value  — exact data as submitted
  Layer 2 (Wide): chr_kpi_wide — one row per location/month, all KPIs as columns
  Layer 3 (AI):   chr_comparison_result, chr_kpi_correlation, chr_ai_insight, chr_email_draft
"""
from sqlalchemy import (
    Column, Integer, String, DateTime, Text, Float,
    Boolean, UniqueConstraint, Index, Enum
)
from sqlalchemy.sql import func
import enum
from .session import Base


# ─────────────────────────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────────────────────────

class RowType(enum.Enum):
    CLINIC      = "clinic"       # Individual location (BCC MO, MTHMO, etc.)
    COMPANY_AVG = "company_avg"  # Company Avg row
    ONCO        = "onco"         # Onco global benchmark row


class KpiSource(enum.Enum):
    IOPTIMIZE = "iOptimize"
    IASSIGN   = "iAssign"


# ─────────────────────────────────────────────────────────────
# TABLE 1: RAW GITHUB ISSUE SNAPSHOT
# Purpose: Immutable audit trail. Never changes after fetch.
# ─────────────────────────────────────────────────────────────

class ChrIssueSnapshot(Base):
    """Stores the raw GitHub issue exactly as submitted by the clinic."""
    __tablename__ = "chr_issue_snapshot"

    id               = Column(Integer, primary_key=True)
    run_month        = Column(String(7),   nullable=False, index=True)   # 2026-01
    client_name      = Column(String(100), nullable=False, index=True)   # HOGONC
    repo             = Column(String(200), nullable=False)
    issue_number     = Column(Integer,     nullable=False)
    issue_title      = Column(String(500), nullable=False)
    issue_url        = Column(String(500), nullable=False)
    issue_created_at = Column(DateTime(timezone=True), nullable=True)
    issue_updated_at = Column(DateTime(timezone=True), nullable=True)
    body_markdown    = Column(Text, nullable=False)                       # Full raw markdown
    fetched_at       = Column(DateTime(timezone=True), server_default=func.now())
    run_id           = Column(String(50), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("repo", "issue_number", name="uq_snapshot_repo_issue"),
        Index("ix_snapshot_client_month", "client_name", "run_month"),
    )


# ─────────────────────────────────────────────────────────────
# TABLE 2: NORMALIZED KPI VALUES (Long/Narrow format)
# Purpose: One row per KPI per location. Raw parsed values.
#          Used as audit trail and source for wide table.
# ─────────────────────────────────────────────────────────────

class ChrKpiValue(Base):
    """
    Normalized KPI storage. One row per KPI per location per month.
    Keeps avg and median as separate float columns.
    Keeps value_raw as the original text for auditability.
    """
    __tablename__ = "chr_kpi_value"

    id               = Column(Integer, primary_key=True)

    # Identity
    run_month        = Column(String(7),   nullable=False, index=True)
    client_name      = Column(String(100), nullable=False, index=True)
    location_name    = Column(String(100), nullable=False, index=True)
    row_type         = Column(Enum(RowType),   nullable=False, index=True)
    source           = Column(Enum(KpiSource), nullable=False, index=True)
    kpi_name         = Column(String(100), nullable=False, index=True)
    kpi_display_name = Column(String(500), nullable=False)

    # Values — avg and median always stored separately
    value_raw    = Column(String(100), nullable=False)  # "9.81(8.64)" — never lose original
    value_avg    = Column(Float, nullable=True)          # 9.81
    value_median = Column(Float, nullable=True)          # 8.64
    value_unit   = Column(String(20), nullable=True)     # "%", "mins", "count"

    # Data quality
    parse_status = Column(String(20), nullable=False, default="ok")  # ok/warning/failed
    parse_notes  = Column(Text, nullable=True)

    # Traceability
    issue_number = Column(Integer, nullable=False)
    run_id       = Column(String(50), nullable=False)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "run_month", "client_name", "location_name", "source", "kpi_name",
            name="uq_kpi_month_client_loc_source_kpi"
        ),
        Index("ix_kpi_source_name", "source", "kpi_name"),
        Index("ix_kpi_row_type", "row_type"),
        Index("ix_kpi_client_month_source", "client_name", "run_month", "source"),
    )


# ─────────────────────────────────────────────────────────────
# TABLE 3: WIDE KPI TABLE ← THE KEY NEW TABLE
# Purpose: One row per location per month. All KPIs as columns.
#          This is what the AI reads. This is what comparisons use.
#          Much faster queries. Much simpler AI prompts.
# ─────────────────────────────────────────────────────────────

class ChrKpiWide(Base):
    """
    Wide-format KPI storage. One row = one location + one month.
    All KPIs stored as individual columns with avg and median separated.

    This is the PRIMARY table for:
      - Comparison engine (Step 3)
      - AI insight generation (Step 5)
      - Email drafting (Step 6)

    Example row for HOGONC / BCC MO / 2026-01:
      client_name          = "HOGONC"
      location_name        = "BCC MO"
      run_month            = "2026-01"
      source               = "iOptimize"
      scheduler_compliance = 46.99
      delay_avg            = 9.81
      delay_median         = 8.64
      treatments_avg       = 2.86
      treatments_median    = 3.00
      tx_mins_avg          = 16.52
      tx_mins_median       = 14.67
      chair_util_avg       = 91.14
      chair_util_median    = 94.85
    """
    __tablename__ = "chr_kpi_wide"

    id            = Column(Integer, primary_key=True)

    # Identity
    run_month     = Column(String(7),   nullable=False, index=True)
    client_name   = Column(String(100), nullable=False, index=True)
    location_name = Column(String(100), nullable=False, index=True)
    row_type      = Column(Enum(RowType),   nullable=False, index=True)
    source        = Column(Enum(KpiSource), nullable=False, index=True)

    # ── iOptimize KPIs ──────────────────────────────────────
    scheduler_compliance      = Column(Float, nullable=True)  # % (no median)

    delay_avg                 = Column(Float, nullable=True)  # mins
    delay_median              = Column(Float, nullable=True)

    treatments_avg            = Column(Float, nullable=True)  # count
    treatments_median         = Column(Float, nullable=True)

    tx_mins_avg               = Column(Float, nullable=True)  # mins
    tx_mins_median            = Column(Float, nullable=True)

    chair_util_avg            = Column(Float, nullable=True)  # %
    chair_util_median         = Column(Float, nullable=True)

    # ── iAssign KPIs ────────────────────────────────────────
    iassign_utilization       = Column(Float, nullable=True)  # % (no median)

    patients_per_nurse_avg    = Column(Float, nullable=True)  # count
    patients_per_nurse_median = Column(Float, nullable=True)

    chairs_per_nurse_avg      = Column(Float, nullable=True)  # count
    chairs_per_nurse_median   = Column(Float, nullable=True)

    nurse_util_avg            = Column(Float, nullable=True)  # %
    nurse_util_median         = Column(Float, nullable=True)

    # ── Data quality ────────────────────────────────────────
    has_warnings  = Column(Boolean, default=False)  # True if any KPI had parse issues
    issue_number  = Column(Integer, nullable=False)
    run_id        = Column(String(50), nullable=False)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "run_month", "client_name", "location_name", "source",
            name="uq_wide_month_client_loc_source"
        ),
        Index("ix_wide_client_month", "client_name", "run_month"),
        Index("ix_wide_row_type", "row_type"),
        Index("ix_wide_source", "source"),
        # This index makes "get all months for HOGONC BCC MO" very fast
        Index("ix_wide_client_location_history", "client_name", "location_name", "run_month"),
    )


# ─────────────────────────────────────────────────────────────
# TABLE 4: COMPARISON RESULTS
# Purpose: Pre-computed comparisons. MoM, vs company, vs Onco.
#          AI reads this — doesn't need to calculate anything.
# ─────────────────────────────────────────────────────────────

class ChrComparisonResult(Base):
    """
    One row per KPI per location per month.
    Stores every comparison pre-computed so AI just reads numbers.
    """
    __tablename__ = "chr_comparison_result"

    id            = Column(Integer, primary_key=True)
    run_month     = Column(String(7),   nullable=False, index=True)
    client_name   = Column(String(100), nullable=False, index=True)
    location_name = Column(String(100), nullable=False)
    source        = Column(Enum(KpiSource), nullable=False)
    kpi_name      = Column(String(100), nullable=False)

    # Current month
    current_avg    = Column(Float, nullable=True)
    current_median = Column(Float, nullable=True)

    # Month-over-Month
    prior_month          = Column(String(7),  nullable=True)   # which month we compared to
    prior_avg            = Column(Float, nullable=True)
    prior_median         = Column(Float, nullable=True)
    mom_delta_avg        = Column(Float, nullable=True)   # absolute change
    mom_delta_avg_pct    = Column(Float, nullable=True)   # % change
    mom_delta_median     = Column(Float, nullable=True)
    mom_delta_median_pct = Column(Float, nullable=True)
    mom_direction        = Column(String(10), nullable=True)  # "up", "down", "flat"
    mom_is_good          = Column(Boolean, nullable=True)     # True=improvement, False=decline

    # vs Company Average (same client, same month)
    company_avg_value    = Column(Float, nullable=True)
    vs_company_delta     = Column(Float, nullable=True)
    vs_company_delta_pct = Column(Float, nullable=True)
    vs_company_rank      = Column(Integer, nullable=True)  # rank among all locations (1=best)

    # vs Onco Global Benchmark
    onco_value           = Column(Float, nullable=True)
    vs_onco_delta        = Column(Float, nullable=True)
    vs_onco_delta_pct    = Column(Float, nullable=True)
    vs_onco_direction    = Column(String(10), nullable=True)  # "above", "below", "at"

    # Statistical
    z_score              = Column(Float, nullable=True)   # vs company group this month
    percentile_rank      = Column(Float, nullable=True)   # 0-100, 100=best
    is_outlier           = Column(Boolean, default=False)
    outlier_reason       = Column(String(200), nullable=True)
    mom_is_meaningful    = Column(Boolean, nullable=True)  # is MoM delta > 0.5 * hist_std?

    # Volatility
    volatility_score     = Column(Float, nullable=True)   # std dev last 6 months
    volatility_label     = Column(String(20), nullable=True)  # stable/moderate/high

    # Trend (linear regression over last 3-6 months)
    trend_slope          = Column(Float, nullable=True)   # units/month
    trend_r2             = Column(Float, nullable=True)   # 0-1, trend consistency
    trend_label          = Column(String(20), nullable=True)  # improving/declining/stable
    streak_count         = Column(Integer, nullable=True)  # consecutive months same direction
    streak_direction     = Column(String(20), nullable=True)  # improving/declining

    # Rolling averages
    rolling_avg_3m       = Column(Float, nullable=True)
    rolling_avg_6m       = Column(Float, nullable=True)

    # Global benchmarks (across ALL clients this month)
    global_avg_value     = Column(Float, nullable=True)
    vs_global_delta      = Column(Float, nullable=True)
    vs_global_delta_pct  = Column(Float, nullable=True)

    # Best-in-class (top decile across all history)
    best_in_class_value  = Column(Float, nullable=True)
    vs_best_in_class_pct = Column(Float, nullable=True)

    # Composite performance score
    composite_component  = Column(Float, nullable=True)  # this KPI's normalised 0-100 contribution
    composite_score      = Column(Float, nullable=True)  # weighted aggregate for the location

    # Traceability
    run_id       = Column(String(50), nullable=False)
    computed_at  = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "run_month", "client_name", "location_name", "source", "kpi_name",
            name="uq_cmp_month_client_loc_source_kpi"
        ),
        Index("ix_cmp_client_month", "client_name", "run_month"),
        Index("ix_cmp_outliers", "is_outlier", "run_month"),
        Index("ix_cmp_kpi_month", "kpi_name", "run_month"),
    )


# ─────────────────────────────────────────────────────────────
# TABLE 5: KPI CORRELATIONS
# Purpose: "When scheduler compliance goes up, delays go down"
#          Detected automatically. AI uses these for richer insights.
# ─────────────────────────────────────────────────────────────

class ChrKpiCorrelation(Base):
    """Detected relationships between KPIs across months."""
    __tablename__ = "chr_kpi_correlation"

    id            = Column(Integer, primary_key=True)
    run_month     = Column(String(7),   nullable=False, index=True)
    client_name   = Column(String(100), nullable=False, index=True)
    location_name = Column(String(100), nullable=False)

    kpi1_source     = Column(Enum(KpiSource), nullable=False)
    kpi1_name       = Column(String(100), nullable=False)
    kpi1_change_pct = Column(Float, nullable=True)

    kpi2_source     = Column(Enum(KpiSource), nullable=False)
    kpi2_name       = Column(String(100), nullable=False)
    kpi2_change_pct = Column(Float, nullable=True)

    correlation_type    = Column(String(50), nullable=False)   # likely_causal/plausible_causal/correlated_confounded/correlated_unknown/spurious
    narrative_quality   = Column(String(500), nullable=False)  # human-readable explanation of the relationship
    should_highlight    = Column(Boolean, default=False)

    run_id     = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_corr_client_month", "client_name", "run_month"),
        Index("ix_corr_highlight", "should_highlight"),
    )


# ─────────────────────────────────────────────────────────────
# TABLE 6: AI INSIGHTS
# Purpose: Claude-generated observations, stored with priority.
#          Multiple insight types per client per month.
# ─────────────────────────────────────────────────────────────

class ChrAiInsight(Base):
    """AI-generated insights for each client/month."""
    __tablename__ = "chr_ai_insight"

    id          = Column(Integer, primary_key=True)
    run_month   = Column(String(7),   nullable=False, index=True)
    client_name = Column(String(100), nullable=False, index=True)

    # executive_summary / highlight / concern / recommendation / trend
    insight_type     = Column(String(50), nullable=False)
    insight_text     = Column(Text, nullable=False)
    priority         = Column(Integer, default=0)   # Higher = shown first in email
    supporting_kpis  = Column(Text, nullable=True)  # JSON: ["scheduler_compliance", "delay_avg"]
    confidence_score = Column(Float, nullable=True) # 0.0 - 1.0

    run_id       = Column(String(50), nullable=False)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_insight_client_month", "client_name", "run_month"),
        Index("ix_insight_type_priority", "insight_type", "priority"),
    )


# ─────────────────────────────────────────────────────────────
# TABLE 7: EMAIL DRAFTS
# Purpose: Generated emails waiting for CTO review.
#          Full workflow: generated → reviewed → sent.
# ─────────────────────────────────────────────────────────────

class ChrEmailDraft(Base):
    """Email drafts generated for CTO review and sending."""
    __tablename__ = "chr_email_draft"

    id          = Column(Integer, primary_key=True)
    run_month   = Column(String(7),   nullable=False, index=True)
    client_name = Column(String(100), nullable=False, index=True)

    subject_line    = Column(String(500), nullable=False)
    body_html       = Column(Text, nullable=False)
    body_plain_text = Column(Text, nullable=True)
    attachment_ids  = Column(Text, nullable=True)  # JSON array of artifact IDs

    draft_status = Column(String(20), default="generated")  # generated/reviewed/sent
    reviewed_by  = Column(String(100), nullable=True)
    reviewed_at  = Column(DateTime(timezone=True), nullable=True)
    sent_at      = Column(DateTime(timezone=True), nullable=True)

    run_id     = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("run_month", "client_name", name="uq_draft_month_client"),
        Index("ix_draft_status", "draft_status"),
    )


# ─────────────────────────────────────────────────────────────
# TABLE 8: REPORT ARTIFACTS
# Purpose: Track all generated files (PDFs, charts, etc.)
# ─────────────────────────────────────────────────────────────

class ChrMLAnalytics(Base):
    """
    Stores per-location ML analytics computed in Step 3.5.

    Row types (distinguished by kpi_name):
      kpi_name = '_anomaly'     — Isolation Forest scores (location-level)
                                  + lag cross-correlation (client-level, repeated per location)
      kpi_name = <actual name>  — ARIMA forecast for that KPI at this location

    Both types share the same table for chatbot simplicity: one JOIN retrieves
    all ML context for a location in a single query.
    """
    __tablename__ = "chr_ml_analytics"

    id            = Column(Integer, primary_key=True)

    # Identity
    run_month     = Column(String(7),   nullable=False, index=True)
    client_name   = Column(String(100), nullable=False, index=True)
    location_name = Column(String(100), nullable=False, index=True)
    kpi_name      = Column(String(100), nullable=False, index=True)
    # '_anomaly' for location-level IF scores; actual kpi name for ARIMA rows

    # ── Isolation Forest (populated only when kpi_name = '_anomaly') ──
    is_anomaly_client    = Column(Boolean,  nullable=True)
    anomaly_score_client = Column(Float,    nullable=True)
    # Negative score = more anomalous (sklearn convention: -1 to 0)
    is_anomaly_network   = Column(Boolean,  nullable=True)
    anomaly_score_network = Column(Float,   nullable=True)

    # ── ARIMA forecast (populated only when kpi_name = <actual KPI>) ──
    arima_forecast   = Column(Float,   nullable=True)   # point estimate for next month
    arima_lower_95   = Column(Float,   nullable=True)   # 95% confidence interval lower
    arima_upper_95   = Column(Float,   nullable=True)   # 95% confidence interval upper
    arima_n_months   = Column(Integer, nullable=True)   # months of history used
    arima_method     = Column(String(20), nullable=True)  # 'arima' | 'moving_avg'
    arima_converged  = Column(Boolean, nullable=True)

    # ── Lag cross-correlation (populated only when kpi_name = '_anomaly') ──
    # Tests: does scheduler_compliance(T-1) predict chair_utilization(T)?
    lag_sc_to_chair_r = Column(Float,   nullable=True)  # Pearson r (null if < 4 pairs)
    lag_sc_to_chair_n = Column(Integer, nullable=True)  # number of (T-1, T) data pairs used

    # Traceability
    run_id      = Column(String(50), nullable=False)
    computed_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "run_month", "client_name", "location_name", "kpi_name",
            name="uq_ml_month_client_loc_kpi"
        ),
        Index("ix_ml_client_month",  "client_name", "run_month"),
        Index("ix_ml_anomaly_flags", "is_anomaly_client", "is_anomaly_network", "run_month"),
    )


class ChrReportArtifact(Base):
    """Tracks all generated files — PDFs, charts, JSON exports."""
    __tablename__ = "chr_report_artifact"

    id          = Column(Integer, primary_key=True)
    run_month   = Column(String(7),   nullable=False, index=True)
    client_name = Column(String(100), nullable=True,  index=True)

    artifact_type    = Column(String(50),  nullable=False)   # chart_png/pdf/email_html
    artifact_name    = Column(String(200), nullable=False)
    file_path        = Column(String(500), nullable=False)
    file_size_bytes  = Column(Integer, nullable=True)
    file_sha256      = Column(String(64), nullable=False)
    mime_type        = Column(String(100), nullable=True)

    run_id     = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_artifact_client_month", "client_name", "run_month"),
        Index("ix_artifact_type", "artifact_type"),
    )