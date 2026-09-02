#!/usr/bin/env python3
"""Stream-audit the frozen Technology 20 SEC-derived authority without republishing facts."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = "signalforge/technology20-data-authority-audit/v2"
FRESHNESS_POLICY = "sec-periodic-filing-age-180d/v1"
SEMANTIC_MAPPING_POLICY = "sec-companyfacts-semantic-mapping-review/v1"
COMPANY_PREFIX = "sec-cik:"


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def records(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path.name}:{line_number}: invalid JSON: {error}") from error


def period_shape_valid(period_type: str, start: datetime, end: datetime) -> bool:
    return (period_type == "duration" and start < end) or (
        period_type == "instant" and start == end
    )


def normalized_source_lineage_valid(
    item: dict[str, Any],
    unit: str,
    period_type: str,
    available: datetime,
    fact_authority: dict[str, tuple[str, str, str, datetime]],
) -> bool:
    source_fact_ids = item.get("source_fact_ids") or []
    source_facts = [fact_authority.get(fact_id) for fact_id in source_fact_ids]
    return (
        bool(source_facts)
        and all(source_facts)
        and all(source[0] == item.get("company_id") for source in source_facts if source)
        and all(source[1] == unit for source in source_facts if source)
        and all(source[2] == period_type for source in source_facts if source)
        and max(source[3] for source in source_facts if source) == available
    )


def audit(root: Path, coverage: Path) -> dict[str, Any]:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    as_of = parse_time(manifest["as_of"])
    expected_files = manifest["files"]
    validation_errors: list[str] = []
    verified_hashes: dict[str, str] = {}
    for name, expected in sorted(expected_files.items()):
        path = root / name
        actual = sha256(path)
        verified_hashes[name] = actual
        if actual != expected:
            validation_errors.append(f"{name}:sha256_mismatch")

    companies: dict[str, dict[str, Any]] = {}
    for item in records(root / "companies.jsonl"):
        company_id = item.get("company_id", "")
        cik = item.get("cik", "")
        if (
            not company_id.startswith(COMPANY_PREFIX)
            or company_id != COMPANY_PREFIX + cik
            or len(cik) != 10
            or company_id in companies
            or not item.get("legal_name")
            or not item.get("source_record_ids")
        ):
            validation_errors.append(f"companies:{company_id or 'unknown'}:identity_invalid")
            continue
        companies[company_id] = item

    filing_ids: set[str] = set()
    accession_ids: set[str] = set()
    filing_forms: dict[str, str] = {}
    amendment_edges: dict[str, str] = {}
    latest_periodic: dict[str, dict[str, Any]] = {}
    excluded_non_operating_collisions: list[dict[str, str]] = []
    filing_count = 0
    for item in records(root / "filings.jsonl"):
        filing_count += 1
        filing_id = item.get("filing_id", "")
        company_id = item.get("company_id", "")
        accession = item.get("accession_number", "")
        try:
            accepted = parse_time(item["accepted_at"])
            published = parse_time(item["published_at"])
            retrieved = parse_time(item["retrieved_at"])
            report_end = parse_time(item["report_period_end"])
        except (KeyError, ValueError, TypeError):
            validation_errors.append(f"filings:{filing_id or filing_count}:timestamp_invalid")
            continue
        duplicate_identity = filing_id in filing_ids or accession in accession_ids
        form_type = item.get("form_type", "")
        periodic = form_type in {"10-K", "10-Q", "10-K/A", "10-Q/A"}
        prior_periodic = filing_forms.get(filing_id) in {"10-K", "10-Q", "10-K/A", "10-Q/A"}
        if duplicate_identity and not periodic and not prior_periodic:
            excluded_non_operating_collisions.append(
                {
                    "filing_id": filing_id,
                    "accession_number": accession,
                    "form_type": form_type,
                    "reason": "same third-party ownership filing appears in multiple issuer submission histories",
                }
            )
        if (
            company_id not in companies
            or (duplicate_identity and (periodic or prior_periodic))
            or not item.get("source_uri")
            or not item.get("content_sha256")
            or published < accepted
            or retrieved < published
            or report_end > as_of
        ):
            validation_errors.append(f"filings:{filing_id or filing_count}:contract_invalid")
        filing_ids.add(filing_id)
        accession_ids.add(accession)
        filing_forms.setdefault(filing_id, form_type)
        if item.get("amends_filing_id"):
            amendment_edges[filing_id] = item["amends_filing_id"]
        if periodic and published <= as_of:
            previous = latest_periodic.get(company_id)
            if previous is None or parse_time(previous["published_at"]) < published:
                latest_periodic[company_id] = item

    for child, parent in amendment_edges.items():
        if parent not in filing_ids or child == parent:
            validation_errors.append(f"filings:{child}:amendment_lineage_invalid")

    fact_ids: set[str] = set()
    fact_authority: dict[str, tuple[str, str, str, datetime]] = {}
    fact_count = 0
    raw_scale_count = 0
    raw_unit_counts: Counter[str] = Counter()
    for item in records(root / "reported_facts.jsonl"):
        fact_count += 1
        fact_id = item.get("fact_id", "")
        try:
            available = parse_time(item["available_at"])
            retrieved = parse_time(item["retrieved_at"])
            value = Decimal(item["value"])
        except (KeyError, ValueError):
            validation_errors.append(f"reported_facts:{fact_id or fact_count}:timestamp_invalid")
            continue
        except InvalidOperation:
            validation_errors.append(f"reported_facts:{fact_id or fact_count}:value_invalid")
            continue
        duration = bool(item.get("start_date") or item.get("end_date"))
        instant = bool(item.get("instant_date"))
        if duration:
            try:
                start, end = parse_time(item["start_date"]), parse_time(item["end_date"])
                period_valid = start <= end <= available
            except (KeyError, ValueError):
                period_valid = False
        elif instant:
            try:
                period_valid = parse_time(item["instant_date"]) <= available
            except ValueError:
                period_valid = False
        else:
            period_valid = False
        scale = item.get("scale")
        unit = item.get("unit", "")
        if (
            fact_id in fact_ids
            or item.get("company_id") not in companies
            or item.get("filing_id") not in filing_ids
            or not value.is_finite()
            or not item.get("taxonomy")
            or not item.get("concept")
            or not unit
            or isinstance(scale, bool)
            or not isinstance(scale, int)
            or not item.get("source_context_id")
            or not item.get("source_locator")
            or duration == instant
            or not period_valid
            or available > as_of
            or retrieved < available
        ):
            validation_errors.append(f"reported_facts:{fact_id or fact_count}:contract_invalid")
        fact_ids.add(fact_id)
        fact_authority[fact_id] = (
            item.get("company_id", ""),
            unit,
            "duration" if duration else "instant",
            available,
        )
        raw_scale_count += int(isinstance(scale, int) and not isinstance(scale, bool))
        raw_unit_counts[unit] += 1

    metric_ids: set[str] = set()
    metric_count = 0
    metric_statuses: Counter[str] = Counter()
    metric_companies: Counter[str] = Counter()
    metric_statuses_by_company: dict[str, Counter[str]] = defaultdict(Counter)
    aliases_by_company_metric: dict[str, Counter[str]] = defaultdict(Counter)
    metric_contract_gaps: Counter[str] = Counter()
    normalized_lineage_checks: Counter[str] = Counter()
    for item in records(root / "normalized_metrics.jsonl"):
        metric_count += 1
        metric_id = item.get("metric_id", "")
        try:
            value = Decimal(item["value"])
            start = parse_time(item["period_start"])
            end = parse_time(item["period_end"])
            available = parse_time(item["source_available_at"])
            computed = parse_time(item["computed_at"])
        except (KeyError, ValueError, InvalidOperation):
            validation_errors.append(f"normalized_metrics:{metric_id or metric_count}:value_or_time_invalid")
            continue
        status = item.get("comparability_status", "")
        currency = item.get("currency", "")
        unit = item.get("unit", "")
        period_type = item.get("period_type", "")
        source_lineage_valid = normalized_source_lineage_valid(
            item, unit, period_type, available, fact_authority
        )
        valid_period_shape = period_shape_valid(period_type, start, end)
        if (
            metric_id in metric_ids
            or item.get("company_id") not in companies
            or not value.is_finite()
            or not valid_period_shape
            or end > available
            or available > as_of
            or computed < available
            or period_type not in {"instant", "duration"}
            or not source_lineage_valid
            or not item.get("transformation_id")
            or not item.get("normalization_policy_version")
            or status not in {"standardized", "concept_alias"}
            or not unit
            or (unit == "USD" and currency != "USD")
        ):
            validation_errors.append(f"normalized_metrics:{metric_id or metric_count}:contract_invalid")
        metric_ids.add(metric_id)
        metric_statuses[status] += 1
        company_id = item.get("company_id", "")
        metric_companies[company_id] += 1
        metric_statuses_by_company[company_id][status] += 1
        normalized_lineage_checks["source_fact_refs_valid"] += int(source_lineage_valid)
        normalized_lineage_checks["period_shape_valid"] += int(valid_period_shape)
        normalized_lineage_checks["unit_and_currency_valid"] += int(
            bool(unit) and (unit != "USD" or currency == "USD")
        )
        if status == "concept_alias":
            aliases_by_company_metric[company_id][item.get("canonical_metric", "")] += 1
        for field in ("sign_policy", "dimensions", "accounting_perimeter", "taxonomy_concept"):
            if field not in item:
                metric_contract_gaps[field] += 1

    issue_count = sum(1 for _ in records(root / "issues.jsonl"))
    freshness: list[dict[str, Any]] = []
    stale_companies = 0
    for company_id, company in sorted(companies.items()):
        latest = latest_periodic.get(company_id)
        if latest is None:
            status, age_days, form, published_at = "missing", None, None, None
            stale_companies += 1
        else:
            published = parse_time(latest["published_at"])
            age_days = (as_of - published).days
            status = "fresh" if age_days <= 180 else "stale"
            stale_companies += int(status == "stale")
            form, published_at = latest["form_type"], latest["published_at"]
        freshness.append(
            {
                "company_id": company_id,
                "display_name": company["legal_name"],
                "latest_periodic_form": form,
                "latest_periodic_published_at": published_at,
                "age_days": age_days,
                "status": status,
                "normalized_metric_records": metric_companies[company_id],
            }
        )

    if len(companies) != 20:
        validation_errors.append(f"population:expected_20_companies_found_{len(companies)}")
    semantic_mapping_review: list[dict[str, Any]] = []
    for company_id in sorted(companies):
        alias_counts = aliases_by_company_metric[company_id]
        semantic_mapping_review.append(
            {
                "company_id": company_id,
                "display_name": companies[company_id]["legal_name"],
                "standardized_records": metric_statuses_by_company[company_id]["standardized"],
                "concept_alias_records": metric_statuses_by_company[company_id]["concept_alias"],
                "alias_metrics": [
                    {"canonical_metric": metric, "records": count}
                    for metric, count in sorted(alias_counts.items())
                ],
                "disposition": (
                    "excluded_pending_named_semantic_review"
                    if alias_counts
                    else "no_alias_mapping_present"
                ),
            }
        )
    coverage_hash = sha256(coverage)
    return {
        "schema_version": SCHEMA_VERSION,
        "universe_id": "us-technology-20-v2",
        "as_of": manifest["as_of"],
        "generated_from_frozen_inputs_at": manifest["computed_at"],
        "source_manifest_sha256": sha256(manifest_path),
        "coverage_report_sha256": coverage_hash,
        "verified_file_hashes": verified_hashes,
        "counts": {
            "companies": len(companies),
            "filings": filing_count,
            "reported_facts": fact_count,
            "normalized_metrics": metric_count,
            "explicit_issues": issue_count,
        },
        "normalized_metric_comparability_states": dict(sorted(metric_statuses.items())),
        "semantic_mapping_policy": SEMANTIC_MAPPING_POLICY,
        "semantic_mapping_review": semantic_mapping_review,
        "semantic_mapping_summary": {
            "approved_alias_records": 0,
            "excluded_alias_records": metric_statuses["concept_alias"],
            "companies_with_excluded_aliases": sum(
                1 for item in semantic_mapping_review if item["concept_alias_records"] > 0
            ),
        },
        "normalized_metric_contract_gaps": dict(sorted(metric_contract_gaps.items())),
        "semantic_dimension_assurance": {
            "currency": {
                "status": "validated",
                "records": normalized_lineage_checks["unit_and_currency_valid"],
                "policy": "normalized USD units require USD currency; non-currency units remain explicit",
            },
            "scale": {
                "status": "source_validated_normalized_via_lineage",
                "reported_fact_records": raw_scale_count,
                "policy": "integer SEC source scale is preserved on facts; normalized values bind immutable source facts",
            },
            "unit": {
                "status": "validated",
                "normalized_records": normalized_lineage_checks["unit_and_currency_valid"],
                "source_units": dict(sorted(raw_unit_counts.items())),
                "policy": "every normalized metric unit equals every referenced source-fact unit",
            },
            "sign": {
                "status": "blocked_missing_contract_field",
                "blocked_records": metric_contract_gaps["sign_policy"],
                "policy": "finite numeric syntax is validated, but semantic sign interpretation is not promoted without sign_policy",
            },
            "period": {
                "status": "validated",
                "normalized_records": normalized_lineage_checks["period_shape_valid"],
                "policy": "duration requires start before end; instant requires equal boundaries; source type must match",
            },
            "segment": {
                "status": "blocked_missing_contract_field",
                "blocked_records": metric_contract_gaps["dimensions"],
                "policy": "segment interpretation is quarantined until dimensions are explicit",
            },
            "consolidation_scope": {
                "status": "blocked_missing_contract_field",
                "blocked_records": metric_contract_gaps["accounting_perimeter"],
                "policy": "consolidation claims are quarantined until accounting_perimeter is explicit",
            },
        },
        "normalized_lineage_checks": dict(sorted(normalized_lineage_checks.items())),
        "excluded_non_operating_filing_collisions": excluded_non_operating_collisions,
        "excluded_non_operating_filing_collision_count": len(excluded_non_operating_collisions),
        "freshness_policy": FRESHNESS_POLICY,
        "company_freshness": freshness,
        "stale_or_missing_companies": stale_companies,
        "validation_errors": validation_errors,
        "passed": not validation_errors,
        "claim_boundary": (
            "This streaming audit verifies frozen derived-file hashes, identities, point-in-time "
            "timestamps, period shape, units, source-fact joins, amendment references, normalized "
            "values, and source freshness. Every concept_alias record is excluded from promotion until a named "
            "semantic review approves its exact mapping. Missing sign, dimensional, perimeter, "
            "or source-concept fields remain explicit contract gaps. This audit does not establish "
            "footnote interpretation, metric applicability, standalone journey quality, or peer "
            "comparability."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--derived-root", type=Path, required=True)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.derived_root.resolve(), args.coverage.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not report["passed"]:
        raise SystemExit(f"data authority audit failed with {len(report['validation_errors'])} errors")
    print(
        f"technology20 data authority passed: {report['counts']['companies']} companies, "
        f"{report['counts']['reported_facts']} facts, {report['stale_or_missing_companies']} stale"
    )


if __name__ == "__main__":
    main()
