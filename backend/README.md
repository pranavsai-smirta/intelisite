# CHR Automation System - God-Tier Edition

**Automated Clinic Health Report generation with AI-powered insights**

## What This System Does

1. **Extracts** KPI data from GitHub Issues (17+ clients, monthly)
2. **Analyzes** performance (MoM trends, benchmarks, correlations)
3. **Generates** intelligent insights using AI
4. **Creates** beautiful email drafts (one per client)
5. **Delivers** to CTO for review before sending to client COOs

## Quick Start

### Prerequisites
- Python 3.11+
- Docker (for PostgreSQL)
- GitHub Personal Access Token
- Anthropic API Key (for AI insights)

### Installation

```bash
# 1. Navigate to project
cd CHR-AUTOMATION-V2

# 2. Activate virtual environment
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and add your tokens

# 5. Start database
docker compose up -d

# 6. Initialize database
python -m app.cli db-init

# 7. Run pipeline
python -m app.cli run --month 2026-01
```

## Architecture

This system uses a **normalized database design** (god-tier) with an **AI intelligence layer** that decides what to highlight in each email.

### Key Design Decisions

**✅ Normalized Storage**
- Each KPI value = one database row
- Supports both averages AND medians
- Easy to query, analyze, and extend

**✅ AI-Powered Narrative**
- Computes ALL possible comparisons
- AI decides which ones to show
- Always highlights improvements
- Carefully handles deteriorations

**✅ Complete Audit Trail**
- Every number traceable to source
- Immutable raw data storage
- SHA256 hashes on all artifacts

See [ARCHITECTURE.md](./ARCHITECTURE.md) for detailed design documentation.

## Database Schema

### Core Tables
- `chr_issue_snapshot` - Raw GitHub issues
- `chr_kpi_value` - Normalized KPI storage
- `chr_comparison_result` - All computed comparisons
- `chr_kpi_correlation` - KPI relationships

### Intelligence Tables
- `chr_ai_insight` - AI-generated insights
- `chr_email_draft` - Email drafts for CTO review
- `chr_report_artifact` - Generated files/charts

## Usage

### Process Current Month
```bash
python -m app.cli run
```

### Process Specific Month
```bash
python -m app.cli run --month 2026-01
```

### Import Historical Data
```bash
python -m app.cli import-history --start-month 2025-07 --end-month 2025-12
```

### Generate Reports Only (no GitHub fetch)
```bash
python -m app.cli generate-reports --month 2026-01
```

## Project Structure

```
CHR-AUTOMATION-V2/
├── app/
│   ├── db/
│   │   ├── models.py          # God-tier database schema
│   │   ├── session.py         # DB connection
│   │   └── init_db.py         # Table creation
│   ├── parsers/
│   │   ├── markdown_parser.py # Extract tables from markdown
│   │   └── kpi_parser.py      # Parse KPIs with medians
│   ├── engine/
│   │   ├── comparison_engine.py   # Compute all comparisons
│   │   └── correlation_engine.py  # Find KPI relationships
│   ├── ai/
│   │   ├── insight_generator.py   # AI-powered insights
│   │   └── narrative_selector.py  # Choose what to highlight
│   ├── services/
│   │   ├── github_client.py   # Fetch GitHub issues
│   │   ├── chart_generator.py # Create visualizations
│   │   ├── email_composer.py  # Build email drafts
│   │   └── pipeline.py        # Orchestrate everything
│   └── cli.py                 # Command-line interface
├── configs/
│   ├── kpi_rules.yml         # KPI definitions
│   └── comparison_rules.yml   # Analysis rules
├── artifacts/                 # Generated files
├── docker-compose.yml         # PostgreSQL setup
├── requirements.txt           # Dependencies
├── .env.example              # Configuration template
├── README.md                 # This file
└── ARCHITECTURE.md           # Detailed design docs
```

## Configuration

### Environment Variables (.env)

```bash
# Database
DATABASE_URL=postgresql://chr_user:chr_pass@localhost:5432/chr_db

# GitHub
GITHUB_TOKEN=ghp_your_token_here
GITHUB_REPO=Smirta-Innovations/Oncosmart-Dashboard
CHR_LABEL=Clinic health report

# AI
ANTHROPIC_API_KEY=sk-ant-your_key_here

# Clients
EXPECTED_CLIENTS=HOGONC,PCI,VCI,TNO,CHCWM,MBPCC,PCC,NCS,CCBD,NMCC,LOA

# Output
ARTIFACTS_DIR=./artifacts
```

### KPI Rules (configs/kpi_rules.yml)

Defines:
- KPI canonical names
- Display names
- Units
- Whether higher or lower is better

### Comparison Rules (configs/comparison_rules.yml)

Defines:
- Outlier detection thresholds
- Significance levels
- Correlation detection rules

## Development

### Run Tests
```bash
pytest tests/
```

### Check Database
```bash
# Connect to PostgreSQL
docker exec -it chr_postgres psql -U chr_user -d chr_db

# Query KPI values
SELECT * FROM chr_kpi_value WHERE client_name = 'HOGONC' LIMIT 10;
```

### View Logs
```bash
tail -f artifacts/2026-01/latest/pipeline.log
```

## Troubleshooting

### Database Connection Issues
```bash
# Check if PostgreSQL is running
docker ps | grep chr_postgres

# Restart database
docker compose restart
```

### GitHub Rate Limits
```bash
# Check rate limit
curl -H "Authorization: token YOUR_TOKEN" https://api.github.com/rate_limit
```

### Parse Failures
Check the `parse_status` column in `chr_kpi_value` table and review `parse_notes` for details.

## Support

For issues or questions, contact the development team.

## License

Proprietary - Smirta Innovations Inc.
