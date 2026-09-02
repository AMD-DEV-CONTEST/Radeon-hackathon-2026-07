#!/usr/bin/env python3
"""Audit declared Technology 20 development coverage without reading sealed cases."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "signalforge/technology20-development-coverage/v1"
REQUIRED_STANDALONE_DOMAINS = (
    "accounting",
    "business",
    "economics",
    "evidence",
    "financial_quality",
    "market_behavior",
    "valuation",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(catalog_path: Path, suite_path: Path) -> dict[str, Any]:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    companies = catalog.get("companies", [])
    cases = suite.get("cases", [])
    if len(companies) != 20:
        raise ValueError("Technology 20 catalog must contain exactly 20 companies")
    if suite.get("split") != "development":
        raise ValueError("only the public development split may be audited")

    company_ids = {item["company_id"] for item in companies}
    journey_ids: set[str] = set()
    coverage: dict[str, Counter[str]] = defaultdict(Counter)
    global_domains: Counter[str] = Counter()
    question_ids: Counter[str] = Counter()
    problems: list[str] = []

    for case in cases:
        journey_id = case.get("journey_id", "")
        company_id = case.get("company_id", "")
        domains = case.get("required_domains", [])
        if not journey_id or journey_id in journey_ids:
            problems.append(f"duplicate_or_empty_journey_id:{journey_id}")
        journey_ids.add(journey_id)
        if company_id not in company_ids:
            problems.append(f"unknown_company:{company_id}")
            continue
        if not domains:
            problems.append(f"missing_required_domains:{journey_id}")
        question_ids[case.get("question_id", "")] += 1
        for domain in domains:
            coverage[company_id][domain] += 1
            global_domains[domain] += 1

    company_reports = []
    for company in sorted(companies, key=lambda item: item["primary_ticker"]):
        company_id = company["company_id"]
        counts = coverage[company_id]
        missing = [
            domain for domain in REQUIRED_STANDALONE_DOMAINS if counts[domain] == 0
        ]
        case_count = sum(1 for case in cases if case.get("company_id") == company_id)
        if case_count == 0:
            problems.append(f"company_without_development_case:{company_id}")
        company_reports.append(
            {
                "company_id": company_id,
                "primary_ticker": company["primary_ticker"],
                "case_count": case_count,
                "declared_domain_counts": dict(sorted(counts.items())),
                "missing_required_domains": missing,
                "complete_domain_coverage": not missing,
            }
        )

    missing_global = [
        domain for domain in REQUIRED_STANDALONE_DOMAINS if global_domains[domain] == 0
    ]
    complete_companies = sum(
        1 for item in company_reports if item["complete_domain_coverage"]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "universe_id": catalog["universe_id"],
        "split": "development",
        "catalog_sha256": sha256(catalog_path),
        "suite_sha256": sha256(suite_path),
        "company_count": len(companies),
        "case_count": len(cases),
        "unique_journey_count": len(journey_ids),
        "question_id_counts": dict(sorted(question_ids.items())),
        "declared_domain_counts": dict(sorted(global_domains.items())),
        "required_standalone_domains": list(REQUIRED_STANDALONE_DOMAINS),
        "missing_global_domains": missing_global,
        "companies_with_complete_domain_coverage": complete_companies,
        "companies": company_reports,
        "problems": sorted(set(problems)),
        "promotion_eligible": (
            not problems
            and not missing_global
            and complete_companies == len(companies)
        ),
        "claim_boundary": (
            "This report audits only domains explicitly declared by the public development "
            "suite. It does not read sealed cases, measure factual accuracy, authorize a "
            "company, or replace professional and rights review."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.catalog, args.suite)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "development coverage: "
        f"{result['company_count']} companies, {result['case_count']} cases, "
        f"missing domains={','.join(result['missing_global_domains']) or 'none'}"
    )


if __name__ == "__main__":
    main()
