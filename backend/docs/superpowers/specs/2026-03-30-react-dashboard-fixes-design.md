# React Dashboard — 4 Critical Fixes Design Spec

**Date:** 2026-03-30  
**Status:** Approved  
**Repo:** ncs-chr-webpage (React frontend)

---

## Fix 1 — KpiTable: Pin Average Rows at Bottom with Distinct Styling

### Problem
`ioptimize` and `iassign` arrays include `"Company Avg"` and `"Global Avg"` rows mixed in with clinic location rows. They can appear in any position, which looks wrong on a C-suite dashboard.

### Solution
Inside the `Table` component in `KpiTable.jsx`:
1. Detect avg rows by matching `row.location` against `["company avg", "global avg"]` (case-insensitive).
2. Sort the non-avg rows alphabetically by `location`.
3. Append avg rows at the end in the order: Company Avg first, then Global Avg.
4. Render avg rows with a distinct row style: `bg-slate-100 border-t-2 border-slate-300` with `font-semibold` text on the location cell — visually separating them as summary rows.

### Label Fix
All truncated KPI labels get their full names:
- `"Sched\u00a0Compliance"` → `"Scheduler\u00a0Compliance"` (KpiTable column header)
- `"Sched Compliance"` label in `ClinicView.jsx` KpiCard → `"Scheduler Compliance"`
- `'Sched Compliance'` in `TrendChart.jsx` KPI_CONFIG → `"Scheduler Compliance"`
- `"Chair\u00a0Util"` → `"Chair\u00a0Utilization"` in KpiTable (same class of truncation)
- `"Chair Util"` → `"Chair Utilization"` in TrendChart KPI_CONFIG

---

## Fix 2 — Navigation: Prominent Back Breadcrumb in ClinicView

### Problem
The NavBar has a small `← All Clinics` link but it blends into the navigation bar. There is no prominent breadcrumb in the clinic hero area that makes it obvious to a CTO how to return to the master view.

### Solution
Add a breadcrumb link at the **very top of the hero section** in `ClinicView.jsx`, above the "Clinic Detail" label. It sits flush left, uses `Link` from react-router-dom pointing to `"/"`.

Style: `text-slate-400 hover:text-teal-400 text-sm transition-colors flex items-center gap-1.5` with a `←` arrow character. Text: `Back to CTO Dashboard`.

The NavBar's existing `← All Clinics` link is kept as-is (no changes to `NavBar.jsx`).

---

## Fix 3 — DB Investigation: Scheduler Compliance Trend Data

### Investigation Plan
1. Run psql against the local Docker PostgreSQL (`chr_postgres`) to query `chr_kpi_wide` for all months of `scheduler_compliance` data.
2. If data exists in DB for 6+ months but JSON only shows 2 months → bug in `json_exporter.py` historical extraction.
3. If DB itself only has 2 months of `scheduler_compliance` → bug in mock data generation or pipeline parsing.
4. Fix the appropriate layer, re-run `json_exporter.py` to regenerate JSON files, push updated files to `ncs-chr-webpage/public/data/`.

### Expected Outcome
After fix, all trend charts should show 6 months of data consistently. The investigation findings will be reported inline during implementation.

---

## Fix 4 — ChatBot: Premium Glassmorphism UI

### Visual Design
The drawer gets a deep glassmorphism treatment. All colors use translucency and blur rather than solid dark backgrounds.

**Drawer container:**
- `background: rgba(15, 23, 42, 0.75)` (translucent slate-900)
- `backdrop-filter: blur(20px) saturate(180%)`
- Border: `1px solid rgba(255, 255, 255, 0.10)` with a subtle top-edge glow
- Box shadow: layered — ambient dark shadow + inner teal glow highlight

**Header:** Gradient left edge accent (2px teal-to-transparent bar), "OncoSmart AI" in teal, status dot (pulsing green) indicating "online".

**Message bubbles:**
- User: `background: linear-gradient(135deg, #0D9488, #0F766E)` (teal gradient), white text, `rounded-2xl rounded-tr-sm`
- AI: `background: rgba(255,255,255,0.06)` glass, `border: 1px solid rgba(255,255,255,0.08)`, slate-100 text, `rounded-2xl rounded-tl-sm`

**Typing indicator:** 3 animated dots with staggered CSS bounce animation. Shown as an AI bubble when `streaming === true` and accumulated content is empty.

**FAQ / Suggested Question Pills:** 3 pill buttons rendered above the input field (only when `messages.length === 0`):
1. "Analyze scheduler compliance"
2. "Which location is underperforming?"
3. "Summarize recent trends"

Pills: `bg-white/5 hover:bg-white/10 border border-white/10 text-slate-300 text-xs rounded-full px-3 py-1.5 transition-colors`. Clicking a pill calls `handleSend` with that text as the message (sets input and triggers send immediately).

**Input area:** Slightly elevated glass input `bg-white/5 border border-white/10 focus:border-teal-500/50`, placeholder `"Ask about this clinic…"`. Send button: teal gradient with glow on hover.

**Floating button:** Teal ring glow on hover, smooth scale transform.

---

## Files Changed

| File | Repo | Change |
|------|------|--------|
| `src/components/KpiTable.jsx` | ncs-chr-webpage | Pin avg rows, alphabetize, distinct styling, fix labels |
| `src/components/TrendChart.jsx` | ncs-chr-webpage | Fix "Sched Compliance" → "Scheduler Compliance", "Chair Util" → "Chair Utilization" |
| `src/pages/ClinicView.jsx` | ncs-chr-webpage | Add back breadcrumb, fix "Sched Compliance" → "Scheduler Compliance" in KpiCard label |
| `src/components/ChatBot.jsx` | ncs-chr-webpage | Full glassmorphism UI overhaul with FAQ pills and typing indicator |
| `app/engine/json_exporter.py` | CHR-AUTOMATION-V2 | Fix if historical data bug found here |
| `ncs-chr-webpage/public/data/*.json` | ncs-chr-webpage | Re-generated if pipeline fix needed |

## Out of Scope
- No column sorting UI added to KpiTable
- No changes to NavBar.jsx
- No changes to CTOMasterView.jsx
- No new routes or pages
