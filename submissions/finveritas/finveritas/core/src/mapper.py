"""
Canonical field mapping for Bloomberg Terminal financial statement PDFs.

Bloomberg line-item labels vary across exports (abbreviations, casing, extra
whitespace). This module centralises the mapping so that the parser can resolve
any recognised variant to a canonical key used in the output JSON.
"""

from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Statement-type detection patterns
# ---------------------------------------------------------------------------
# Bloomberg headers usually contain one of these phrases.
IS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"income\s+statement", re.IGNORECASE),
    re.compile(r"profit\s*(?:&|and)\s*loss", re.IGNORECASE),
    re.compile(r"\bIS\b"),
]

BS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"balance\s+sheet", re.IGNORECASE),
    re.compile(r"\bBS\b"),
]


def detect_statement_type(text: str) -> Optional[str]:
    """Return 'IS' or 'BS' based on header text, or None if unknown."""
    for pat in IS_PATTERNS:
        if pat.search(text):
            return "IS"
    for pat in BS_PATTERNS:
        if pat.search(text):
            return "BS"
    return None


# ---------------------------------------------------------------------------
# Line-item → canonical key mapping
# ---------------------------------------------------------------------------
# Each canonical key maps to a list of regex patterns that match known
# Bloomberg label variants.  Patterns are tried in order; first match wins.

_FIELD_MAP: dict[str, list[re.Pattern[str]]] = {
    # ── Income Statement fields ──────────────────────────────────────────
    "revenue": [
        re.compile(r"^(?:total\s+)?revenue", re.IGNORECASE),
        re.compile(r"^net\s+revenue", re.IGNORECASE),
        re.compile(r"^sales", re.IGNORECASE),
        re.compile(r"^turnover", re.IGNORECASE),
        re.compile(r"^revenue\s+from\s+operations", re.IGNORECASE),
    ],
    "cost_of_revenue": [
        re.compile(r"^cost\s+of\s+(?:revenue|goods\s+sold|sales)", re.IGNORECASE),
        re.compile(r"^COGS$", re.IGNORECASE),
    ],
    "gross_profit": [
        re.compile(r"^gross\s+profit", re.IGNORECASE),
    ],
    "operating_income": [
        re.compile(r"^operating\s+(?:income|profit)", re.IGNORECASE),
        re.compile(r"^EBIT$", re.IGNORECASE),
    ],
    "ebitda": [
        re.compile(r"^EBITDA$", re.IGNORECASE),
    ],
    "interest_expense": [
        re.compile(r"^interest\s+expense", re.IGNORECASE),
        re.compile(r"^finance\s+cost", re.IGNORECASE),
    ],
    "pretax_income": [
        re.compile(r"^(?:pre[\-\s]?tax|before\s+tax)\s+(?:income|profit)", re.IGNORECASE),
        re.compile(r"^income\s+before\s+tax", re.IGNORECASE),
        re.compile(r"^profit\s+before\s+tax", re.IGNORECASE),
        re.compile(r"^PBT$", re.IGNORECASE),
    ],
    "income_tax": [
        re.compile(r"^income\s+tax", re.IGNORECASE),
        re.compile(r"^(?:provision|expense)\s+for\s+(?:income\s+)?tax", re.IGNORECASE),
        re.compile(r"^tax\s+expense", re.IGNORECASE),
    ],
    "net_income": [
        re.compile(r"^net\s+(?:income|profit|earnings)", re.IGNORECASE),
        re.compile(r"^profit\s+(?:after\s+tax|for\s+the\s+(?:period|year))", re.IGNORECASE),
        re.compile(r"^PAT$", re.IGNORECASE),
    ],
    "diluted_eps": [
        re.compile(r"^diluted\s+(?:EPS|earnings\s+per\s+share)", re.IGNORECASE),
    ],
    "basic_eps": [
        re.compile(r"^basic\s+(?:EPS|earnings\s+per\s+share)", re.IGNORECASE),
        re.compile(r"^EPS", re.IGNORECASE),
    ],
    "depreciation": [
        re.compile(r"^depreciation", re.IGNORECASE),
        re.compile(r"^depreciation\s*(?:&|and)\s*amortization", re.IGNORECASE),
        re.compile(r"^D&A$", re.IGNORECASE),
    ],

    # ── Balance Sheet fields ─────────────────────────────────────────────
    "total_assets": [
        re.compile(r"^total\s+assets", re.IGNORECASE),
    ],
    "current_assets": [
        re.compile(r"^(?:total\s+)?current\s+assets", re.IGNORECASE),
    ],
    "non_current_assets": [
        re.compile(r"^(?:total\s+)?non[\-\s]?current\s+assets", re.IGNORECASE),
        re.compile(r"^(?:total\s+)?fixed\s+assets", re.IGNORECASE),
    ],
    "cash_and_equivalents": [
        re.compile(r"^cash\s*(?:&|and)\s*(?:cash\s+)?equivalents", re.IGNORECASE),
        re.compile(r"^cash\s*$", re.IGNORECASE),
    ],
    "total_liabilities": [
        re.compile(r"^total\s+liabilities", re.IGNORECASE),
    ],
    "current_liabilities": [
        re.compile(r"^(?:total\s+)?current\s+liabilities", re.IGNORECASE),
    ],
    "non_current_liabilities": [
        re.compile(r"^(?:total\s+)?non[\-\s]?current\s+liabilities", re.IGNORECASE),
        re.compile(r"^(?:total\s+)?long[\-\s]?term\s+liabilities", re.IGNORECASE),
    ],
    "total_debt": [
        re.compile(r"^total\s+debt", re.IGNORECASE),
        re.compile(r"^total\s+borrowings", re.IGNORECASE),
    ],
    "short_term_debt": [
        re.compile(r"^short[\-\s]?term\s+(?:debt|borrowings)", re.IGNORECASE),
    ],
    "long_term_debt": [
        re.compile(r"^long[\-\s]?term\s+(?:debt|borrowings)", re.IGNORECASE),
    ],
    "equity": [
        re.compile(r"^total\s+(?:shareholders?['\u2019]?s?\s+)?equity", re.IGNORECASE),
        re.compile(r"^(?:shareholders?['\u2019]?s?\s+)?equity", re.IGNORECASE),
        re.compile(r"^net\s+worth", re.IGNORECASE),
        re.compile(r"^total\s+equity", re.IGNORECASE),
    ],
    "retained_earnings": [
        re.compile(r"^retained\s+earnings", re.IGNORECASE),
        re.compile(r"^accumulated\s+(?:profit|surplus)", re.IGNORECASE),
    ],
}


def resolve_field(label: str) -> Optional[str]:
    """Map a raw Bloomberg line-item label to a canonical field key.

    Returns the canonical key (e.g. ``"revenue"``, ``"total_assets"``) or
    ``None`` if the label is not recognised.
    """
    label = label.strip()
    for canonical, patterns in _FIELD_MAP.items():
        for pat in patterns:
            if pat.search(label):
                return canonical
    return None
