#!/bin/bash
# CHR Automation — Quick Start
# Run this at the start of every session
# Usage: bash scripts/start.sh

echo "🚀 CHR Automation Starting..."

# Ensure Docker is up
if ! docker info > /dev/null 2>&1; then
    echo "Opening Docker Desktop..."
    open -a Docker
    echo "Waiting 30 seconds..."
    sleep 30
fi

# Start postgres if not running
docker-compose up -d
echo "✓ Postgres running"

echo ""
echo "Ready! Run your pipeline:"
echo "  python -m app.cli run --month 2026-01"
echo "  python -m app.cli import-history"