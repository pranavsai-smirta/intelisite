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
)

def init_db():
    """Initialize database - drop and recreate all 9 tables with latest schema"""
    engine = init_sessionmaker()
    # Drop all tables first so schema changes always take effect
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    print("✅ Database initialized with 9 tables:")
    print("   - chr_issue_snapshot     (raw GitHub issues)")
    print("   - chr_kpi_value          (normalized KPI storage - audit trail)")
    print("   - chr_kpi_wide           (wide format - one row per location/month)")
    print("   - chr_comparison_result  (MoM, vs company, vs Onco comparisons)")
    print("   - chr_kpi_correlation    (KPI relationships)")
    print("   - chr_ai_insight         (AI-generated insights)")
    print("   - chr_email_draft        (email drafts for CTO)")
    print("   - chr_report_artifact    (generated files)")
    print("   - chr_ml_analytics       (Isolation Forest + ARIMA + lag correlations)")
    return engine