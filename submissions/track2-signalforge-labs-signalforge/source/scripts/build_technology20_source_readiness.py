#!/usr/bin/env python3
"""Build a typed source-readiness ledger for every Technology 20 issuer."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "signalforge/technology20-source-readiness/v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(catalog_path: Path, audit_path: Path) -> dict[str, Any]:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if len(catalog["companies"]) != 20 or not audit["passed"]:
        raise ValueError("catalog or data authority is not eligible for source-readiness export")
    sec_by_company = {
        item["company_id"]: item for item in audit["company_freshness"]
    }
    companies = []
    for company in catalog["companies"]:
        company_id = company["company_id"]
        sec = sec_by_company.get(company_id)
        if sec is None:
            raise ValueError(f"{company_id}: SEC freshness record is missing")
        companies.append(
            {
                "company_id": company_id,
                "display_name": company["display_name"],
                "primary_ticker": company["primary_ticker"],
                "sources": {
                    "sec_companyfacts": {
                        "state": "fresh" if sec["status"] == "fresh" else sec["status"],
                        "latest_form": sec["latest_periodic_form"],
                        "available_at": sec["latest_periodic_published_at"],
                        "age_days": sec["age_days"],
                        "reason_codes": [],
                    },
                    "market_price": {
                        "state": "missing",
                        "available_at": None,
                        "reason_codes": ["frozen_provider_observation_not_supplied"],
                    },
                    "fred_vintage": {
                        "state": "missing",
                        "available_at": None,
                        "reason_codes": ["frozen_vintage_observation_not_supplied"],
                    },
                    "investor_relations_narrative": {
                        "state": "quarantined",
                        "available_at": None,
                        "reason_codes": ["pending_named_rights_and_factuality_review"],
                    },
                },
                "standalone_promotion_blocked": True,
                "blocking_reason_codes": [
                    "market_price_authority_missing",
                    "macro_vintage_authority_missing",
                    "narrative_rights_review_pending",
                    "standalone_journey_not_evaluated",
                ],
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "universe_id": catalog["universe_id"],
        "as_of": audit["as_of"],
        "catalog_sha256": sha256(catalog_path),
        "data_authority_audit_sha256": sha256(audit_path),
        "companies": companies,
        "source_summary": {
            "sec_companyfacts_fresh": sum(
                1
                for item in companies
                if item["sources"]["sec_companyfacts"]["state"] == "fresh"
            ),
            "market_price_missing": 20,
            "fred_vintage_missing": 20,
            "investor_relations_quarantined": 20,
        },
        "claim_boundary": (
            "This ledger records source readiness, not company research readiness. Missing market, "
            "macro-vintage, and rights-reviewed narrative sources remain fail-closed even when SEC "
            "Company Facts are fresh."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--data-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.catalog, args.data_audit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("source readiness: 20 SEC-fresh companies; market, FRED, and IR remain guarded")


if __name__ == "__main__":
    main()
