#!/bin/bash
set -e

# WARNING: db-init DROPS AND RECREATES ALL TABLES.
# Once real production data exists, replace the line below with:
# python -m alembic upgrade head
echo "Initializing database schema..."
python -m app.cli db-init
echo "Schema ready. Starting API server..."

exec uvicorn app.api.chat:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 4 \
  --log-level info
