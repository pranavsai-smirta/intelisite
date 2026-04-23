"""
Demo Practice injector -- creates a masked clone of HOGONC for sales demos.

Called only from json_exporter.export_json() after HOGONC.json is built.
Never touches the database or the real HOGONC payload in-place.
"""
import copy
import logging
from typing import Dict, List

log = logging.getLogger(__name__)

DEMO_CODE = "DEMO"
DEMO_DISPLAY_NAME = "Demo Practice"
KEEP_LOCATIONS = 4

# Rows that are network/benchmark aggregates, not real clinic locations.
_NON_CLINIC = {
    'global avg', 'global average', 'network avg', 'network average',
    'onco avg', 'onco average', 'oncosmart avg', 'oncosmart average',
    'company avg', 'company average', 'all clinics',
    'onco', 'total', 'grand total', 'overall',
}


def _sorted_clinic_locs(payload: Dict) -> List[str]:
    """
    Return sorted, unique real-clinic location names drawn from the most recent
    month's ioptimize rows in *payload*.  Benchmark/aggregate rows are excluded.
    Returns at most KEEP_LOCATIONS names.
    """
    months = payload.get("meta", {}).get("months_available", [])
    if not months:
        return []
    latest = months[-1]
    iopt_rows = payload.get("months", {}).get(latest, {}).get("ioptimize", [])

    seen: List[str] = []
    for row in iopt_rows:
        loc = row.get("location", "")
        if loc.strip().lower() not in _NON_CLINIC and loc not in seen:
            seen.append(loc)

    seen.sort()
    return seen[:KEEP_LOCATIONS]


def _scrub(text: str, rename: Dict[str, str], original_client: str) -> str:
    """
    Replace every real location name and the original client code in *text*
    with their demo-safe aliases.  Replacements are applied longest-first so
    that no partial match clobbers a longer name.
    """
    # Sort by descending length to avoid partial-match collisions
    for original in sorted(rename, key=len, reverse=True):
        text = text.replace(original, rename[original])
    text = text.replace(original_client, DEMO_DISPLAY_NAME)
    return text


def _scrub_insights(month_data: Dict, rename: Dict[str, str], original_client: str) -> None:
    """Scrub all free-text AI insight strings inside *month_data* in-place."""
    insights = month_data.get("ai_insights", {})
    for key, val in insights.items():
        if isinstance(val, str):
            insights[key] = _scrub(val, rename, original_client)
        elif isinstance(val, list):
            insights[key] = [
                _scrub(item, rename, original_client) if isinstance(item, str) else item
                for item in val
            ]


def inject_demo_practice(hogonc_payload: Dict, session=None) -> Dict:
    """
    Return a deep copy of *hogonc_payload* transformed into a 'Demo Practice'
    client with four anonymised locations.

    Transformations:
      - meta.client_code         ->  DEMO
      - Locations kept           ->  first KEEP_LOCATIONS names (alphabetical sort)
      - Location names           ->  Clinic 1, Clinic 2, Clinic 3, Clinic 4
      - AI insights prose        ->  all real location names + client code replaced
      - Benchmark rows           ->  kept verbatim (Company Avg, Onco, etc.)
      - All KPI values/scores    ->  unchanged

    Returns the transformed dict; the original is never mutated.
    """
    demo = copy.deepcopy(hogonc_payload)

    original_locs = _sorted_clinic_locs(hogonc_payload)
    if not original_locs:
        log.warning("demo_injector: no clinic locations found in HOGONC payload -- DEMO will be empty")
        return demo

    original_client = hogonc_payload.get("meta", {}).get("client_code", "HOGONC")
    rename: Dict[str, str] = {loc: f"Clinic {i + 1}" for i, loc in enumerate(original_locs)}
    keep_set = set(original_locs)

    # meta
    demo["meta"]["client_code"] = DEMO_CODE

    # per-month tables + AI insights
    for month_data in demo.get("months", {}).values():
        for table_key in ("ioptimize", "iassign"):
            kept = []
            for row in month_data.get(table_key, []):
                loc = row.get("location", "")
                if loc.strip().lower() in _NON_CLINIC:
                    kept.append(row)          # benchmark rows pass through unchanged
                elif loc in keep_set:
                    row["location"] = rename[loc]
                    kept.append(row)
                # else: 5th+ clinic location -- dropped
            month_data[table_key] = kept

        _scrub_insights(month_data, rename, original_client)

    # chatbot_context historical series
    hist = demo.get("chatbot_context", {}).get("historical_kpis", [])
    demo["chatbot_context"]["historical_kpis"] = [
        {**entry, "location": rename[entry["location"]]}
        for entry in hist
        if entry.get("location") in keep_set
    ]

    # raw_data_context: pull directly from DEMO's own ingested rows (already Clinic 1-4)
    # HOGONC has no raw rows, so we bypass the HOGONC-scrub path for this field only.
    if session is not None:
        from app.engine.json_exporter import _raw_data_context  # local import avoids circular dep
        demo["chatbot_context"]["raw_data_context"] = _raw_data_context(session, DEMO_CODE)
    else:
        demo["chatbot_context"]["raw_data_context"] = {"monthly_summaries": [], "weekly_summaries": []}

    log.info(
        "demo_injector: DEMO payload ready -- %d locations: %s",
        len(rename),
        ", ".join(rename.values()),
    )
    return demo
