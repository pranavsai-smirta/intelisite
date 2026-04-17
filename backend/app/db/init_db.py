"""Database initialization"""
from .session import init_sessionmaker, Base
from .models import (
    ChrIssueSnapshot,
    ChrKpiValue,
    ChrKpiWide,
    ChrComparisonResult,
    ChrKpiCorrelation,
    ChrAiInsight,
    ChrEmailDraft,
    ChrReportArtifact,
    ChrMLAnalytics,
    # Raw daily data layer (additive — must survive container restarts)
    ChrClinicConfig,
    ChrRawDailyOperations,
    ChrRawSchedulerProductivity,
    ChrRawNurseUtilization,
    ChrRawStaffingMetrics,
    ChrRawServiceDistribution,
    ChrRawServiceTotals,
    ChrRawTimeBlockDistribution,
    ChrRawDataSummary,
)


def init_db():
    """
    Initialize database.
    Uses CREATE TABLE IF NOT EXISTS semantics via Base.metadata.create_all,
    so raw daily data and historical KPIs survive container restarts.
    """
    engine = init_sessionmaker()
    Base.metadata.create_all(bind=engine)
    print("✅ Database ready (create_all — existing tables preserved):")
    print("   - chr_issue_snapshot              (raw GitHub issues)")
    print("   - chr_kpi_value                   (normalized KPI storage)")
    print("   - chr_kpi_wide                    (wide format — location/month)")
    print("   - chr_comparison_result           (MoM, vs company, vs Onco)")
    print("   - chr_kpi_correlation             (KPI relationships)")
    print("   - chr_ai_insight                  (AI-generated insights)")
    print("   - chr_email_draft                 (email drafts for CTO)")
    print("   - chr_report_artifact             (generated files)")
    print("   - chr_ml_analytics                (Isolation Forest + ARIMA)")
    print("   - chr_clinic_config               (per-clinic chair/hour config)")
    print("   - chr_raw_daily_operations        (daily delay/overtime/util × service)")
    print("   - chr_raw_scheduler_productivity  (per-scheduler E/A/M counts)")
    print("   - chr_raw_nurse_utilization       (daily nurse util %)")
    print("   - chr_raw_staffing_metrics        (daily chairs/RN, patients)")
    print("   - chr_raw_service_distribution    (MD + Tx + Inj coordination)")
    print("   - chr_raw_service_totals          (daily service counts × type)")
    print("   - chr_raw_time_block_distribution (fractional scheduling by time block)")
    print("   - chr_raw_data_summary            (weekly/monthly rollup narratives)")
    return engine
