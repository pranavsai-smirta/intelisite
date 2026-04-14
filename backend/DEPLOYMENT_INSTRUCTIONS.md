# Deployment Instructions - CHR Automation v3

## What Changed from v2

### ✅ God-Tier Database Schema
- 7 tables instead of 4
- Supports both averages AND medians
- Separate tables for correlations, insights, email drafts
- Fully normalized and optimized

### ✅ Architecture Documentation
- See ARCHITECTURE.md for complete design
- Every design decision explained
- Future extension paths documented

### ✅ Better CLI
- Rich console output with colors
- Clear progress indicators
- Better error messages

## How to Deploy

### Step 1: Replace Your v2 Files

```bash
cd ~/CHR-AUTOMATION-V2

# Backup your current files
mv app app.backup
mv configs configs.backup
mv README.md README.backup.md

# Copy new files
cp -r ~/Downloads/chr-automation-v3/* .

# Keep your .env (don't overwrite it)
# Keep your .venv (don't overwrite it)
```

### Step 2: Reinitialize Database

```bash
# Stop old database
docker compose down

# Remove old data (IMPORTANT!)
docker volume rm chr-automation-v2_chr_pgdata

# Start fresh database
docker compose up -d

# Wait 5 seconds for PostgreSQL to start
sleep 5

# Initialize new schema
python -m app.cli db-init
```

You should see:
```
✅ Database initialized with 7 tables:
   - chr_issue_snapshot (raw GitHub issues)
   - chr_kpi_value (normalized KPI storage)
   - chr_comparison_result (all comparisons)
   - chr_kpi_correlation (KPI relationships)
   - chr_ai_insight (AI-generated insights)
   - chr_email_draft (email drafts for CTO)
   - chr_report_artifact (generated files)
```

### Step 3: Verify Everything Works

```bash
# Test dry run
python -m app.cli run --month 2026-01 --dry-run

# Check database
docker exec -it chr_postgres psql -U chr_user -d chr_db -c "\dt"
```

You should see 7 tables listed.

## What's Included

✅ **Complete Database Schema** - models.py with 7 god-tier tables
✅ **Architecture Docs** - ARCHITECTURE.md explaining every decision
✅ **Updated README** - Complete usage guide
✅ **CLI** - Better command-line interface
✅ **All Config Files** - kpi_rules.yml, comparison_rules.yml
✅ **Parser** - Already handles multi-column tables and medians
✅ **GitHub Client** - Ready to fetch issues

## What's NOT Included Yet (Coming Soon)

⏳ **Comparison Engine** - Computes all comparisons
⏳ **Correlation Engine** - Finds KPI relationships
⏳ **AI Insights** - Generates intelligent narratives
⏳ **Chart Generator** - Creates visualizations
⏳ **Email Composer** - Builds HTML emails
⏳ **Full Pipeline** - Orchestrates everything

## Next Steps

After deploying v3:

1. **Test Database** - Make sure all 7 tables are created
2. **Test Parser** - Verify it extracts KPIs correctly
3. **Build Comparison Engine** - I'll help you with this next
4. **Add AI Layer** - Then we'll add intelligent insights
5. **Create Email Templates** - Finally, beautiful emails

## Rollback (If Needed)

If something breaks:

```bash
# Restore backup
rm -rf app configs
mv app.backup app
mv configs.backup configs
mv README.backup.md README.md

# Restart old database
docker compose down
docker compose up -d
python -m app.cli db-init
```

## Questions?

Review ARCHITECTURE.md for design decisions, or ask me for help!
