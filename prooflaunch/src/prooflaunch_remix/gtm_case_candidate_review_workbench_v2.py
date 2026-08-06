from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import json
from typing import Any, Mapping

from .gtm_case_candidate_binding_v2 import GATES, verify_case_candidate_binding_packets


INTAKE_SCHEMA = "ProofLaunchGTMCaseCandidateHumanReviewIntakeV2"
RECEIPT_SCHEMA = "ProofLaunchGTMCaseCandidateHumanReviewReceiptV2"
DECISIONS = {
    "needs_more_evidence",
    "reject_episode",
    "submit_for_admission_gate",
}
REQUIRED_FIELD_BINDINGS = (
    "company",
    "product",
    "campaign_or_motion",
    "primary_audience",
    "subvertical_ids",
    "company_scale",
    "observed_start",
    "observed_end",
    "recency_bucket",
    "quota_market",
    "lifecycle_state",
    "budget_tier",
    "outcome_type",
    "result_summary",
    "mechanism_summary",
)
SIX_COST_COMPONENTS = (
    "media",
    "people",
    "tools",
    "creator",
    "channel",
    "production",
)


class GTMCaseCandidateReviewError(ValueError):
    pass


def _canonical_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def packet_digest(packet: Mapping[str, Any]) -> str:
    return _canonical_digest(packet)


def _nonempty(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value) and all(isinstance(item, str) and item.strip() for item in value)
    return False


def _valid_datetime(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def validate_review_intake(
    intake: Mapping[str, Any],
    binding_packets: Mapping[str, Any],
) -> None:
    verify_case_candidate_binding_packets(binding_packets)
    if intake.get("schema") != INTAKE_SCHEMA:
        raise GTMCaseCandidateReviewError("review intake schema is invalid")
    if intake.get("binding_packet_set_sha256") != binding_packets.get("content_sha256"):
        raise GTMCaseCandidateReviewError("review intake is not bound to the current packet set")
    if intake.get("automatic_candidate_promotion_allowed") is not False:
        raise GTMCaseCandidateReviewError("review intake attempted automatic candidate promotion")
    if intake.get("candidate_quota_credit") != 0:
        raise GTMCaseCandidateReviewError("review intake attempted to mint candidate quota")
    records = intake.get("records")
    if not isinstance(records, list):
        raise GTMCaseCandidateReviewError("review intake records are invalid")
    if intake.get("review_count") != len(records):
        raise GTMCaseCandidateReviewError("review intake count drifted")
    if len({record.get("packet_id") for record in records}) != len(records):
        raise GTMCaseCandidateReviewError("review intake contains duplicate packet IDs")

    packets = {packet["packet_id"]: packet for packet in binding_packets["records"]}
    for record in records:
        packet_id = record.get("packet_id")
        packet = packets.get(packet_id)
        if packet is None:
            raise GTMCaseCandidateReviewError(f"unknown candidate packet: {packet_id}")
        if record.get("source_url") != packet.get("source_url"):
            raise GTMCaseCandidateReviewError(f"{packet_id} source URL drifted")
        if record.get("packet_sha256") != packet_digest(packet):
            raise GTMCaseCandidateReviewError(f"{packet_id} packet hash drifted")
        if not _nonempty(record.get("reviewer_name")):
            raise GTMCaseCandidateReviewError(f"{packet_id} lacks a named human reviewer")
        if not _valid_datetime(record.get("reviewed_at")):
            raise GTMCaseCandidateReviewError(f"{packet_id} review timestamp is invalid")
        if record.get("source_inspected") is not True:
            raise GTMCaseCandidateReviewError(f"{packet_id} source was not inspected")
        decision = record.get("decision")
        if decision not in DECISIONS:
            raise GTMCaseCandidateReviewError(f"{packet_id} review decision is invalid")
        gates = record.get("gate_decisions")
        if not isinstance(gates, Mapping) or set(gates) != set(GATES):
            raise GTMCaseCandidateReviewError(f"{packet_id} review gate set drifted")
        if not all(isinstance(gates[gate], bool) for gate in GATES):
            raise GTMCaseCandidateReviewError(f"{packet_id} review gates must be explicit booleans")
        if record.get("automatic_candidate_promotion_allowed") is not False:
            raise GTMCaseCandidateReviewError(f"{packet_id} escaped fail-closed review")
        if record.get("candidate_quota_credit") != 0:
            raise GTMCaseCandidateReviewError(f"{packet_id} minted quota during review")

        if decision == "submit_for_admission_gate":
            if not all(gates.values()):
                raise GTMCaseCandidateReviewError(f"{packet_id} admission submission has failed gates")
            fields = record.get("field_bindings")
            if not isinstance(fields, Mapping) or set(fields) != set(REQUIRED_FIELD_BINDINGS):
                raise GTMCaseCandidateReviewError(f"{packet_id} field binding set drifted")
            missing = [name for name in REQUIRED_FIELD_BINDINGS if not _nonempty(fields[name])]
            if missing:
                raise GTMCaseCandidateReviewError(
                    f"{packet_id} admission submission lacks field bindings: {', '.join(missing)}"
                )
            costs = record.get("cost_components")
            if not isinstance(costs, Mapping) or set(costs) != set(SIX_COST_COMPONENTS):
                raise GTMCaseCandidateReviewError(f"{packet_id} six-component cost binding drifted")
            if not all(_nonempty(costs[name]) for name in SIX_COST_COMPONENTS):
                raise GTMCaseCandidateReviewError(f"{packet_id} has incomplete cost evidence")
            bindings = record.get("exact_claim_bindings")
            if not isinstance(bindings, list) or not bindings:
                raise GTMCaseCandidateReviewError(f"{packet_id} lacks exact claim bindings")
            for binding in bindings:
                if not isinstance(binding, Mapping):
                    raise GTMCaseCandidateReviewError(f"{packet_id} exact claim binding is invalid")
                required = ("field", "source_url", "exact_excerpt", "excerpt_sha256")
                if any(not _nonempty(binding.get(name)) for name in required):
                    raise GTMCaseCandidateReviewError(f"{packet_id} exact claim binding is incomplete")
                expected = hashlib.sha256(binding["exact_excerpt"].encode("utf-8")).hexdigest()
                if binding["excerpt_sha256"] != expected:
                    raise GTMCaseCandidateReviewError(f"{packet_id} exact excerpt hash drifted")
        elif not _nonempty(record.get("decision_notes")):
            raise GTMCaseCandidateReviewError(f"{packet_id} non-admission decision lacks notes")


def compile_review_receipt(
    intake: Mapping[str, Any],
    binding_packets: Mapping[str, Any],
) -> dict[str, Any]:
    validate_review_intake(intake, binding_packets)
    decisions = Counter(record["decision"] for record in intake["records"])
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "binding_packet_set_sha256": binding_packets["content_sha256"],
        "review_intake_sha256": _canonical_digest(intake),
        "review_count": len(intake["records"]),
        "decision_counts": dict(sorted(decisions.items())),
        "admission_submission_count": decisions.get("submit_for_admission_gate", 0),
        "candidate_quota_credit": 0,
        "automatic_candidate_promotion_allowed": False,
        "next_gate": (
            "Independent CaseCandidateV2 admission must re-check identity, episode deduplication, "
            "source independence, exact budget evidence and marginal quotas. This receipt never grants quota."
        ),
        "records": [
            {
                "packet_id": record["packet_id"],
                "packet_sha256": record["packet_sha256"],
                "reviewer_name": record["reviewer_name"],
                "reviewed_at": record["reviewed_at"],
                "decision": record["decision"],
                "candidate_quota_credit": 0,
            }
            for record in intake["records"]
        ],
        "truth_boundary": (
            "This receipt proves that named humans completed source-bound intake records. It does not prove the "
            "underlying claims, causal effect, independent outcome, deduplication, marginal quota fit or candidate admission."
        ),
    }
    receipt["content_sha256"] = _canonical_digest(receipt)
    return receipt


def verify_review_receipt(receipt: Mapping[str, Any]) -> None:
    unsigned = dict(receipt)
    supplied = unsigned.pop("content_sha256", None)
    if receipt.get("schema") != RECEIPT_SCHEMA or supplied != _canonical_digest(unsigned):
        raise GTMCaseCandidateReviewError("review receipt seal is invalid")
    if receipt.get("candidate_quota_credit") != 0:
        raise GTMCaseCandidateReviewError("review receipt minted quota")
    if receipt.get("automatic_candidate_promotion_allowed") is not False:
        raise GTMCaseCandidateReviewError("review receipt escaped fail-closed mode")
    records = receipt.get("records")
    if not isinstance(records, list) or receipt.get("review_count") != len(records):
        raise GTMCaseCandidateReviewError("review receipt aggregate drifted")
    if any(record.get("candidate_quota_credit") != 0 for record in records):
        raise GTMCaseCandidateReviewError("review receipt record minted quota")


__all__ = [
    "DECISIONS",
    "GTMCaseCandidateReviewError",
    "INTAKE_SCHEMA",
    "RECEIPT_SCHEMA",
    "REQUIRED_FIELD_BINDINGS",
    "SIX_COST_COMPONENTS",
    "compile_review_receipt",
    "packet_digest",
    "validate_review_intake",
    "verify_review_receipt",
]
