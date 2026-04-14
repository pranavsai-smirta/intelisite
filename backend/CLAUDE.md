# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CHR Automation is a Python pipeline that extracts KPI data from GitHub issues for 11+ oncology clinic clients, analyzes performance with statistical methods, and generates AI-powered HTML email reports for CTO review.

## Commands

**Setup:**
```bash
docker compose up -d          # Start PostgreSQL 16
python -m app.cli db-init     # Initialize schema
```

**Run the pipeline:**
```bash
python -m app.cli run                     # Process previous month
python -m app.cli run --month 2026-01     # Process specific month
python -m app.cli run --skip-github       # Use existing GitHub data (skip fetch)
python -m app.cli import-history          # Backfill all historical issues
```

**Testing/smoke tests:**
```bash
python test_fetcher.py --parse-only       # Test parser on synthetic data
python test_fetcher.py --month 2026-01    # Smoke test fetch + parse
python test_fetcher.py --month 2026-01 --client HOGONC  # Single client
pytest tests/                             # Run test suite
```

**Database inspection:**
```bash
docker exec -it chr_postgres psql -U chr_user -d chr_db
# Useful queries:
# SELECT COUNT(*) FROM chr_kpi_value;
# SELECT * FROM chr_kpi_wide WHERE client_name = 'HOGONC' LIMIT 5;
```

## Architecture

The system follows a **6-step orchestrated pipeline** (`app/core/orchestrator.py`) with a layered database design.

### Pipeline Steps

```
Step 1 (github_fetcher.py)      → Fetch GitHub issues labeled "Clinic health report"
Step 2 (markdown_parser.py,     → Parse pipe tables, extract KPI values,
        kpi_parser.py)            handle avg(median) format like "9.81(8.64)"
Step 3 (comparison_engine.py)   → Compute MoM deltas, vs company avg, vs Onco benchmarks,
                                  z-scores, percentiles, volatility, composite scores
Step 4 (insight_engine.py)      → Detect KPI correlations, classify as causal/spurious
Step 5 (insight_engine.py)      → Call Claude API to generate flowing prose narratives
Step 6 (email_engine.py)        → Build HTML emails with embedded base64 JPEG charts
```

### Database Layers

The schema (`app/db/models.py`) has 4 logical layers:

1. **Raw audit trail:** `chr_issue_snapshot` (immutable GitHub issues), `chr_kpi_value` (one row per KPI per location per month, with raw text preserved)
2. **Wide format for queries:** `chr_kpi_wide` (one row per location/month, all KPIs as columns — primary table for analysis)
3. **Pre-computed analytics:** `chr_comparison_result` (MoM, benchmarks, z-scores, trends), `chr_kpi_correlation`
4. **AI outputs:** `chr_ai_insight`, `chr_email_draft`, `chr_report_artifact`

### Configuration

- `configs/kpi_rules.yml` — 9 KPI definitions with column aliases (handles real-world typos like "Scheduler Complaince"), units, and directionality
- `configs/comparison_rules.yml` — Outlier detection thresholds, significance levels
- `.env` — Runtime credentials and settings (see `.env.example`)

### Key Implementation Details

**Parsing robustness:** The parser handles real-world markdown variations: `**bold**` formatting, malformed parentheses in `avg(median)` values, case-insensitive special row detection (Company Avg, Onco, Global Avg rows are excluded from client narratives).

**Statistical methods:** Outlier detection uses MAD (Median Absolute Deviation) at z-threshold 3.5 (more robust than standard z-score). Trend analysis uses linear regression with R². Composite scores are weighted 0–100.

**Email charts:** Horizontal bar charts embedded as base64 JPEG (quality=75). For clients with >10 locations, shows Top 5 + Bottom 5. DPI adjusted dynamically for large clinic sets.

**AI safety:** The insight engine post-validates Claude's output to reject false causal language. Every statistic in AI text must cite its benchmark. Causation relationships are pre-classified in `CAUSAL_MAP` before being sent to the AI.

### Clients Tracked

11 expected clients: HOGONC, PCI, TNO, CHCWM, MBPCC, PCC, NCS, VCI, CCBD, NMCC, LOA

### Output

HTML email files saved to `./artifacts/` with naming `YYYY-MM_CLIENTNAME_email.html`. Also stored in `chr_email_draft` table with review workflow fields (`reviewed_by`, `sent_at`).

## CRITICAL — JS Dashboard Rules
ALL special characters in JavaScript files must be unicode escapes. NEVER write raw em dash — or any non-ASCII character directly in .js files or js_template.js.
Use these variables instead:
- Em dash: var EM="\u2014"
- Middle dot: var MID="\u00b7"
- Up arrow: var UP="\u2191"
- Down arrow: var DN="\u2193"
- Right arrow: var RT="\u2192"
- Smart apostrophe: var AP="\u2019"
- json.dumps(..., ensure_ascii=True) ALWAYS

Violation = blank page on GitHub Pages. This burned 3 sessions.

## Non-Clinic Names — NEVER treat as locations
Filter these out everywhere:
global avg, global average, network avg, network average, onco avg, onco average, company avg, company average, all clinics, onco, total, grand total, overall

## Dashboard Generator
Generator files: gen.py + js_template.js + css_template.css
Run: python3 gen.py
Output goes to: /mnt/user-data/outputs/

## GitHub Pages
Repo: https://github.com/intern-smirta/ncs-chr-webpage
User: intern-smirta
Pages on main branch, / (root) folder
14 live dashboards, one per client

## Future Architecture Decision (LOCKED)
Dashboard frontend is being migrated from plain HTML to React.
Data layer: pipeline outputs JSON files (one per client) to ncs-chr-webpage/data/
UI layer: React app reads JSON files, never touched by pipeline
Hosting: GitHub Pages via React build
Chatbot: will be added to React app, reads from JSON files
Multi-user: CTO gets master view, each clinic gets their own view
