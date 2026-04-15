#!/usr/bin/env bash
# =============================================================================
# certbot-bootstrap.sh — One-time SSL certificate setup for a fresh server.
#
# Usage:
#   DOMAIN=app.example.com EMAIL=admin@example.com bash scripts/certbot-bootstrap.sh
#
# Prerequisites:
#   - docker compose up -d must already be running (nginx-proxy at minimum)
#   - DNS A record for $DOMAIN must point to this server's public IP
#   - Ports 80 and 443 must be open in the EC2 security group
# =============================================================================
set -euo pipefail

# ─── Validate required env vars ───────────────────────────────────────────────
if [[ -z "${DOMAIN:-}" ]]; then
  echo "ERROR: DOMAIN environment variable is required." >&2
  echo "Usage: DOMAIN=app.example.com EMAIL=admin@example.com bash scripts/certbot-bootstrap.sh" >&2
  exit 1
fi
if [[ -z "${EMAIL:-}" ]]; then
  echo "ERROR: EMAIL environment variable is required." >&2
  echo "Usage: DOMAIN=app.example.com EMAIL=admin@example.com bash scripts/certbot-bootstrap.sh" >&2
  exit 1
fi

# ─── Navigate to project root ─────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/.."

echo ""
echo "======================================================================"
echo "  certbot-bootstrap.sh — Provisioning SSL for: ${DOMAIN}"
echo "======================================================================"
echo ""

# ─── Step 1: Ensure nginx-proxy is up ────────────────────────────────────────
echo "==> [1/5] Ensuring nginx-proxy is running..."
docker compose up -d nginx-proxy
sleep 2

# ─── Step 2: Swap in HTTP-only config (ACME challenge mode) ───────────────────
echo "==> [2/5] Swapping in HTTP-only config for ACME challenge..."
# Save the HTTPS template before overwriting
cp nginx/conf.d/default.conf nginx/conf.d/default.conf.tpl
cp nginx/default-http-only.conf nginx/conf.d/default.conf
docker compose exec nginx-proxy nginx -s reload
echo "    nginx reloaded — now serving ACME challenge on port 80."

# ─── Step 3: Run certbot ──────────────────────────────────────────────────────
echo "==> [3/5] Running certbot (webroot challenge for ${DOMAIN})..."
docker compose run --rm certbot certonly \
  --webroot \
  -w /var/www/certbot \
  -d "${DOMAIN}" \
  --email "${EMAIL}" \
  --agree-tos \
  --non-interactive
echo "    Certificate issued successfully."

# ─── Step 4: Restore HTTPS config with domain substituted ────────────────────
echo "==> [4/5] Restoring full HTTPS config (substituting domain)..."
# envsubst '${DOMAIN}' only replaces ${DOMAIN}, leaving nginx vars ($host etc.) intact
envsubst '${DOMAIN}' < nginx/conf.d/default.conf.tpl > nginx/conf.d/default.conf
rm -f nginx/conf.d/default.conf.tpl
docker compose exec nginx-proxy nginx -s reload
echo "    nginx reloaded — HTTPS is now active."

# ─── Step 5: Summary ─────────────────────────────────────────────────────────
echo ""
echo "==> [5/5] SUCCESS"
echo "======================================================================"
echo "  Site live at : https://${DOMAIN}"
echo "  Certs stored : ./certbot/conf/live/${DOMAIN}/"
echo ""
echo "  Set up auto-renewal by adding this line to crontab (crontab -e):"
echo "    0 3 * * * cd $(pwd) && bash scripts/certbot-renew.sh"
echo "======================================================================"
echo ""
