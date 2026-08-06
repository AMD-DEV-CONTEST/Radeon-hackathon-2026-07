from __future__ import annotations

from collections import Counter
import hashlib
import json
from typing import Any, Mapping

from .gtm_all_subvertical_discovery_v2 import verify_all_subvertical_discovery


SCHEMA = "ProofLaunchGTMDiscoveryDeltaV2"


class GTMDiscoveryDeltaError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def build_discovery_delta(current: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict[str, Any]:
    verify_all_subvertical_discovery(current)
    verify_all_subvertical_discovery(baseline)
    baseline_urls = {str(row["source_url"]) for row in baseline["records"]}
    records = [dict(row) for row in current["records"] if str(row["source_url"]) not in baseline_urls]
    records.sort(key=lambda row: row["lead_id"])
    origin_counts: Counter[str] = Counter()
    for row in records:
        origin_counts.update(map(str, row.get("source_record_origins", [])))
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "current_discovery_sha256": current["content_sha256"],
        "baseline_discovery_sha256": baseline["content_sha256"],
        "baseline_unique_lead_count": baseline["unique_discovery_lead_count"],
        "current_unique_lead_count": current["unique_discovery_lead_count"],
        "new_unique_lead_count": len(records),
        "source_origin_counts": dict(sorted(origin_counts.items())),
        "records": records,
        "formal_candidate_quota_credit": 0,
        "automatic_promotion_allowed": False,
        "truth_boundary": (
            "This is an exact URL delta prepared for bounded public metadata capture. Delta membership, enumeration and "
            "capture do not prove a CaseCandidateV2 episode and grant zero formal candidate quota credit."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_discovery_delta(
    payload: Mapping[str, Any],
    current: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> None:
    verify_all_subvertical_discovery(current)
    verify_all_subvertical_discovery(baseline)
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMDiscoveryDeltaError("discovery delta seal is invalid")
    if payload.get("current_discovery_sha256") != current.get("content_sha256"):
        raise GTMDiscoveryDeltaError("discovery delta is stale against current discovery")
    if payload.get("baseline_discovery_sha256") != baseline.get("content_sha256"):
        raise GTMDiscoveryDeltaError("discovery delta is stale against its baseline")
    records = payload.get("records")
    if not isinstance(records, list) or payload.get("new_unique_lead_count") != len(records):
        raise GTMDiscoveryDeltaError("discovery delta aggregate drifted")
    expected_urls = {str(row["source_url"]) for row in current["records"]} - {
        str(row["source_url"]) for row in baseline["records"]
    }
    actual_urls = {str(row.get("source_url")) for row in records}
    if len(actual_urls) != len(records) or actual_urls != expected_urls:
        raise GTMDiscoveryDeltaError("discovery delta URL partition drifted")
    if payload.get("formal_candidate_quota_credit") != 0 or payload.get("automatic_promotion_allowed") is not False:
        raise GTMDiscoveryDeltaError("discovery delta escaped zero-credit mode")
    if any(
        row.get("formal_candidate_quota_credit") != 0
        or row.get("automatic_promotion_allowed") is not False
        or row.get("human_classification_required") is not True
        for row in records
    ):
        raise GTMDiscoveryDeltaError("a delta lead escaped provisional review")


__all__ = ["GTMDiscoveryDeltaError", "build_discovery_delta", "verify_discovery_delta"]
