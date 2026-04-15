# IntelliSite

Oncology clinic KPI analytics platform — React + FastAPI + PostgreSQL, containerised with Docker Compose and served via Nginx + Let's Encrypt.

---

## Phase 2 — SSL Setup

### Prerequisites

Before running the bootstrap script, confirm:

1. **EC2 Security Group** — inbound rules open for TCP 80 and TCP 443 from `0.0.0.0/0`.
2. **DNS** — an A record for your domain points to the EC2 instance's public IP.
3. **Stack is running** — `docker compose up -d` has been executed at least once so the `nginx-proxy` container is up.

---

### First-time certificate bootstrap

Run this **once** on a fresh server after DNS has propagated:

```bash
DOMAIN=app.example.com EMAIL=admin@example.com bash scripts/certbot-bootstrap.sh
```

What the script does (automated):

| Step | Action |
|------|--------|
| 1 | Ensures `nginx-proxy` is running |
| 2 | Swaps in the HTTP-only config so certbot can reach `/.well-known/acme-challenge/` |
| 3 | Runs `certbot certonly --webroot` inside a temporary container |
| 4 | Substitutes `${DOMAIN}` in the production nginx config and reloads nginx |
| 5 | Prints the live URL and renewal crontab line |

Certificates are written to `./certbot/conf/` on the host and mounted read-only into both the `nginx-proxy` and `certbot` containers.

---

### Verify certificates are working

```bash
# Check certificate details
docker compose run --rm certbot certificates

# Test HTTPS response
curl -I https://app.example.com

# Confirm redirect from HTTP → HTTPS
curl -I http://app.example.com
# Expect: HTTP/1.1 301 Moved Permanently
```

---

### Automated renewal

Certbot certificates expire every 90 days. The `certbot` service in `docker-compose.yml` runs a renewal loop internally (checks every 12 hours, renews when < 30 days remain).

For belt-and-suspenders coverage, also add the shell script to cron:

```bash
crontab -e
```

Add this line (runs at 3 AM daily, logs to `/var/log/certbot-renew.log`):

```
0 3 * * * cd /home/ubuntu/intellisite && bash scripts/certbot-renew.sh
```

Verify the log after the first scheduled run:

```bash
tail -f /var/log/certbot-renew.log
```
