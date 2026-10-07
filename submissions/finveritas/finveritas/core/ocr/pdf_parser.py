"""PDF → JSON parser for the Streamlit demo.

This module wraps the existing OCR pipeline in `src/` so the Streamlit app can
process a single uploaded PDF and get a JSON payload in-memory, while also
persisting it to `output/`.

For each uploaded PDF three agent-specific JSON files are written in addition
to the full combined output:
  {company}_revenue.json       — Income Statement fields  → Revenue Agent
  {company}_balance_sheet.json — Balance Sheet fields     → Balance Sheet Agent
  {company}_liquidity.json     — Liquidity fields         → Liquidity Agent
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from src.builder import build_company_json
from src.extractor import extract_pdf
from src.parser import parse_statement

# ---------------------------------------------------------------------------
# Field sets that define what each agent needs
# ---------------------------------------------------------------------------

_REVENUE_FIELDS: frozenset[str] = frozenset({
    "revenue", "cost_of_revenue", "gross_profit", "operating_income",
    "ebitda", "interest_expense", "pretax_income", "income_tax",
    "net_income", "diluted_eps", "basic_eps", "depreciation",
})

_BALANCE_SHEET_FIELDS: frozenset[str] = frozenset({
    "total_assets", "total_liabilities", "equity", "total_debt",
    "non_current_assets", "non_current_liabilities",
    "cash_and_equivalents", "retained_earnings",
    "short_term_debt", "long_term_debt",
})

_LIQUIDITY_FIELDS: frozenset[str] = frozenset({
    "current_assets", "current_liabilities",
    "total_assets", "total_liabilities", "equity",
})


def _sub_payload(payload: dict[str, Any], fields: frozenset[str]) -> dict[str, Any]:
    """Return a copy of *payload* with time_series limited to *fields*."""
    ts = payload.get("time_series") or {}
    return {
        "entity": payload.get("entity", {}),
        "time_series": {k: v for k, v in ts.items() if k in fields},
    }


def parse_pdf_to_json(
    *,
    uploads: list[tuple[bytes, str]],
    output_dir: str | Path = "output",
) -> tuple[dict[str, Any], Path, dict[str, Path]]:
    """Parse one or more uploaded PDFs and merge them into the repo's JSON schema.

    Passing both an Income Statement PDF and a Balance Sheet PDF in *uploads*
    allows all agents (Revenue, Balance Sheet, Liquidity) to run.

    Args:
        uploads: List of (pdf_bytes, original_filename) tuples.
        output_dir: Directory where JSON files should be written.

    Returns:
        (payload_dict, full_json_path, agent_paths)
        where agent_paths = {"revenue": Path, "balance_sheet": Path, "liquidity": Path}

    Raises:
        ValueError: if extraction/parsing yields no usable data from any PDF.
    """
    if not uploads:
        raise ValueError("No PDF files provided")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    parsed_statements = []

    with tempfile.TemporaryDirectory() as td:
        for idx, (pdf_bytes, filename) in enumerate(uploads):
            suffix = "" if filename.lower().endswith(".pdf") else ".pdf"
            pdf_path = Path(td) / f"upload_{idx}{suffix or Path(filename).suffix}"
            pdf_path.write_bytes(pdf_bytes)

            content = extract_pdf(pdf_path)
            if not content.pages:
                raise ValueError(f"No pages extracted from '{filename}'")

            parsed = parse_statement(content)
            # Give the parsed statement the original filename for traceability.
            parsed.source_file = filename
            if parsed.data:
                parsed_statements.append(parsed)

        if not parsed_statements:
            raise ValueError("No recognised financial data extracted from any uploaded PDF")

        payload = build_company_json(parsed_statements)

        # Sanitise company name for filenames (mirrors builder.py logic).
        entity_id = str(payload.get("entity", {}).get("entity_id") or "UNKNOWN")
        safe = "".join(c if c.isalnum() or c in (" ", "_", "-") else "_" for c in entity_id)
        safe = safe.strip().replace(" ", "_") or "UNKNOWN"

        def _write(name: str, data: dict[str, Any]) -> Path:
            p = out_dir / name
            p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            return p

        # Full combined output (unchanged schema).
        full_path = _write(f"{safe}.json", payload)

        # Agent-specific split files.
        agent_paths: dict[str, Path] = {
            "revenue":       _write(f"{safe}_revenue.json",       _sub_payload(payload, _REVENUE_FIELDS)),
            "balance_sheet": _write(f"{safe}_balance_sheet.json", _sub_payload(payload, _BALANCE_SHEET_FIELDS)),
            "liquidity":     _write(f"{safe}_liquidity.json",     _sub_payload(payload, _LIQUIDITY_FIELDS)),
        }

        return payload, full_path, agent_paths


# ---------------------------------------------------------------------------
# Generic helper for in-memory payloads (yfinance / private CSV ingestion)
# ---------------------------------------------------------------------------

def payload_to_agent_files(
    payload: dict[str, Any],
    output_dir: str | Path = "output",
) -> tuple[dict[str, Any], Path, dict[str, Path]]:
    """Write an arbitrary in-memory payload to the agent-specific JSON files.

    Use this for data sources that produce a payload dict directly (e.g.
    ``src.yfinance_ingestion.fetch_by_ticker`` or
    ``src.private_company_ingestion.load_private_company_data``) so they can
    feed the same downstream agent pipeline as Bloomberg PDF uploads.

    Args:
        payload:    A dict with ``entity`` and ``time_series`` keys — same
                    schema produced by :func:`parse_pdf_to_json`.
        output_dir: Directory where JSON files should be written.

    Returns:
        ``(payload, full_json_path, agent_paths)`` — identical shape to
        the return value of :func:`parse_pdf_to_json`.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    entity_id = str(payload.get("entity", {}).get("entity_id") or "UNKNOWN")
    safe = "".join(c if c.isalnum() or c in (" ", "_", "-") else "_" for c in entity_id)
    safe = safe.strip().replace(" ", "_") or "UNKNOWN"

    def _write(name: str, data: dict[str, Any]) -> Path:
        p = out_dir / name
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return p

    full_path = _write(f"{safe}.json", payload)

    agent_paths: dict[str, Path] = {
        "revenue":       _write(f"{safe}_revenue.json",       _sub_payload(payload, _REVENUE_FIELDS)),
        "balance_sheet": _write(f"{safe}_balance_sheet.json", _sub_payload(payload, _BALANCE_SHEET_FIELDS)),
        "liquidity":     _write(f"{safe}_liquidity.json",     _sub_payload(payload, _LIQUIDITY_FIELDS)),
    }

    return payload, full_path, agent_paths

