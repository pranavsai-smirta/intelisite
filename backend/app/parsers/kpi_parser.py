"""
KPI Parser — extracts and cleans all KPI values from CHR issue bodies.

God-level v2 changes:
  - resolve_row_type now catches "Global Avg" and all non-clinic names
  - Location names cleaned: underscores → spaces at parse time
  - Expanded special_rows from kpi_rules.yml

Handles every value format found across all 13 real clients:
  "61.06%"              → avg=61.06, median=None, unit=%
  "9.81(8.64)"          → avg=9.81,  median=8.64,  unit=None
  "57.54%(60.35%)"      → avg=57.54, median=60.35, unit=%
  "59%(includes SI)"    → avg=59.0,  median=None,  unit=%, note saved
  "80.32%102.04%)"      → avg=80.32, median=102.04, unit=% (missing open paren)
  "65.81%64.39%)"       → avg=65.81, median=64.39,  unit=% (missing open paren)
  "36.08(34.56%)"       → avg=36.08, median=34.56,  unit=%
  "0.69(0.00"           → avg=0.69,  median=0.0  (missing close paren)
  "3.7(3033)"           → avg=3.7,   median=None, warning (suspicious typo)
  "6(0)"                → avg=6.0,   median=0.0
  "0.05(0)"             → avg=0.05,  median=0.0
  "0(0.00)"             → avg=0.0,   median=0.0
  "100%"                → avg=100.0, median=None
  "0.925(0.00)"         → avg=0.925, median=0.0
"""
import re
import os
import yaml
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict
from .markdown_parser import (
    extract_section_table, ParsedTable,
    is_company_avg_row, is_onco_row
)

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Additional non-clinic location names that should be treated
# as special aggregate rows. Matched case-insensitively.
# ─────────────────────────────────────────────────────────────
_EXTRA_NON_CLINIC = {
    'global avg', 'global average', 'network avg', 'network average',
    'onco avg', 'onco average', 'oncosmart avg', 'oncosmart average',
    'all clinics', 'total', 'grand total', 'overall',
}


@dataclass
class ParsedKpi:
    location_name:   str
    is_special_row:  bool
    row_type:        str            # "clinic", "company_avg", "onco"
    kpi_name:        str
    kpi_display_name: str
    value_raw:       str
    value_avg:       Optional[float]
    value_median:    Optional[float]
    value_unit:      Optional[str]
    parse_status:    str            # "ok", "warning", "failed"
    parse_notes:     Optional[str]


def load_kpi_rules(configs_dir: str = "./configs") -> dict:
    path = os.path.join(configs_dir, "kpi_rules.yml")
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def resolve_row_type(location_name: str) -> str:
    """
    Determine if a location name is a real clinic or a special aggregate row.
    Checks both the markdown_parser functions AND the expanded non-clinic list.
    """
    if is_company_avg_row(location_name):
        return "company_avg"
    if is_onco_row(location_name):
        return "onco"

    # Check expanded non-clinic list
    name_lower = location_name.strip().lower()
    if name_lower in _EXTRA_NON_CLINIC:
        # "Global Avg" is a network-wide benchmark — treat as Onco-equivalent
        if 'global' in name_lower:
            return "onco"
        return "company_avg"

    return "clinic"


def parse_value_with_median(
    value_raw: str
) -> Tuple[Optional[float], Optional[float], Optional[str], str, Optional[str]]:
    """
    Parse any cell value into (avg, median, unit, status, notes).
    Handles every format found across all 13 real clients.
    """
    raw = value_raw.strip()
    notes = None

    if not raw or raw.lower() in ('n/a', 'na', '-', ''):
        return None, None, None, "warning", "empty_or_na"

    # ── Step 1: Strip text annotations like "(includes SI)" ──────────
    text_ann = re.search(r'\(([^0-9.\-][^)]*)\)', raw)
    if text_ann:
        notes = f"annotation:{text_ann.group(0)}"
        raw = raw.replace(text_ann.group(0), '').strip()

    # ── Step 2: Detect unit ──────────────────────────────────────────
    unit = '%' if '%' in raw else None

    # ── Step 3: Normalize — remove %, commas ────────────────────────
    clean = raw.replace('%', '').replace(',', '').strip()

    # ── Step 4: Fix missing close paren: "0.69(0.00" → "0.69(0.00)" ─
    if '(' in clean and ')' not in clean:
        clean = clean + ')'

    # ── Step 5: Fix missing open paren ──────────────────────────────
    if ')' in clean and '(' not in clean:
        m = re.match(r'^(\d+\.\d+)(\d+\.?\d*\))$', clean)
        if m:
            clean = f'{m.group(1)}({m.group(2)}'
        else:
            m2 = re.match(r'^(\d+)(\d+\.\d+\))$', clean)
            if m2:
                clean = f'{m2.group(1)}({m2.group(2)}'

    # ── Step 6: Parse number(number) ────────────────────────────────
    m = re.match(r'^([\d.]+)\s*\(([\d.]+)\)$', clean)
    if m:
        try:
            avg    = float(m.group(1))
            median = float(m.group(2))
            if median > 999:
                return avg, None, unit, "warning", f"suspicious_median:{m.group(2)}"
            return avg, median, unit, "ok", notes
        except ValueError as e:
            return None, None, unit, "warning", f"parse_error:{e}"

    # ── Step 7: Single number ────────────────────────────────────────
    try:
        return float(clean), None, unit, "ok", notes
    except ValueError as e:
        return None, None, unit, "warning", f"parse_error:{e}|raw:{value_raw}"


def _normalize_for_matching(text: str) -> str:
    """
    Normalize a column header or alias for fuzzy matching.
    Strips punctuation, collapses whitespace, lowercases.
    """
    s = text.lower()
    s = re.sub(r'[()\[\]/]', ' ', s)
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _match_score(col_norm: str, alias_norm: str) -> int:
    """
    Return a match score between a normalized column and alias.
    Higher = better match. 0 = no match.
    """
    if not alias_norm:
        return 0

    if col_norm == alias_norm:
        return 3

    STOP = {'a', 'an', 'the', 'and', 'or', 'of', 'in', 'per', 'to'}
    alias_words = [w for w in alias_norm.split() if w not in STOP and len(w) > 1]
    col_words   = set(col_norm.split())

    if not alias_words:
        return 0

    matches = sum(1 for w in alias_words if w in col_words)
    ratio   = matches / len(alias_words)

    if ratio == 1.0:
        return 2
    if ratio >= 0.8:
        return 1
    return 0


def map_column_to_kpi(
    column_header: str,
    source_rules: dict
) -> Optional[Tuple[str, dict, str, str]]:
    """
    Map a raw column header to a canonical KPI using intelligent fuzzy matching.
    """
    col_norm = _normalize_for_matching(column_header)
    if not col_norm:
        return None

    best_score  = 0
    best_kpi    = None
    best_alias  = None
    best_mtype  = None

    for kpi_name, kpi_config in source_rules.get('kpis', {}).items():
        candidates = [kpi_config.get('display_name', '')] + kpi_config.get('aliases', [])
        for alias in candidates:
            if not alias:
                continue
            alias_norm = _normalize_for_matching(alias)
            score = _match_score(col_norm, alias_norm)
            if score > best_score:
                best_score = score
                best_kpi   = (kpi_name, kpi_config)
                best_alias = alias
                best_mtype = {3: "exact", 2: "word_exact", 1: "fuzzy_80pct"}[score]

    if best_score >= 1:
        return best_kpi[0], best_kpi[1], best_alias, best_mtype
    return None


def parse_table_to_kpis(
    table: ParsedTable,
    source_name: str,
    kpi_rules: dict
) -> List[ParsedKpi]:
    """Convert a ParsedTable into a flat list of ParsedKpi objects."""
    results = []

    if not table or not table.headers or len(table.headers) < 2:
        return results

    source_rules = kpi_rules.get('sources', {}).get(source_name, {})
    if not source_rules:
        log.warning(f"[{source_name}] No rules defined")
        return results

    # Map columns to KPIs
    kpi_columns = []
    for idx, header in enumerate(table.headers[1:], start=1):
        if not header.strip():
            continue
        mapped = map_column_to_kpi(header, source_rules)
        if mapped:
            kpi_name, kpi_config, matched_alias, match_type = mapped
            kpi_columns.append((idx, kpi_name, kpi_config, header))
            if match_type != "exact":
                log.info(
                    f"[{source_name}] Fuzzy match ({match_type}): "
                    f"\"{header[:50]}\" → \"{kpi_name}\" via alias \"{matched_alias}\""
                )
        else:
            log.warning(f"[{source_name}] Unmapped column: '{header[:60]}'")

    if not kpi_columns:
        log.warning(f"[{source_name}] No columns mapped to KPIs")
        return results

    # Parse each data row
    for row in table.rows:
        if not row:
            continue

        location_name = row[0].strip()
        if not location_name:
            continue

        row_type   = resolve_row_type(location_name)
        is_special = row_type in ("company_avg", "onco")

        for col_idx, kpi_name, kpi_config, original_header in kpi_columns:
            if col_idx >= len(row):
                results.append(ParsedKpi(
                    location_name=location_name,
                    is_special_row=is_special,
                    row_type=row_type,
                    kpi_name=kpi_name,
                    kpi_display_name=kpi_config.get('display_name', original_header),
                    value_raw='',
                    value_avg=None, value_median=None,
                    value_unit=kpi_config.get('unit'),
                    parse_status='warning',
                    parse_notes='missing_column'
                ))
                continue

            value_raw = row[col_idx].strip()
            avg, median, unit, status, notes = parse_value_with_median(value_raw)

            if not unit:
                unit = kpi_config.get('unit')

            results.append(ParsedKpi(
                location_name=location_name,
                is_special_row=is_special,
                row_type=row_type,
                kpi_name=kpi_name,
                kpi_display_name=kpi_config.get('display_name', original_header),
                value_raw=value_raw,
                value_avg=avg,
                value_median=median,
                value_unit=unit,
                parse_status=status,
                parse_notes=notes
            ))

    return results


def parse_issue_body(
    body_markdown: str,
    configs_dir: str = "./configs"
) -> Tuple[List[ParsedKpi], List[ParsedKpi], dict]:
    """
    Parse a full CHR issue body.
    Returns: (ioptimize_kpis, iassign_kpis, metadata)
    """
    kpi_rules = load_kpi_rules(configs_dir)
    metadata: Dict[str, str] = {}

    iopt_table, iopt_status = extract_section_table(body_markdown, "iOptimize")
    metadata['iOptimize'] = iopt_status
    iopt_kpis: List[ParsedKpi] = []
    if iopt_table and iopt_status == "ok":
        iopt_kpis = parse_table_to_kpis(iopt_table, "iOptimize", kpi_rules)

    iasg_table, iasg_status = extract_section_table(body_markdown, "iAssign")
    metadata['iAssign'] = iasg_status
    iasg_kpis: List[ParsedKpi] = []
    if iasg_table and iasg_status == "ok":
        iasg_kpis = parse_table_to_kpis(iasg_table, "iAssign", kpi_rules)

    return iopt_kpis, iasg_kpis, metadata