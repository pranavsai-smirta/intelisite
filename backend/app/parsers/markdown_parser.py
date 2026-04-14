"""
CHR Issue Markdown Parser — handles all 13 real client formats.

Real format: One single pipe table per issue.
- Row 1: "iOptimize stats" label in cell [0]
- Row 4: Actual column headers ("Clinic", "Scheduler Complaince", ...)
- Data rows follow
- Later: "iAssign Stats" label row (bolded or not)
- Then iAssign column headers and data rows

Edge cases handled:
- iAssign label with or without bold: iAssign Stats vs **iAssign Stats**
- Company Avg variations: Company Avg / Company / company avg
- Bolded clinic rows: **CCI_drive** treated as clinic, not special row
- Trailing junk cells: |   |   |   | at end of rows
- Plain text outside table (AON note) — ignored automatically
"""
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class ParsedTable:
    headers: List[str]
    rows: List[List[str]]


def clean_cell(cell: str) -> str:
    """Remove bold markdown (**text**), strip whitespace."""
    return re.sub(r'\*\*(.+?)\*\*', r'\1', cell).strip()


def is_separator_row(line: str) -> bool:
    """Check if line is |---|---|---|"""
    stripped = line.strip()
    if not (stripped.startswith('|') and stripped.endswith('|')):
        return False
    inner = stripped.strip('|')
    return bool(re.match(r'^[\s\-:|]+$', inner))


def split_pipe_row(line: str) -> List[str]:
    """Split pipe row into cleaned cells, strip trailing empty cells."""
    cells = [clean_cell(c) for c in line.strip().strip('|').split('|')]
    # Remove trailing empty cells (junk like |   |   |)
    while cells and cells[-1] == '':
        cells.pop()
    return cells


def is_empty_row(cells: List[str]) -> bool:
    return all(c == '' for c in cells)


def is_clinic_header(cells: List[str]) -> bool:
    """The actual column header row starts with 'Clinic'."""
    return len(cells) > 1 and cells[0].lower().strip() == 'clinic'


def cell_has_keyword(cells: List[str], keyword: str) -> bool:
    return any(keyword.lower() in c.lower() for c in cells)


def is_company_avg_row(location: str) -> bool:
    """
    Handles all variations:
      Company Avg, Company, company avg, **Company Avg**
    Rule: contains 'company' (case-insensitive)
    But NOT if it also contains a slash or pod name (clinic names won't have 'company')
    """
    return 'company' in location.lower().strip()


def is_onco_row(location: str) -> bool:
    return 'onco' in location.lower().strip()


def parse_chr_issue_body(body: str) -> Tuple[Optional['ParsedTable'], Optional['ParsedTable']]:
    """
    Parse a CHR issue body into (iOptimize table, iAssign table).
    Handles all real-world format variations across all 13 clients.
    """
    lines = body.split('\n')

    # Step 1: Collect all valid pipe rows, skip separators
    all_rows = []
    for line in lines:
        stripped = line.strip()
        # Must start and end with pipe
        if not (stripped.startswith('|') and stripped.endswith('|')):
            continue
        if is_separator_row(line):
            continue
        cells = split_pipe_row(line)
        if cells:
            all_rows.append(cells)

    if not all_rows:
        return None, None

    # Step 2: Find the two "Clinic" header rows
    # First one = iOptimize headers, second one = iAssign headers
    # Each appears after their respective section label

    iopt_label_idx  = None
    iasg_label_idx  = None
    iopt_header_idx = None
    iasg_header_idx = None

    for i, cells in enumerate(all_rows):
        # Find iOptimize label row
        if iopt_label_idx is None and cell_has_keyword(cells, 'iOptimize'):
            iopt_label_idx = i

        # Find iAssign label row (after iOptimize)
        if iasg_label_idx is None and iopt_label_idx is not None and i > iopt_label_idx:
            if cell_has_keyword(cells, 'iAssign'):
                iasg_label_idx = i

        # First "Clinic" header after iOptimize label
        if iopt_header_idx is None and iopt_label_idx is not None and i > iopt_label_idx:
            if is_clinic_header(cells):
                iopt_header_idx = i

        # First "Clinic" header after iAssign label
        if iasg_header_idx is None and iasg_label_idx is not None and i > iasg_label_idx:
            if is_clinic_header(cells):
                iasg_header_idx = i

    iopt_table = None
    iasg_table = None

    # Step 3: Extract iOptimize data rows
    if iopt_header_idx is not None:
        headers = all_rows[iopt_header_idx]
        rows = []
        end_idx = iasg_label_idx if iasg_label_idx is not None else len(all_rows)
        for cells in all_rows[iopt_header_idx + 1 : end_idx]:
            if is_empty_row(cells):
                continue
            if is_clinic_header(cells):
                continue
            rows.append(cells)
        iopt_table = ParsedTable(headers=headers, rows=rows)

    # Step 4: Extract iAssign data rows
    if iasg_header_idx is not None:
        headers = all_rows[iasg_header_idx]
        rows = []
        for cells in all_rows[iasg_header_idx + 1:]:
            if is_empty_row(cells):
                continue
            if is_clinic_header(cells):
                continue
            rows.append(cells)
        iasg_table = ParsedTable(headers=headers, rows=rows)

    return iopt_table, iasg_table


def extract_section_table(markdown: str, section_keyword: str) -> Tuple[Optional[ParsedTable], str]:
    """Backward-compatible wrapper used by kpi_parser."""
    iopt_table, iasg_table = parse_chr_issue_body(markdown)

    if 'ioptimize' in section_keyword.lower():
        return (iopt_table, "ok") if iopt_table else (None, "missing_section:iOptimize")

    if 'iassign' in section_keyword.lower():
        return (iasg_table, "ok") if iasg_table else (None, "missing_section:iAssign")

    return None, f"unknown_section:{section_keyword}"