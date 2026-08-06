from __future__ import annotations

from collections import Counter
import hashlib
import json
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

from .gtm_case_acquisition_matrix_v2 import verify_case_acquisition_matrix
from .gtm_case_evidence_funnel_v2 import verify_case_evidence_funnel_standard
from .gtm_gold_case_discovery_v2 import verify_gold_case_discovery


SCHEMA = "ProofLaunchGTMAllSubverticalDiscoveryV2"
ALLOWED_DISCOVERY_METHODS = {
    "operator_reviewed_public_search_result",
    "model_assisted_public_search_result",
    "sealed_gold_discovery_import",
}


class GTMAllSubverticalDiscoveryError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _canonical_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise GTMAllSubverticalDiscoveryError("only credential-free public HTTPS lead URLs are allowed")
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit(("https", parsed.netloc.casefold(), path, parsed.query, ""))


def _normalized_record(
    row: Mapping[str, Any],
    *,
    allowed_subverticals: set[str],
    origin: str,
) -> dict[str, Any]:
    url = _canonical_url(str(row.get("source_url") or ""))
    subvertical_ids = sorted(set(map(str, row.get("provisional_subvertical_ids", []))))
    if not set(subvertical_ids).issubset(allowed_subverticals):
        raise GTMAllSubverticalDiscoveryError(f"{url} references an unknown subvertical")
    method = str(row.get("discovery_method") or "sealed_gold_discovery_import")
    if method not in ALLOWED_DISCOVERY_METHODS:
        raise GTMAllSubverticalDiscoveryError(f"{url} has an unsupported discovery method")
    source_family_values = row.get("source_family_ids")
    if not isinstance(source_family_values, list):
        source_family_values = [row.get("source_family_id")]
    normalized = {
        "lead_id": "all-lead-" + _digest(url)[:16],
        "source_url": url,
        "source_family_ids": sorted({str(value) for value in source_family_values if value}),
        "source_record_origins": [origin],
        "discovery_method": method,
        "company": str(row.get("company") or "").strip(),
        "title": str(row.get("title") or "").strip(),
        "directory_industry": str(row.get("directory_industry") or "").strip(),
        "source_excerpt": str(row.get("source_excerpt") or "").strip()[:1_200],
        "provisional_subvertical_ids": subvertical_ids,
        "status": "discovery_lead_only",
        "human_classification_required": True,
        "formal_candidate_quota_credit": 0,
        "automatic_promotion_allowed": False,
    }
    if len(normalized["title"]) < 4:
        raise GTMAllSubverticalDiscoveryError(f"{url} lacks a usable title")
    return normalized


def build_all_subvertical_discovery(
    standard: Mapping[str, Any],
    acquisition_matrix: Mapping[str, Any],
    gold_discovery: Mapping[str, Any],
    targeted_lead_sets: Sequence[tuple[str, Sequence[Mapping[str, Any]]]],
) -> dict[str, Any]:
    verify_case_evidence_funnel_standard(standard)
    verify_case_acquisition_matrix(acquisition_matrix)
    verify_gold_case_discovery(gold_discovery)
    allowed = {str(row["subvertical_id"]) for row in standard["subverticals"]}

    by_url: dict[str, dict[str, Any]] = {}
    for row in gold_discovery["records"]:
        normalized = _normalized_record(row, allowed_subverticals=allowed, origin="gtm-gold-case-discovery-v2")
        by_url[normalized["source_url"]] = normalized
    for origin, rows in targeted_lead_sets:
        for row in rows:
            normalized = _normalized_record(row, allowed_subverticals=allowed, origin=origin)
            prior = by_url.get(normalized["source_url"])
            if prior is None:
                by_url[normalized["source_url"]] = normalized
                continue
            prior["source_family_ids"] = sorted(set(prior["source_family_ids"]) | set(normalized["source_family_ids"]))
            prior["source_record_origins"] = sorted(set(prior["source_record_origins"]) | set(normalized["source_record_origins"]))
            prior["provisional_subvertical_ids"] = sorted(
                set(prior["provisional_subvertical_ids"]) | set(normalized["provisional_subvertical_ids"])
            )
            # Later evidence layers may resolve a company candidate or add an exact,
            # capture-bound routing explanation for the same canonical URL. Preserve the
            # strongest non-empty metadata without changing its provisional zero-credit state.
            if normalized["company"] and not prior["company"]:
                prior["company"] = normalized["company"]
            if len(normalized["title"]) > len(prior["title"]):
                prior["title"] = normalized["title"]
            if len(normalized["source_excerpt"]) > len(prior["source_excerpt"]):
                prior["source_excerpt"] = normalized["source_excerpt"]
            if (
                prior["directory_industry"].startswith("public_case_")
                and normalized["directory_industry"]
                and not normalized["directory_industry"].endswith("unclassified")
            ):
                prior["directory_industry"] = normalized["directory_industry"]

    records = sorted(by_url.values(), key=lambda row: row["lead_id"])
    route_counts: Counter[str] = Counter()
    for record in records:
        route_counts.update(record["provisional_subvertical_ids"])
    subvertical_rows = []
    for row in standard["subverticals"]:
        subvertical_id = str(row["subvertical_id"])
        count = route_counts[subvertical_id]
        subvertical_rows.append({
            "subvertical_id": subvertical_id,
            "business_model": row["business_model"],
            "vertical": row["vertical"],
            "subvertical": row["subvertical"],
            "provisional_discovery_route_count": count,
            "formal_candidate_count": 0,
            "formal_candidate_gap": 200,
            "status": "coverage_gap",
        })

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "standard_sha256": standard["content_sha256"],
        "acquisition_matrix_sha256": acquisition_matrix["content_sha256"],
        "gold_discovery_sha256": gold_discovery["content_sha256"],
        "unique_discovery_lead_count": len(records),
        "provisionally_routed_lead_count": sum(bool(row["provisional_subvertical_ids"]) for row in records),
        "provisional_route_assignment_count": sum(len(row["provisional_subvertical_ids"]) for row in records),
        "subverticals_with_provisional_routes": sum(row["provisional_discovery_route_count"] > 0 for row in subvertical_rows),
        "subverticals_without_provisional_routes": sum(row["provisional_discovery_route_count"] == 0 for row in subvertical_rows),
        "formal_candidate_count": 0,
        "formal_candidate_gap": 16_200,
        "records": records,
        "subverticals": subvertical_rows,
        "truth_boundary": (
            "This is a cross-81-subvertical public discovery ledger. Leads, vendor claims, search excerpts and provisional "
            "routes grant zero CaseCandidateV2 credit until named human source inspection and independent admission pass."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_all_subvertical_discovery(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMAllSubverticalDiscoveryError("all-subvertical discovery seal is invalid")
    records = payload.get("records")
    subverticals = payload.get("subverticals")
    if not isinstance(records, list) or payload.get("unique_discovery_lead_count") != len(records):
        raise GTMAllSubverticalDiscoveryError("lead aggregate drifted")
    if not isinstance(subverticals, list) or len(subverticals) != 81:
        raise GTMAllSubverticalDiscoveryError("all 81 subvertical rows are required")
    urls = [row.get("source_url") for row in records]
    if len(urls) != len(set(urls)):
        raise GTMAllSubverticalDiscoveryError("duplicate source URLs escaped canonical deduplication")
    if any(
        row.get("status") != "discovery_lead_only"
        or row.get("human_classification_required") is not True
        or row.get("formal_candidate_quota_credit") != 0
        or row.get("automatic_promotion_allowed") is not False
        for row in records
    ):
        raise GTMAllSubverticalDiscoveryError("a discovery lead escaped the zero-credit review boundary")
    expected_routed = sum(bool(row.get("provisional_subvertical_ids")) for row in records)
    expected_routes = sum(len(row.get("provisional_subvertical_ids", [])) for row in records)
    if payload.get("provisionally_routed_lead_count") != expected_routed:
        raise GTMAllSubverticalDiscoveryError("routed lead aggregate drifted")
    if payload.get("provisional_route_assignment_count") != expected_routes:
        raise GTMAllSubverticalDiscoveryError("route assignment aggregate drifted")
    if payload.get("formal_candidate_count") != 0 or payload.get("formal_candidate_gap") != 16_200:
        raise GTMAllSubverticalDiscoveryError("discovery leads were misreported as formal candidates")
    if any(row.get("formal_candidate_count") != 0 or row.get("formal_candidate_gap") != 200 for row in subverticals):
        raise GTMAllSubverticalDiscoveryError("a subvertical row escaped the formal candidate gap")


__all__ = [
    "GTMAllSubverticalDiscoveryError",
    "build_all_subvertical_discovery",
    "verify_all_subvertical_discovery",
]
