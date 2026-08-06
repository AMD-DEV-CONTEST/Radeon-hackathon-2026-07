from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
from typing import Any, Mapping

from .gtm_all_subvertical_unified_review_v2 import verify_unified_review_ledger


SCHEMA = "ProofLaunchGTMAdmissionAccelerationQueueV2"


class GTMAdmissionAccelerationQueueError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_admission_acceleration_queue(ledger: Mapping[str, Any]) -> dict[str, Any]:
    verify_unified_review_ledger(ledger)
    rows = []
    for packet in ledger["records"]:
        if not packet["machine_ready_for_named_review"]:
            continue
        text = f"{packet.get('title', '')} {packet.get('source_excerpt', '')}"
        quantitative = bool(re.search(r"(?:\$\s?\d|\d[\d,.]*\s?%|\b\d+(?:\.\d+)?[KMB]\b|\bARR\b|\bMRR\b|\brevenue\b)", text, re.I))
        high_transparency = "high-transparency-public-leads-wave8-v2.json" in packet.get("origin_source", "")
        if high_transparency:
            lane, score = "p0_high_transparency", 100
        elif quantitative and packet["origin_kind"] == "gold_candidate_binding_packet":
            lane, score = "p1_quantified_gold", 85
        elif quantitative:
            lane, score = "p1_quantified_targeted", 75
        else:
            lane, score = "p2_identity_ready", 55
        rows.append({
            "acceleration_task_id": "admission-" + _digest(packet["review_packet_id"])[:18],
            "review_packet_id": packet["review_packet_id"],
            "review_packet_sha256": _digest(packet),
            "source_url": packet["source_url"],
            "company": packet["company"],
            "title": packet["title"],
            "provisional_subvertical_ids": packet["provisional_subvertical_ids"],
            "priority_lane": lane,
            "priority_score": score,
            "quantitative_signal_present": quantitative,
            "required_closure_sequence": [
                "named_source_inspection_and_exact_field_binding",
                "independent_outcome_source_capture",
                "six_component_cost_binding_or_bounded_estimation",
                "entity_episode_and_cross_platform_duplicate_review",
                "casecandidate_v2_admission_submission",
            ],
            "independent_discovery_queries": packet["corroboration_queries"],
            "observed_named_human_review_count": 0,
            "formal_candidate_quota_credit": 0,
            "automatic_promotion_allowed": False,
        })
    rows.sort(key=lambda row: (-row["priority_score"], row["provisional_subvertical_ids"], row["acceleration_task_id"]))
    lanes = Counter(row["priority_lane"] for row in rows)
    routes = Counter(route for row in rows for route in row["provisional_subvertical_ids"])
    payload = {
        "schema": SCHEMA,
        "source_unified_review_ledger_sha256": ledger["content_sha256"],
        "task_count": len(rows),
        "priority_lane_counts": dict(sorted(lanes.items())),
        "represented_subvertical_count": len(routes),
        "subvertical_task_counts": dict(sorted(routes.items())),
        "observed_named_human_review_count": 0,
        "formal_candidate_quota_credit": 0,
        "automatic_promotion_allowed": False,
        "records": rows,
        "truth_boundary": "Priority compresses time-to-review; it does not verify a claim or mint a case. Every task remains bound to the sealed unified packet and must pass the independent admission gate.",
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_admission_acceleration_queue(payload: Mapping[str, Any], ledger: Mapping[str, Any]) -> None:
    verify_unified_review_ledger(ledger)
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMAdmissionAccelerationQueueError("admission acceleration queue seal is invalid")
    if payload.get("source_unified_review_ledger_sha256") != ledger["content_sha256"]:
        raise GTMAdmissionAccelerationQueueError("admission acceleration queue is stale")
    records = payload.get("records")
    if not isinstance(records, list) or payload.get("task_count") != len(records):
        raise GTMAdmissionAccelerationQueueError("admission acceleration queue aggregate drifted")
    expected = {row["review_packet_id"] for row in ledger["records"] if row["machine_ready_for_named_review"]}
    observed = {row.get("review_packet_id") for row in records}
    if expected != observed or len(observed) != len(records):
        raise GTMAdmissionAccelerationQueueError("admission acceleration queue does not exactly cover ready packets")
    if payload.get("formal_candidate_quota_credit") != 0 or payload.get("automatic_promotion_allowed") is not False:
        raise GTMAdmissionAccelerationQueueError("admission acceleration queue escaped zero-credit mode")
    packet_map = {row["review_packet_id"]: row for row in ledger["records"]}
    for row in records:
        packet = packet_map[row["review_packet_id"]]
        if row.get("review_packet_sha256") != _digest(packet):
            raise GTMAdmissionAccelerationQueueError("admission acceleration packet binding drifted")
        if row.get("formal_candidate_quota_credit") != 0 or row.get("automatic_promotion_allowed") is not False:
            raise GTMAdmissionAccelerationQueueError("admission acceleration record minted quota")


__all__ = ["GTMAdmissionAccelerationQueueError", "build_admission_acceleration_queue", "verify_admission_acceleration_queue"]
