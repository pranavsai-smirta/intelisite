# React Migration Design Spec
**Date:** 2026-03-30
**Project:** CHR Automation — ncs-chr-webpage React Migration
**Status:** Approved

---

## Overview

Migrate the 14 static HTML oncology dashboards at `intern-smirta/ncs-chr-webpage` to a production-grade React SPA hosted on GitHub Pages. The Python pipeline is **unchanged internally** — the only pipeline addition is a new `json_exporter.py` step that writes one JSON file per client. The React app is completely separate from the pipeline.

Two independent deliverables:
1. **Pipeline JSON export** — Step 7 added to existing pipeline: writes structured JSON files to `ncs-chr-webpage/public/data/`
2. **React dashboard app** — Vite + React SPA with CTO master view, per-clinic views, and an AI chatbot

---

## Architecture: Approach A (Selected)

**Vite + React + HashRouter**, deployed to GitHub Pages via GitHub Actions.

- `HashRouter` handles SPA routing on static hosting without any 404 tricks
- URLs: `/#/` (CTO master), `/#/clinic/:clientCode` (per-clinic)
- Pipeline pushes JSON to `main` → GitHub Actions builds React → Pages updates within ~60s
- The 14 existing static HTML files remain untouched during development; deleted only when React build goes live

---

## Repo Structure (`ncs-chr-webpage`)

```
ncs-chr-webpage/
├── public/
│   └── data/
│       ├── manifest.json          ← pipeline writes (index of all clients)
│       ├── HOGONC.json            ← pipeline writes (one per client)
│       ├── PCI.json
│       └── ... (14 files total)
├── src/
│   ├── main.jsx
│   ├── App.jsx                    ← HashRouter + route definitions
│   ├── pages/
│   │   ├── CTOMasterView.jsx      ← reads manifest.json, all-clinic grid
│   │   └── ClinicView.jsx         ← reads {CLIENT}.json, month-selectable
│   ├── components/
│   │   ├── KpiCard.jsx            ← hero metric card (dark glass style)
│   │   ├── ScoreBadge.jsx         ← composite 0-100 score badge
│   │   ├── KpiTable.jsx           ← iOptimize / iAssign data tables
│   │   ├── TrendChart.jsx         ← 6-month sparkline (Recharts AreaChart)
│   │   ├── InsightPanel.jsx       ← AI narrative prose display
│   │   ├── ChatBot.jsx            ← floating side-drawer chatbot
│   │   └── NavBar.jsx
│   ├── hooks/
│   │   ├── useManifest.js         ← fetches + caches manifest.json
│   │   └── useClinicData.js       ← fetches + caches {CLIENT}.json
│   └── lib/
│       └── anthropic.js           ← Anthropic browser API, key from VITE_ANTHROPIC_API_KEY
├── .env.local                     ← VITE_ANTHROPIC_API_KEY (never committed)
├── .github/
│   └── workflows/
│       └── deploy.yml             ← build + deploy to gh-pages on push to main
├── vite.config.js                 ← base: '/ncs-chr-webpage/'
└── package.json
```

---

## JSON Schema

### `manifest.json`
Written by pipeline after every run. Used by CTOMasterView.

```json
{
  "generated_at": "2026-03-01T00:00:00Z",
  "latest_month": "2026-02",
  "clients": [
    {
      "code": "HOGONC",
      "display_name": "HOGONC",
      "latest_month": "2026-02",
      "location_count": 4,
      "composite_score": 74,
      "mom_trend": "up"
    }
  ],
  "network_summary": {
    "avg_composite_score": 68,
    "top_performer": "NCS",
    "most_improved": "CCBD"
  }
}
```

### `{CLIENT}.json`
One file per client. Written by pipeline after every run.

```json
{
  "meta": {
    "client_code": "HOGONC",
    "generated_at": "2026-03-01T00:00:00Z",
    "months_available": ["2025-09","2025-10","2025-11","2025-12","2026-01","2026-02"]
  },
  "months": {
    "2026-02": {
      "composite_score": 74,
      "ioptimize": [
        {
          "location": "BCC MO",
          "scheduler_compliance_avg": 46.99,
          "scheduler_compliance_median": null,
          "avg_delay_avg": 9.81,
          "avg_delay_median": 8.64,
          "chair_utilization_avg": 82.1,
          "chair_utilization_median": null,
          "tx_past_close_avg": 3.2,
          "tx_mins_past_close_avg": 12.5,
          "mom_deltas": {
            "scheduler_compliance": 2.1,
            "avg_delay": -0.4,
            "chair_utilization": 1.2
          },
          "vs_company": {
            "scheduler_compliance": "below",
            "avg_delay": "above",
            "chair_utilization": "above"
          },
          "outlier_flags": ["avg_delay"]
        }
      ],
      "iassign": [
        {
          "location": "BCC MO",
          "iassign_utilization_avg": 88.5,
          "patients_per_nurse_avg": 4.2,
          "chairs_per_nurse_avg": 3.1,
          "nurse_utilization_avg": 71.0,
          "mom_deltas": {},
          "vs_company": {},
          "outlier_flags": []
        }
      ],
      "benchmarks": {
        "company_avg": {
          "scheduler_compliance_avg": 61.2,
          "avg_delay_avg": 7.8,
          "chair_utilization_avg": 79.0
        },
        "onco_benchmark": {
          "scheduler_compliance_avg": 75.0,
          "avg_delay_avg": 6.0,
          "chair_utilization_avg": 85.0
        }
      },
      "ai_insights": {
        "executive_summary": "...",
        "highlights": ["..."],
        "concerns": ["..."],
        "recommendations": ["..."]
      }
    }
  },
  "chatbot_context": {
    "kpi_definitions": {
      "scheduler_compliance": {
        "label": "Scheduler Compliance",
        "unit": "%",
        "higher_is_better": true,
        "explanation": "Percentage of appointments scheduled following iOptimize recommendations. Higher is better. Company avg ~61%, Onco benchmark 75%."
      },
      "avg_delay": {
        "label": "Avg Delay",
        "unit": "mins",
        "higher_is_better": false,
        "explanation": "Average daily schedule delay in minutes. Lower is better."
      }
    },
    "data_notes": "Company Avg rows represent the network average across all clinics for that client. Onco rows are global oncology benchmarks. Rows named 'Global Avg', 'Network Avg', 'Total', 'Overall' are aggregates — not individual clinic locations.",
    "historical_kpis": [
      {
        "month": "2025-09",
        "location": "BCC MO",
        "scheduler_compliance_avg": 44.1,
        "avg_delay_avg": 10.2,
        "chair_utilization_avg": 80.5,
        "composite_score": 68
      }
    ]
  }
}
```

---

## Routes

| URL | Component | Data source |
|-----|-----------|-------------|
| `/#/` | `CTOMasterView` | `manifest.json` |
| `/#/clinic/:clientCode` | `ClinicView` | `{clientCode}.json` |

`ClinicView` defaults to `meta.months_available` last entry. Month selector is local state — no route change on month switch.

**Clients:** AON, CCBD, CCI, CHC, HOGONC, LOA, MOASD, NCS, NMCC, NWMS, NYOH, PCC, PCI, TNO (14 total)

---

## CTO Master View

- **Header:** "OncoSmart Network Dashboard — {month}" + last-updated timestamp from `manifest.json`
- **Network summary strip:** 4 hero `KpiCard` components — avg composite score, top performer, most improved, count of clinics below threshold
- **Clinic grid:** 14 cards, responsive grid. Each card: client code, `ScoreBadge` (color-coded 0–100), location count, top 2 KPI highlights, MoM trend arrow. Click navigates to `/#/clinic/{code}`
- **Controls:** Sort by composite score (asc/desc), filter by trend (all / improving / declining)

---

## Clinic View

- **Header:** Client name, selected month, location count, composite score as large hero badge
- **Month selector:** Dropdown populated from `meta.months_available` (up to 6 entries)
- **AI Insights panel:** Executive summary + collapsible highlights/concerns/recommendations
- **iOptimize table:** All locations × KPIs, color-coded cells (green = above company avg, red = below), MoM delta arrows with prior-month value in parentheses, outlier badge
- **iAssign table:** Same treatment
- **Trend charts:** 6-month `AreaChart` (Recharts) per key KPI — scheduler compliance, avg delay, chair utilization, composite score
- **Chatbot:** Floating button bottom-right, expands to side drawer

---

## Chatbot

- **Placement:** Floating action button (bottom-right), expands to 400px side drawer
- **Context:** On open, reads `chatbot_context` from the already-loaded clinic JSON (no extra fetch). On CTO master view, loads and merges all 14 `historical_kpis` arrays
- **System prompt:** Constructed from `kpi_definitions` + `data_notes` + `historical_kpis` + current month's full KPI data for the active clinic
- **API:** `fetch` POST to `https://api.anthropic.com/v1/messages`, header `x-api-key: ${import.meta.env.VITE_ANTHROPIC_API_KEY}`, `anthropic-dangerous-direct-browser-access: true`
- **Model:** `claude-haiku-4-5-20251001` (fast, low-cost; configurable via env var)
- **Streaming:** SSE (`stream: true`) for real-time token output
- **State:** `useState` array of `{role, content}` messages, persisted for the browser session only
- **API key exposure:** Accepted — CTO is the only user at this stage. Key stored in `.env.local`, excluded from git via `.gitignore`

---

## Design System

| Token | Value | Usage |
|-------|-------|-------|
| Primary text | `#0F172A` | Headings, body |
| Secondary text | `#64748B` | Labels, captions |
| Accent (teal) | `#0D9488` | Links, positive delta, active states |
| Danger (red) | `#DC2626` | Below-benchmark, declining trend |
| Warning (amber) | `#D97706` | Near-threshold |
| Base bg | `#FFFFFF` | Page, cards |
| Surface bg | `#F8FAFC` | Table rows, section fills |
| Border | `#E2E8F0` | Card borders, dividers |
| Hero bg | `#0F172A` | KpiCard, ScoreBadge, ChatBot header |
| Hero glow | `rgba(13,148,136,0.15)` | Subtle teal glow on dark hero components |

**Typography:** Inter (via Fontsource `@fontsource/inter`)
**Styling:** Tailwind CSS v3
**Charts:** Recharts
**No component library** — custom components for full design control
**Special characters in JS:** All non-ASCII must be unicode escapes. Em dash: `"\u2014"`, middle dot: `"\u00b7"`, arrows: `"\u2191"` / `"\u2193"`. `ensure_ascii=True` in all pipeline JSON output.

---

## Pipeline Change (Step 7 — New)

**File:** `app/engine/json_exporter.py`

- Called at the end of `orchestrator.py` after Step 6 (email generation)
- Reads `chr_kpi_wide`, `chr_comparison_result`, `chr_ai_insight` for the run month
- Reads 5 prior months of history from DB for `chatbot_context.historical_kpis`
- Assembles and writes `{CLIENT}.json` for each client processed
- Assembles and writes `manifest.json` (network summary across all clients)
- Output path configured via `JSON_EXPORT_PATH` env var (default: `../ncs-chr-webpage/public/data/`)
- Pipeline does **not** run git commands — operator pushes manually or CI handles it
- The existing `email_engine.py` is **not modified**

---

## GitHub Actions Deployment

```yaml
# .github/workflows/deploy.yml (in ncs-chr-webpage)
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 20 }
      - run: npm ci
      - run: npm run build
        env:
          VITE_ANTHROPIC_API_KEY: ${{ secrets.VITE_ANTHROPIC_API_KEY }}
      - uses: peaceiris/actions-gh-pages@v4
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: ./dist
```

`vite.config.js` sets `base: '/ncs-chr-webpage/'`. API key stored as a GitHub Actions secret — not in the repo, but baked into the built JS bundle (accepted tradeoff per decision above).

---

## Migration Path

1. Build React app in a `react-dev` branch of `ncs-chr-webpage`
2. Old static HTML files remain on `main` and stay live throughout development
3. Once React app passes review: merge to `main`, delete old HTML files
4. GitHub Actions deploys new build — zero downtime transition

---

## Out of Scope (Phase 1)

- Per-clinic authentication (deferred — URL-based access is accepted)
- Live database connection for chatbot (deferred — Phase 2)
- PDF export of dashboards
- Email sending from the React app
- Multi-language support
