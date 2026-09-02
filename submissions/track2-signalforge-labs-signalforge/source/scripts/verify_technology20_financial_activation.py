#!/usr/bin/env python3
"""Independently recompute every released Technology 20 financial receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "signalforge/technology20-financial-reference-check/v1"
getcontext().prec = 80


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def values_by_id(items: list[dict[str, Any]], id_field: str) -> dict[str, Decimal]:
    return {
        item[id_field]: Decimal(item["quantity"]["value"])
        for item in items
    }


def independently_recompute(receipt: dict[str, Any]) -> dict[str, Decimal | bool]:
    operation = receipt["operation_id"]
    inputs = values_by_id(receipt["normalized_inputs"], "input_id")
    if operation == "accounting.balance_sheet_identity":
        difference = inputs["assets"] - inputs["liabilities"] - inputs["equity"]
        return {"difference": difference, "within_tolerance": abs(difference) <= Decimal("0.01")}
    if operation == "financial.revenue_growth":
        return {
            "growth_rate": (
                inputs["revenue_current"] - inputs["revenue_prior"]
            ) / inputs["revenue_prior"]
        }
    if operation == "financial.operating_margin":
        return {"operating_margin": inputs["operating_income"] / inputs["revenue"]}
    if operation == "financial.free_cash_flow":
        return {
            "free_cash_flow": (
                inputs["operating_cash_flow"] - inputs["capital_expenditure"]
            )
        }
    if operation == "financial.cash_conversion":
        return {
            "cash_conversion": (
                inputs["operating_cash_flow"] / inputs["net_income"]
            )
        }
    if operation == "financial.capex_intensity":
        return {
            "capex_intensity": (
                inputs["capital_expenditure"] / inputs["revenue"]
            )
        }
    if operation == "financial.quality_of_earnings":
        return {
            "accrual_gap": inputs["operating_cash_flow"] - inputs["net_income"],
            "cash_conversion": inputs["operating_cash_flow"] / inputs["net_income"],
        }
    raise ValueError(f"unsupported released operation {operation!r}")


def verify(root: Path) -> dict[str, Any]:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    operation_counts: Counter[str] = Counter()
    companies: set[str] = set()
    receipts = 0
    abstentions = 0
    for reference in manifest["reports"]:
        report_path = root / reference["path"]
        if sha256(report_path) != reference["file_sha256"]:
            failures.append(f"{reference['company_id']}:file_sha256_mismatch")
            continue
        report = json.loads(report_path.read_text(encoding="utf-8"))
        company_id = report["company_id"]
        companies.add(company_id)
        if company_id != reference["company_id"]:
            failures.append(f"{company_id}:company_reference_mismatch")
        for receipt in report["receipts"]:
            receipts += 1
            operation = receipt["operation_id"]
            operation_counts[operation] += 1
            if operation.startswith("valuation."):
                failures.append(f"{company_id}:{operation}:valuation_not_authorized")
            if (
                operation == "financial.free_cash_flow"
                and any(output["output_id"] == "fcff" for output in receipt["outputs"])
            ):
                failures.append(f"{company_id}:{operation}:simple_fcf_mislabeled")
            expected = independently_recompute(receipt)
            actual = {
                item["output_id"]: (
                    item["quantity"]["value"]
                    if item["quantity"]["unit"] == "boolean"
                    else Decimal(item["quantity"]["value"])
                )
                for item in receipt["outputs"]
            }
            for output_id, expected_value in expected.items():
                actual_value = actual.get(output_id)
                if isinstance(expected_value, bool):
                    if actual_value != ("1" if expected_value else "0"):
                        failures.append(f"{company_id}:{operation}:{output_id}:boolean_mismatch")
                elif (
                    not isinstance(actual_value, Decimal)
                    or abs(actual_value - expected_value)
                    > max(Decimal("1"), abs(expected_value)) * Decimal("1e-30")
                ):
                    failures.append(f"{company_id}:{operation}:{output_id}:value_mismatch")
            if not all(item["passed"] for item in receipt["invariant_results"]):
                failures.append(f"{company_id}:{operation}:failed_invariant_released")
        abstentions += len(report["abstentions"])
    if len(companies) != 20:
        failures.append(f"population:expected_20_found_{len(companies)}")
    if receipts != manifest["successful_receipts"]:
        failures.append("manifest:receipt_count_mismatch")
    if abstentions != manifest["typed_abstentions"]:
        failures.append("manifest:abstention_count_mismatch")
    return {
        "schema_version": SCHEMA_VERSION,
        "universe_id": manifest["universe_id"],
        "as_of": manifest["as_of"],
        "source_manifest_sha256": sha256(manifest_path),
        "companies": len(companies),
        "verified_receipts": receipts,
        "verified_abstentions": abstentions,
        "receipts_by_operation": dict(sorted(operation_counts.items())),
        "tolerance": "relative decimal difference <= 1e-30, with an absolute floor of 1e-30",
        "failures": failures,
        "passed": not failures,
        "claim_boundary": (
            "This independent Python implementation recomputes released formulas and verifies "
            "the simple-FCF naming boundary. It does not constitute accounting, source-rights, "
            "peer-comparability, valuation, or investment review."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--activation-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.activation_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not report["passed"]:
        raise SystemExit("financial activation reference check failed")
    print(
        f"financial reference check passed: {report['companies']} companies, "
        f"{report['verified_receipts']} receipts"
    )


if __name__ == "__main__":
    main()
