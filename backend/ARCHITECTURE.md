# CHR Automation - God-Tier Architecture

## Design Principles

### 1. **Database Design: Normalized Perfection**
- Each KPI value = ONE ROW (fully normalized)
- Supports both averages AND medians
- Distinguishes between clinics, Company Avg, and Onco rows
- Complete audit trail (every value traceable to source)
- Optimized indexes for fast queries

### 2. **Intelligence Layer: AI-Powered Narrative Selection**
The system computes ALL possible comparisons and correlations:
- MoM changes (for both avg and median)
- vs Company Average
- vs Global Baseline (Onco)
- KPI correlations (which KPIs move together?)

**AI then decides:**
- Which metric to show (avg vs median) - whichever tells better story
- Which comparisons to highlight
- Which KPIs to correlate
- What narrative to construct

**Goal:** Always show client that your products are helping them improve

### 3. **Workflow**
```
GitHub Issues (Source of Truth)
    ↓
[Parse & Extract] - Multi-column parser extracts ALL KPIs with medians
    ↓
[Store in DB] - Normalized storage
    ↓
[Compute ALL Comparisons] - Engine calculates everything
    ↓
[Find Correlations] - Which KPIs moved together?
    ↓
[AI Intelligence Layer] - Decides what to show/hide
    ↓
[Generate Insights] - Create narrative
    ↓
[Create Charts] - Visualizations
    ↓
[Compose Emails] - One draft per client
    ↓
[Send to CTO] - All drafts in CTO's inbox for review
    ↓
[CTO Reviews] - Manually sends to client COOs
```

## Database Tables

### Core Data Tables

**chr_issue_snapshot**
- Raw GitHub issue storage
- Immutable audit trail
- One row per issue

**chr_kpi_value**
- ONE ROW PER KPI VALUE
- Stores: client, location, source, kpi_name, avg, median
- row_type: clinic/company_avg/onco
- Fully indexed for fast queries

**chr_comparison_result**
- Stores ALL computed comparisons
- MoM (avg and median)
- vs Company Avg
- vs Global (Onco)
- Outlier flags
- Percentile rankings

**chr_kpi_correlation**
- Stores KPI pair relationships
- Identifies positive/negative correlations
- Flags which ones to highlight

### Intelligence & Output Tables

**chr_ai_insight**
- AI-generated insights per client
- Executive summaries
- Highlights
- Recommendations
- Concerns

**chr_email_draft**
- One draft per client per month
- HTML + plain text
- Status tracking (generated/reviewed/sent)

**chr_report_artifact**
- All generated files
- Charts, JSONs, PDFs
- SHA256 hashes for integrity

## Why This Design is "God-Tier"

### ✅ Flexibility
- Easy to add new KPIs (just add rows, no schema change)
- Easy to add new clients (just add rows)
- Easy to query any metric

### ✅ Performance
- Optimized indexes on all query paths
- Efficient storage (no duplicate data)
- Fast aggregations

### ✅ Intelligence
- AI has access to ALL data
- Can make smart decisions about what to show
- Can find unexpected patterns

### ✅ Auditability
- Every value traceable to source GitHub issue
- Complete history preserved
- SHA256 hashes on all artifacts

### ✅ Maintainability
- Clean separation of concerns
- Well-documented
- Easy to test

## Future Extensions (Easy to Add)

- Web dashboard (reads from same DB)
- Real-time alerting (monitors comparisons table)
- Predictive analytics (uses historical data)
- Custom client dashboards
- API for external tools
