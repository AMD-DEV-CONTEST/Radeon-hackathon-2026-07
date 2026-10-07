"""
JSON output builder.

Aggregates parsed Income Statement and Balance Sheet data for each company
into the target JSON schema expected by downstream financial analysis agents.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from .parser import ParsedStatement

logger = logging.getLogger(__name__)

# Fields that MUST appear in the output (populated with [] if missing).
_REQUIRED_FIELDS = [
    "revenue",
    "net_income",
    "total_assets",
    "total_liabilities",
    "total_debt",
    "equity",
]


def _company_key(name: str) -> str:
    """Normalise company name for grouping (case-insensitive, trimmed)."""
    return name.strip().upper()


def _dedup_series(
    series: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Remove duplicate (period, value) entries, keeping the last seen."""
    seen: dict[str, dict[str, Any]] = {}
    for entry in series:
        seen[entry["period"]] = entry
    # Sort chronologically
    return sorted(seen.values(), key=lambda e: e["period"])


def build_company_json(statements: list[ParsedStatement]) -> dict[str, Any]:
    """Build the output JSON for a single company from one or more parsed
    statements (typically one IS + one BS).

    Parameters
    ----------
    statements:
        All ``ParsedStatement`` objects belonging to the same company.

    Returns
    -------
    dict
        JSON-serialisable dict in the target schema.
    """
    if not statements:
        raise ValueError("No statements provided")

    # Use metadata from the first statement as the baseline
    ref = statements[0]
    entity_id = ref.company or "UNKNOWN"
    currency = ref.currency

    # Merge data from all statements
    merged: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_files: list[str] = []

    for stmt in statements:
        source_files.append(stmt.source_file)
        # Prefer the most specific currency found
        if stmt.currency != "INR" or currency == "INR":
            currency = stmt.currency

        for field_key, pv_list in stmt.data.items():
            for pv in pv_list:
                merged[field_key].append(
                    {"period": pv.period, "value": pv.value}
                )

    # Ensure required fields exist (even if empty)
    time_series: dict[str, list[dict[str, Any]]] = {}
    all_keys = set(merged.keys()) | set(_REQUIRED_FIELDS)
    for key in sorted(all_keys):
        time_series[key] = _dedup_series(merged.get(key, []))

    return {
        "entity": {
            "entity_id": entity_id,
            "source": "Bloomberg",
            "currency": currency,
            "source_files": source_files,
        },
        "time_series": time_series,
    }


def aggregate_and_write(
    statements: list[ParsedStatement],
    output_dir: Path,
) -> list[Path]:
    """Group statements by company, build JSON, and write to *output_dir*.

    Returns the list of written file paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Group by normalised company name
    groups: dict[str, list[ParsedStatement]] = defaultdict(list)
    for stmt in statements:
        groups[_company_key(stmt.company)].append(stmt)

    written: list[Path] = []

    for key, stmts in groups.items():
        payload = build_company_json(stmts)
        # Sanitise filename
        safe_name = "".join(
            c if c.isalnum() or c in (" ", "_", "-") else "_"
            for c in stmts[0].company
        ).strip().replace(" ", "_")
        out_path = output_dir / f"{safe_name}.json"

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

        logger.info("Wrote %s (%d fields)", out_path.name, len(payload["time_series"]))
        written.append(out_path)

    return written
