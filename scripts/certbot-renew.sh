#!/usr/bin/env bash
# =============================================================================
# certbot-renew.sh — Automated Let's Encrypt certificate renewal.
#
# Run by cron — recommended schedule (3 AM daily):
#   0 3 * * * cd /home/ubuntu/intellisite && bash scripts/certbot-renew.sh
#
# Output is appended to /var/log/certbot-renew.log with timestamps.
# Ensure the running user has write permission to that file, or adjust LOG_FILE.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/.."

LOG_FILE="/var/log/certbot-renew.log"
TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"

{
  echo "──────────────────────────────────────────────────────────────────────"
  echo "[${TIMESTAMP}] certbot-renew.sh started"
  echo "──────────────────────────────────────────────────────────────────────"

  echo "[${TIMESTAMP}] Running: docker compose run --rm certbot renew"
  docker compose run --rm certbot renew

  echo "[${TIMESTAMP}] Reloading nginx..."
  docker compose exec nginx-proxy nginx -s reload

  echo "[${TIMESTAMP}] Renewal cycle complete."
} 2>&1 | tee -a "${LOG_FILE}"
