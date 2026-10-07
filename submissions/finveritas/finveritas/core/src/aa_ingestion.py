"""Account Aggregator (AA) FI schema ingestion — DEPOSIT type.

Parses ReBIT Financial Information (FI) DEPOSIT JSON data into the internal
payload schema used by the FinVeritas agent pipeline.

Revenue is proxied as the sum of CREDIT transactions per calendar quarter.
Current assets is proxied as the end-of-quarter running balance.

NOTE: This is a proof-of-concept implementation. Production AA integration
requires registration as a Financial Information User (FIU) with the
RBI-regulated Account Aggregator ecosystem (Sahamati / FinSAT) and must use
encrypted FI data exchanged via the AA consent artefact flow.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any


def _quarter(dt: datetime) -> str:
    return f"{dt.year}-Q{(dt.month - 1) // 3 + 1}"


def _to_series(mapping: dict[str, float]) -> list[dict[str, Any]]:
    return [{"period": k, "value": round(v, 2)} for k, v in sorted(mapping.items())]


def parse_aa_deposit(
    file_bytes: bytes,
    company_name: str,
    currency: str = "INR",
) -> dict[str, Any]:
    """Parse a ReBIT FI DEPOSIT JSON into the internal payload schema.

    Accepts a single FI object or a list of FI objects (multiple accounts).

    Raises:
        ValueError: if the file is not valid JSON or has no CREDIT transactions.
    """
    try:
        raw = json.loads(file_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Invalid JSON in AA data file: {exc}") from exc

    fi_list: list[dict] = raw if isinstance(raw, list) else [raw]

    quarterly_credits: dict[str, float] = {}
    quarterly_balance: dict[str, float] = {}

    for fi in fi_list:
        payload_block = fi.get("Payload", fi)
        txn_block = payload_block.get("Transactions", {})
        transactions = txn_block.get("Transaction", [])
        if isinstance(transactions, dict):
            transactions = [transactions]

        for txn in transactions:
            raw_date = txn.get("valueDate") or (txn.get("transactionTimestamp") or "")[:10]
            if not raw_date:
                continue
            try:
                dt = datetime.strptime(raw_date[:10], "%Y-%m-%d")
            except ValueError:
                continue

            period = _quarter(dt)

            try:
                amount = float(txn.get("amount") or 0)
            except (TypeError, ValueError):
                continue

            txn_type = (txn.get("type") or "").strip().upper()
            if txn_type == "CREDIT":
                quarterly_credits[period] = quarterly_credits.get(period, 0.0) + amount

            try:
                bal = float(txn.get("currentBalance") or 0)
                quarterly_balance[period] = bal
            except (TypeError, ValueError):
                pass

    if not quarterly_credits:
        raise ValueError(
            "No CREDIT transactions found. "
            "Ensure this is a ReBIT FI DEPOSIT schema JSON with Transaction entries of type CREDIT."
        )

    time_series: dict[str, Any] = {"revenue": _to_series(quarterly_credits)}
    if quarterly_balance:
        time_series["current_assets"] = _to_series(quarterly_balance)

    return {
        "entity": {
            "entity_id": company_name,
            "source": "aa_deposit",
            "currency": currency,
            "source_files": ["aa_fi_data.json"],
        },
        "time_series": time_series,
    }


_SAMPLE: dict[str, Any] = {
    "ver": "1.1",
    "timestamp": "2024-01-01T00:00:00.000Z",
    "txnid": "sample-001",
    "Payload": {
        "maskedAccNumber": "XXXXXXX8299",
        "Summary": {
            "currentBalance": "2450000.00",
            "currency": "INR",
            "type": "CURRENT",
            "status": "ACTIVE",
        },
        "Transactions": {
            "Transaction": [
                {"type": "CREDIT", "amount": "500000.00", "currentBalance": "550000.00",
                 "valueDate": "2023-04-15", "narration": "Sales Receipt Q1"},
                {"type": "DEBIT",  "amount": "120000.00", "currentBalance": "430000.00",
                 "valueDate": "2023-05-10", "narration": "Vendor Payment"},
                {"type": "CREDIT", "amount": "620000.00", "currentBalance": "1050000.00",
                 "valueDate": "2023-07-20", "narration": "Sales Receipt Q2"},
                {"type": "CREDIT", "amount": "580000.00", "currentBalance": "1630000.00",
                 "valueDate": "2023-10-10", "narration": "Sales Receipt Q3"},
                {"type": "CREDIT", "amount": "700000.00", "currentBalance": "2330000.00",
                 "valueDate": "2024-01-05", "narration": "Sales Receipt Q4"},
            ]
        },
    },
}


def sample_json() -> str:
    """Return a minimal ReBIT DEPOSIT FI JSON string for testing."""
    return json.dumps(_SAMPLE, indent=2)
