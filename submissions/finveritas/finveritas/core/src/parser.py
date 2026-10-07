"""
Bloomberg financial-statement PDF parser.

Responsibilities:
1. Extract header metadata (company name, currency, periods, statement type).
2. Parse the financial data table — mapping raw labels to canonical field keys
   and associating numeric values with their time periods.

The parser works on the *extracted* text/tables produced by ``extractor.py``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from .extractor import PDFContent
from .mapper import detect_statement_type, resolve_field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PeriodValue:
    """A single numeric observation tied to a reporting period."""

    period: str  # e.g. "2024-Q1", "2023-FY"
    value: float


@dataclass
class ParsedStatement:
    """Result of parsing one Bloomberg PDF."""

    source_file: str
    company: str = ""
    currency: str = "INR"
    statement_type: Optional[str] = None  # "IS" | "BS"
    periods: list[str] = field(default_factory=list)
    # canonical_field → list of (period, value)
    data: dict[str, list[PeriodValue]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------

_NUM_RE = re.compile(
    r"^[(\s]*"           # optional opening paren / spaces
    r"[-−]?\s*"          # optional negative sign (hyphen or en-dash)
    r"[\d,]+\.?\d*"      # digits with optional commas / decimal
    r"[)\s]*$"           # optional closing paren / spaces
)


def _parse_number(raw: str | None) -> Optional[float]:
    """Attempt to parse a numeric string.  Returns None on failure."""
    if raw is None:
        return None
    raw = raw.strip()
    if not raw or raw in ("—", "-", "–", "N/A", "n/a", "NA", ""):
        return None
    # Check that it looks numeric before doing heavy processing
    if not _NUM_RE.match(raw):
        return None
    negative = False
    # Parenthesised = negative in accounting notation
    if "(" in raw and ")" in raw:
        negative = True
    cleaned = raw.replace(",", "").replace("(", "").replace(")", "").replace(" ", "")
    # Handle en-dash / em-dash as minus
    cleaned = cleaned.replace("−", "-").replace("–", "-")
    try:
        val = float(cleaned)
        return -abs(val) if negative else val
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Period normalisation
# ---------------------------------------------------------------------------

# Matches patterns like "FY2024", "Q1 2024", "3M 2024", "12M 2023", "2024",
# "Mar-24", "Sep-2023", "1Q2024", "2QFY24", etc.
_PERIOD_RE = re.compile(
    r"""
    (?:
        (?:FY|fy)\s*(?P<fy_year>\d{2,4})                          # FY2024
      | (?P<q_prefix>[1-4])\s*Q\s*(?:FY)?\s*(?P<q_year1>\d{2,4})  # 1Q2024 / 1QFY24
      | Q(?P<quarter>[1-4])\s*(?:FY)?\s*(?P<q_year2>\d{2,4})      # Q1 2024
      | (?P<months>\d{1,2})M\s*(?P<m_year>\d{2,4})                # 3M 2024 / 12M 2023
      | (?P<mon_name>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)
        [-/\s]*(?P<mon_year>\d{2,4})                               # Mar-24
      | (?P<plain_year>(?:19|20)\d{2})                             # 2024
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

_MONTH_TO_Q = {
    "jan": 4, "feb": 4, "mar": 4,   # Indian FY: Q4 = Jan-Mar
    "apr": 1, "may": 1, "jun": 1,   # Q1 = Apr-Jun
    "jul": 2, "aug": 2, "sep": 2,   # Q2 = Jul-Sep
    "oct": 3, "nov": 3, "dec": 3,   # Q3 = Oct-Dec
}


def _expand_year(y: str) -> str:
    if len(y) == 2:
        return f"20{y}" if int(y) < 80 else f"19{y}"
    return y


def normalise_period(raw: str) -> str:
    """Convert a raw period header into ``YYYY-QX`` or ``YYYY-FY``."""
    raw = raw.strip()
    m = _PERIOD_RE.search(raw)
    if not m:
        return raw  # return as-is if unparseable

    if m.group("fy_year"):
        return f"{_expand_year(m.group('fy_year'))}-FY"

    if m.group("q_prefix"):
        q = m.group("q_prefix")
        y = _expand_year(m.group("q_year1"))
        return f"{y}-Q{q}"

    if m.group("quarter"):
        q = m.group("quarter")
        y = _expand_year(m.group("q_year2"))
        return f"{y}-Q{q}"

    if m.group("months"):
        months = int(m.group("months"))
        y = _expand_year(m.group("m_year"))
        if months == 12:
            return f"{y}-FY"
        q = {3: "Q1", 6: "Q2", 9: "Q3"}.get(months, f"{months}M")
        if q.startswith("Q"):
            return f"{y}-{q}"
        return f"{y}-{q}"

    if m.group("mon_name"):
        mon = m.group("mon_name").lower()[:3]
        y = _expand_year(m.group("mon_year"))
        q = _MONTH_TO_Q.get(mon)
        if q:
            return f"{y}-Q{q}"
        return f"{y}-{mon.capitalize()}"

    if m.group("plain_year"):
        return f"{m.group('plain_year')}-FY"

    return raw


# ---------------------------------------------------------------------------
# Header parsing
# ---------------------------------------------------------------------------

_CURRENCY_RE = re.compile(
    r"\b(INR|USD|EUR|GBP|JPY|CNY|CHF|AUD|CAD|HKD|SGD|BRL|KRW)\b",
    re.IGNORECASE,
)


def _parse_header(text: str) -> tuple[str, str, Optional[str]]:
    """Extract (company_name, currency, statement_type) from the first few
    lines of the PDF text.

    Bloomberg exports are not always simple "{Company}\n{Statement}" headers;
    many PDFs include a metadata line like "... Currency: INR ... Company: Foo".
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    header_block = "\n".join(lines[:15])  # top block is usually enough

    # Statement type
    stmt = detect_statement_type(header_block)

    # Currency
    cur_match = _CURRENCY_RE.search(header_block)
    currency = cur_match.group(1).upper() if cur_match else "INR"

    # Company name
    company = ""

    # Prefer an explicit "Company:" field if present (common in Bloomberg exports)
    m = re.search(
        r"\bCompany\s*:\s*(?P<name>[^\n]+)",
        header_block,
        flags=re.IGNORECASE,
    )
    if m:
        company = m.group("name").strip()

    # Fallback to first non-empty line, but skip generic report titles.
    if not company:
        company = lines[0] if lines else "UNKNOWN"
        if company.lower() in {"financial statement analysis", "financial statement"}:
            # Next meaningful line usually contains the company metadata.
            company = lines[1] if len(lines) > 1 else company

    # Strip common suffixes
    company = re.sub(r"\s*\(.*?\)\s*$", "", company).strip()
    company = re.sub(
        r"\s*[-–]\s*(Income Statement|Balance Sheet|IS|BS).*$",
        "",
        company,
        flags=re.IGNORECASE,
    ).strip()

    return company, currency, stmt


# ---------------------------------------------------------------------------
# Table-based parsing
# ---------------------------------------------------------------------------


def _parse_from_tables(
    tables: list[list[list[str | None]]],
    stmt_type: Optional[str],
) -> tuple[list[str], dict[str, list[PeriodValue]]]:
    """Parse financial data from extracted tables.

    Returns (periods, data_dict).
    """
    periods: list[str] = []
    data: dict[str, list[PeriodValue]] = {}

    for table in tables:
        if not table or len(table) < 2:
            continue

        # The first row is usually the header containing period labels
        header_row = table[0]

        # Detect period columns: skip the first cell (label column)
        col_periods: list[Optional[str]] = [None]  # index 0 = label column
        for cell in (header_row[1:] if len(header_row) > 1 else []):
            raw = (cell or "").strip()
            if raw:
                p = normalise_period(raw)
                col_periods.append(p)
                if p not in periods:
                    periods.append(p)
            else:
                col_periods.append(None)

        if not any(col_periods[1:]):
            # No period columns detected; try next table
            continue

        # Process data rows
        for row in table[1:]:
            if not row or not row[0]:
                continue
            label = (row[0] or "").strip()
            canonical = resolve_field(label)
            if canonical is None:
                continue

            for col_idx in range(1, min(len(row), len(col_periods))):
                period = col_periods[col_idx]
                if period is None:
                    continue
                val = _parse_number(row[col_idx])
                if val is not None:
                    data.setdefault(canonical, []).append(
                        PeriodValue(period=period, value=val)
                    )

    return periods, data


# ---------------------------------------------------------------------------
# Text-based fallback parsing (line-by-line)
# ---------------------------------------------------------------------------

_TRAILING_FOOTNOTE_RE = re.compile(r"[^\d\-,.()−–]+$")


def _strip_trailing_footnote(token: str) -> str:
    """Remove common trailing footnote markers (e.g. '*', 'a', ')¹')."""
    return _TRAILING_FOOTNOTE_RE.sub("", token)


def _extract_periods_from_line(line: str) -> list[str]:
    """Extract periods in display order from a header line."""
    out: list[str] = []
    for m in _PERIOD_RE.finditer(line):
        raw = m.group(0)
        p = normalise_period(raw)
        if p not in out:
            out.append(p)
    return out


def _parse_from_text(
    text: str,
    stmt_type: Optional[str],
) -> tuple[list[str], dict[str, list[PeriodValue]]]:
    """Fallback parser that works on raw extracted text when table extraction
    fails or returns empty results.

    Bloomberg exports frequently render tables with single-space separation, so
    we cannot rely on "2+ spaces" column splits. Instead, detect numeric tokens
    at the end of each line and treat the remaining prefix as the label.
    """
    lines = [l for l in text.split("\n") if l.strip()]
    periods: list[str] = []
    data: dict[str, list[PeriodValue]] = {}

    # Try to locate a header row containing multiple period labels.
    header_idx: Optional[int] = None
    for i, line in enumerate(lines):
        ps = _extract_periods_from_line(line)
        if len(ps) >= 2:
            header_idx = i
            periods = ps
            break

    if header_idx is None:
        return periods, data

    # Parse subsequent lines as data rows.
    for line in lines[header_idx + 1 :]:
        tokens = line.strip().split()
        if len(tokens) < 2:
            continue

        # Collect numeric values from the end of the line.
        values_raw: list[str] = []
        idx = len(tokens) - 1
        while idx >= 0:
            tok = _strip_trailing_footnote(tokens[idx])
            if _parse_number(tok) is None:
                break
            values_raw.append(tok)
            idx -= 1

        if len(values_raw) < 2:
            # Skip lines that don't look like a table row.
            continue

        label = " ".join(tokens[: idx + 1]).strip()
        label = label.lstrip("+•*- ").strip()
        if not label:
            continue

        canonical = resolve_field(label)
        if canonical is None:
            continue

        values_raw.reverse()  # restore left-to-right order

        # Align values with periods.
        if len(values_raw) == len(periods):
            aligned_periods = periods
        elif len(values_raw) < len(periods):
            aligned_periods = periods[-len(values_raw) :]
        else:
            aligned_periods = periods[: len(values_raw)]

        for p, raw_val in zip(aligned_periods, values_raw):
            val = _parse_number(raw_val)
            if val is not None:
                data.setdefault(canonical, []).append(PeriodValue(period=p, value=val))

    return periods, data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_statement(content: PDFContent) -> ParsedStatement:
    """Parse a Bloomberg financial-statement PDF into structured data.

    Tries table-based extraction first; falls back to text-based line
    parsing if tables yield no usable data.
    """
    full_text = content.full_text
    company, currency, stmt_type = _parse_header(full_text)

    result = ParsedStatement(
        source_file=content.path.name,
        company=company,
        currency=currency,
        statement_type=stmt_type,
    )

    # Attempt table-based extraction first
    tables = content.all_tables
    if tables:
        periods, data = _parse_from_tables(tables, stmt_type)
        if data:
            result.periods = periods
            result.data = data
            logger.info(
                "Parsed %d fields from tables in %s",
                len(data),
                content.path.name,
            )
            return result

    # Fallback to text-based parsing
    periods, data = _parse_from_text(full_text, stmt_type)
    result.periods = periods
    result.data = data

    if data:
        logger.info(
            "Parsed %d fields from text in %s",
            len(data),
            content.path.name,
        )
    else:
        logger.warning("No financial data extracted from %s", content.path.name)

    return result
