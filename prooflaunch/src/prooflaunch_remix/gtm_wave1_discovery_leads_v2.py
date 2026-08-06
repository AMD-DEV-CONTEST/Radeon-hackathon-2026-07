from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


SCHEMA = "ProofLaunchGTMWave1DiscoveryLeadLedgerV2"


class GTMWave1DiscoveryLeadError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def compile_wave1_discovery_leads(
    leads: Sequence[Mapping[str, Any]],
    capture_ledger: Mapping[str, Any],
) -> dict[str, Any]:
    captures = {str(row.get("source_url")): row for row in capture_ledger.get("records", [])}
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for lead in leads:
        lead_id = str(lead.get("lead_id") or "").strip()
        source_url = str(lead.get("source_url") or "").strip()
        if not lead_id or lead_id in seen_ids:
            raise GTMWave1DiscoveryLeadError("lead IDs must be present and unique")
        parsed = urlparse(source_url)
        if parsed.scheme != "https" or not parsed.netloc or source_url in seen_urls:
            raise GTMWave1DiscoveryLeadError(f"{lead_id} source URL is invalid or duplicated")
        seen_ids.add(lead_id)
        seen_urls.add(source_url)
        for field in ("company", "provisional_subvertical_id", "discovery_rationale", "source_class"):
            if not str(lead.get(field) or "").strip():
                raise GTMWave1DiscoveryLeadError(f"{lead_id} lacks {field}")
        capture = captures.get(source_url, {})
        captured = capture.get("capture_status") == "captured_metadata_only"
        records.append({
            "lead_id": lead_id,
            "status": "captured_pending_case_classification" if captured else "source_capture_gap",
            "company": str(lead["company"]),
            "provisional_subvertical_id": str(lead["provisional_subvertical_id"]),
            "provisional_company_scale": str(lead.get("provisional_company_scale") or "unresolved"),
            "discovery_rationale": str(lead["discovery_rationale"]),
            "source_url": source_url,
            "source_class": str(lead["source_class"]),
            "capture_status": str(capture.get("capture_status") or "not_attempted"),
            "capture_content_sha256": capture.get("content_sha256"),
            "capture_title": capture.get("title", ""),
            "observed_period_status": "unresolved",
            "budget_status": "unresolved",
            "market_status": "unresolved",
            "outcome_verification_status": "unresolved",
            "case_episode_status": "unresolved",
            "quota_credit": 0,
            "next_required_actions": [
                "inspect the captured source and bind exact claim excerpts",
                "resolve company scale, market, observed start/end, lifecycle, budget, recency, and outcome bucket",
                "resolve company and episode identity against the V2 identity ledger",
                "add an independent or first-party outcome source before mechanism promotion",
            ],
        })
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "source_capture_sha256": capture_ledger.get("content_sha256"),
        "lead_count": len(records),
        "captured_lead_count": sum(row["capture_status"] == "captured_metadata_only" for row in records),
        "source_capture_gap_count": sum(row["capture_status"] != "captured_metadata_only" for row in records),
        "distinct_provisional_subvertical_count": len({row["provisional_subvertical_id"] for row in records}),
        "records": records,
        "promotion_policy": {
            "discovery_or_metadata_capture_grants_candidate_credit": False,
            "missing_budget_or_observed_period_may_be_inferred": False,
            "vendor_case_study_alone_proves_causality": False,
            "human_source_inspection_required": True,
        },
        "truth_boundary": (
            "These are bounded public discovery leads, not V2 cases. They contribute zero quota credit until every required "
            "classification and identity field is resolved from captured evidence."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_wave1_discovery_leads(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMWave1DiscoveryLeadError("discovery lead ledger seal is invalid")
    records = payload.get("records")
    if not isinstance(records, list) or payload.get("lead_count") != len(records):
        raise GTMWave1DiscoveryLeadError("lead aggregate drifted")
    if len({row.get("lead_id") for row in records}) != len(records):
        raise GTMWave1DiscoveryLeadError("lead IDs are duplicated")
    if len({row.get("source_url") for row in records}) != len(records):
        raise GTMWave1DiscoveryLeadError("lead source URLs are duplicated")
    if any(row.get("quota_credit") != 0 for row in records):
        raise GTMWave1DiscoveryLeadError("a discovery lead received quota credit")
    captured = sum(row.get("capture_status") == "captured_metadata_only" for row in records)
    if payload.get("captured_lead_count") != captured:
        raise GTMWave1DiscoveryLeadError("captured lead aggregate drifted")


__all__ = [
    "GTMWave1DiscoveryLeadError",
    "compile_wave1_discovery_leads",
    "verify_wave1_discovery_leads",
]
