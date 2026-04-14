#!/bin/bash
# CHR Automation — DB Recovery Script
# Run this any time you get a DB connection error
# Usage: bash scripts/recover_db.sh

set -e

echo "🔄 CHR DB Recovery Starting..."

# Step 1: Make sure Docker is running
echo ""
echo "Step 1/4: Checking Docker..."
if ! docker info > /dev/null 2>&1; then
    echo "  Docker not running. Opening Docker Desktop..."
    open -a Docker
    echo "  Waiting 30 seconds for Docker to start..."
    sleep 30
else
    echo "  ✓ Docker is running"
fi

# Step 2: Start postgres container
echo ""
echo "Step 2/4: Starting postgres container..."
docker-compose up -d
sleep 5

# Step 3: Ensure chr_user exists (safe to run multiple times)
echo ""
echo "Step 3/4: Ensuring chr_user exists in postgres..."
docker exec chr_postgres psql -U postgres -c "
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'chr_user') THEN
        CREATE USER chr_user WITH PASSWORD 'chr_password';
        RAISE NOTICE 'chr_user created';
    ELSE
        RAISE NOTICE 'chr_user already exists';
    END IF;
END
\$\$;
GRANT ALL PRIVILEGES ON DATABASE chr_db TO chr_user;
GRANT ALL ON SCHEMA public TO chr_user;
"

# Step 4: Init DB schema
echo ""
echo "Step 4/4: Initializing DB schema..."
python -m app.cli db-init

echo ""
echo "✅ Recovery complete! You can now run:"
echo "   python -m app.cli run --month 2026-01 --skip-github"
echo "   python -m app.cli import-history"