"""GitHub API client for fetching CHR issues"""
import os
import re
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple
import requests

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Discrepancy tracking — everything the parser notices gets recorded here
# so it can be printed as a full report at the end of import-history.
# ---------------------------------------------------------------------------
@dataclass
class ParseDiscrepancy:
    issue_number: int
    issue_title: str
    discrepancy_type: str   # e.g. "NO_BRACKETS", "TYPO_CLIENT", "WEIRD_SPACING", etc.
    detail: str             # human-readable explanation
    how_handled: str        # what the parser did about it


_discrepancies: List[ParseDiscrepancy] = []


def get_discrepancies() -> List[ParseDiscrepancy]:
    return list(_discrepancies)


def clear_discrepancies():
    _discrepancies.clear()


def _record(issue_number, issue_title, dtype, detail, how_handled):
    _discrepancies.append(ParseDiscrepancy(
        issue_number=issue_number,
        issue_title=issue_title,
        discrepancy_type=dtype,
        detail=detail,
        how_handled=how_handled,
    ))


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class GitHubIssue:
    number: int
    title: str
    url: str
    html_url: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    body: str
    labels: List[str]


# ---------------------------------------------------------------------------
# Title parser — handles every real-world format seen in the repo
# ---------------------------------------------------------------------------

# Known client codes so we can detect obvious typos / close matches
KNOWN_CLIENTS = {
    "AON", "CCBD", "CCI", "CHC", "HOGONC", "LOA", "MBPCC", "MOASD",
    "NCS", "NMCC", "NWMS", "NYOH", "NYCBS", "PCC", "PCI", "TNO", "VCI",
}

# Month aliases that strptime won't handle on its own
MONTH_ALIASES = {
    "sept": "sep",
    "janu": "jan",
    "febr": "feb",
    "marc": "mar",
    "apri": "apr",
    "june": "jun",
    "july": "jul",
    "augu": "aug",
    "octo": "oct",
    "nove": "nov",
    "dece": "dec",
}


def _normalize_month_text(raw: str) -> str:
    """
    Turn any spacing / dash / alias variant into 'Mon YYYY' that strptime
    can parse.

    Examples handled:
        January-2026        → January 2026
        Jan-2026            → Jan 2026
        Jan - 2026          → Jan 2026
        September - 2025    → September 2025
        Sept 2025           → Sep 2025
        Nov -2025           → Nov 2025
        July  2025          → July 2025  (double space)
    """
    # Replace dash (with optional surrounding spaces) → single space
    s = re.sub(r'\s*-\s*', ' ', raw).strip()
    # Collapse multiple spaces
    s = re.sub(r'\s+', ' ', s)
    # Apply known abbreviation aliases (case-insensitive prefix match)
    parts = s.split(' ', 1)
    if parts:
        month_word = parts[0].lower()
        # Try prefix aliases (e.g. "sept" → "sep")
        for alias, replacement in MONTH_ALIASES.items():
            if month_word == alias:
                parts[0] = replacement
                break
        s = ' '.join(parts)
    return s


def parse_issue_title(title: str, issue_number: int = 0) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Parse a CHR issue title into (client_code, month_text, YYYY-MM).

    Handles:
      Standard (post-Jan 2026):
        [NYOH] Clinic health report for [January-2026]

      Pre-standard variants:
        [CCI]  Clinic health report for [September - 2025]
        [LOA]  Clinic health report for  [July-2025]          ← double space
        [VCI]  Clinic health report for [Sept 2025]           ← Sept alias
        CCI Clinic health report for [July-2025]              ← missing brackets on client
        VCI Clinic health report for  [July-2025]             ← missing brackets + double space
        [CCI-Pods] ...                                        ← sub-location suffix
        [CCI(Tx only)] ...                                    ← sub-location suffix

    Returns (client_name, month_text, month_yyyymm).
    If unparseable, returns (None, None, None) and logs a discrepancy.
    """
    raw = title.strip()

    # ── Shared fragment: "Clinic health report(s) for" — the 's' is optional
    #   because many older issues use the plural form:
    #   "Clinic Health Reports for October 2025"
    _CHR_CORE = r'Clinic\s+health\s+reports?\s+for'

    # ── Pattern A: both client and month in brackets (standard + most variants)
    #   [NYOH] Clinic health report for [January-2026]
    #   [NYOH] Clinic Health Reports for [January-2026]
    pat_both = re.match(
        rf'^\[([^\]]+)\]\s+{_CHR_CORE}\s+\[([^\]]+)\]',
        raw, re.IGNORECASE
    )

    # ── Pattern B: client WITHOUT brackets, month WITH brackets (old Jul 2025)
    #   CCI Clinic health report for [July-2025]
    #   CCI Clinic Health Reports for [July-2025]
    pat_no_client_bracket = re.match(
        rf'^([A-Z][A-Z0-9\-]+)\s+{_CHR_CORE}\s+\[([^\]]+)\]',
        raw, re.IGNORECASE
    )

    # ── Pattern C: client WITH brackets, month WITHOUT brackets (Feb–Jun 2025)
    #   [TNO] Clinic health report for June 2025
    #   [LOA] Clinic Health Reports for February 2025
    pat_no_month_bracket = re.match(
        rf'^\[([^\]]+)\]\s+{_CHR_CORE}\s+([A-Za-z]+\s+\d{{4}})\s*$',
        raw, re.IGNORECASE
    )

    # ── Pattern D: neither has brackets (edge case)
    #   CCI Clinic health report for July 2025
    #   CCI Clinic Health Reports for July 2025
    pat_no_brackets = re.match(
        rf'^([A-Z][A-Z0-9\-]+)\s+{_CHR_CORE}\s+([A-Za-z]+\s+\d{{4}})\s*$',
        raw, re.IGNORECASE
    )

    if pat_both:
        client_raw = pat_both.group(1).strip()
        month_raw  = pat_both.group(2).strip()
    elif pat_no_client_bracket:
        client_raw = pat_no_client_bracket.group(1).strip()
        month_raw  = pat_no_client_bracket.group(2).strip()
        _record(issue_number, raw,
                "NO_CLIENT_BRACKETS",
                f"Client code '{client_raw}' has no square brackets",
                f"Parsed client as '{client_raw}' anyway")
    elif pat_no_month_bracket:
        client_raw = pat_no_month_bracket.group(1).strip()
        month_raw  = pat_no_month_bracket.group(2).strip()
        _record(issue_number, raw,
                "NO_MONTH_BRACKETS",
                f"Month '{month_raw}' has no square brackets (old pre-Jul 2025 format)",
                f"Parsed month as '{month_raw}' anyway")
    elif pat_no_brackets:
        client_raw = pat_no_brackets.group(1).strip()
        month_raw  = pat_no_brackets.group(2).strip()
        _record(issue_number, raw,
                "NO_CLIENT_BRACKETS",
                f"Neither client nor month has brackets (very old format)",
                f"Parsed client as '{client_raw}', month as '{month_raw}'")
    else:
        _record(issue_number, raw,
                "UNRECOGNISED_FORMAT",
                "Title does not match any known CHR pattern",
                "Skipped — cannot extract client or month")
        log.warning(f"Could not parse title: '{raw}'")
        return None, None, None

    # ── Clean up client code
    # Strip sub-location suffixes like "-Pods" or "(Tx only)"
    client_clean = re.sub(r'[-\s]*\(.*\)$', '', client_raw).strip()
    client_clean = re.sub(r'-\w+$', '', client_clean).strip()  # e.g. CCI-Pods → CCI

    if client_raw != client_clean:
        _record(issue_number, raw,
                "SUB_LOCATION_SUFFIX",
                f"Client code '{client_raw}' has a sub-location suffix",
                f"Normalised to '{client_clean}'")

    if client_clean.upper() not in KNOWN_CLIENTS:
        # Could be a new client — record but don't reject
        _record(issue_number, raw,
                "UNKNOWN_CLIENT_CODE",
                f"'{client_clean}' is not in the known client list",
                "Imported as-is — may be a new client or a typo")

    # ── Parse month
    normalized = _normalize_month_text(month_raw)

    if normalized != month_raw:
        _record(issue_number, raw,
                "MONTH_FORMAT_VARIANT",
                f"Month text '{month_raw}' needed normalisation",
                f"Normalised to '{normalized}' before parsing")

    for fmt in ("%b %Y", "%B %Y"):
        try:
            dt = datetime.strptime(normalized, fmt)
            return client_clean.upper(), month_raw, dt.strftime("%Y-%m")
        except ValueError:
            continue

    _record(issue_number, raw,
            "UNPARSEABLE_MONTH",
            f"Could not parse '{month_raw}' (normalised: '{normalized}') as a month",
            "Skipped — no YYYY-MM produced")
    log.warning(f"Could not parse month from title: '{raw}'")
    return client_clean.upper() if client_clean else None, month_raw, None


# ---------------------------------------------------------------------------
# GitHub API client
# ---------------------------------------------------------------------------

class GitHubAPIClient:
    def __init__(self, token: str, repo: str):
        self.token = token
        self.repo = repo
        self.base_url = "https://api.github.com"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "chr-automation",
        })

    # ── REST /issues endpoint — handles ALL issues including very old ones
    def list_issues_by_label(self, label: str) -> List[dict]:
        """
        Fetch every issue (open + closed) with the given label using the
        REST /repos/{owner}/{repo}/issues endpoint with proper pagination.

        Unlike the Search API this has no 1000-result cap and correctly
        follows Link headers across as many pages as needed.
        """
        url = f"{self.base_url}/repos/{self.repo}/issues"
        all_items = []
        page = 1

        while True:
            params = {
                "state":    "all",
                "labels":   label,
                "per_page": 100,
                "page":     page,
            }
            response = self.session.get(url, params=params, timeout=30)

            # Respect rate limits gracefully
            if response.status_code == 403 and "rate limit" in response.text.lower():
                reset = int(response.headers.get("X-RateLimit-Reset", time.time() + 60))
                wait = max(reset - int(time.time()), 5)
                log.warning(f"Rate limited — waiting {wait}s")
                time.sleep(wait)
                continue

            response.raise_for_status()
            items = response.json()

            if not items:
                break

            all_items.extend(items)
            log.info(f"  Fetched page {page} — {len(items)} issues (total so far: {len(all_items)})")

            # Check Link header for next page
            link_header = response.headers.get("Link", "")
            if 'rel="next"' not in link_header:
                break

            page += 1
            time.sleep(0.25)  # be polite to the API

        return all_items

    # ── Keep the old search method for the monthly run (fast, recent only)
    def search_issues_by_label(self, label: str) -> List[dict]:
        """Search API — fast but capped at 1000 results. Use for monthly runs."""
        query = f'repo:{self.repo} is:issue label:"{label}"'
        url = f"{self.base_url}/search/issues"
        all_items = []
        page = 1

        while True:
            params = {"q": query, "per_page": 100, "page": page}
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            items = data.get("items", [])
            all_items.extend(items)
            if len(items) < 100:
                break
            page += 1
            time.sleep(0.25)

        return all_items

    def get_issue(self, issue_number: int) -> GitHubIssue:
        url = f"{self.base_url}/repos/{self.repo}/issues/{issue_number}"
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()

        def parse_dt(s):
            if not s:
                return None
            return datetime.fromisoformat(s.replace("Z", "+00:00"))

        return GitHubIssue(
            number=data["number"],
            title=data["title"],
            url=data["url"],
            html_url=data["html_url"],
            created_at=parse_dt(data.get("created_at")),
            updated_at=parse_dt(data.get("updated_at")),
            body=data.get("body") or "",
            labels=[l["name"] for l in data.get("labels", [])],
        )


# ---------------------------------------------------------------------------
# Convenience function for monthly runs (unchanged interface)
# ---------------------------------------------------------------------------

def fetch_chr_issues_for_month(repo: str, label: str, target_month: str) -> List[GitHubIssue]:
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set in .env")

    client = GitHubAPIClient(token, repo)
    search_results = client.search_issues_by_label(label)
    log.info(f"Found {len(search_results)} total issues with label '{label}'")

    matching = []
    for item in search_results:
        client_name, month_text, month_yyyymm = parse_issue_title(item["title"], item.get("number", 0))
        if month_yyyymm == target_month:
            issue = client.get_issue(item["number"])
            matching.append(issue)
            log.info(f"  ✓ #{issue.number}: {client_name} ({month_text})")

    log.info(f"Matched {len(matching)} issues for {target_month}")
    return matching