from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import json
from typing import Any, Mapping, Sequence

from .gtm_all_subvertical_review_queue_v2 import verify_all_subvertical_review_queue
from .gtm_case_candidate_binding_v2 import GATES, verify_case_candidate_binding_packets
from .gtm_case_candidate_review_workbench_v2 import (
    DECISIONS,
    REQUIRED_FIELD_BINDINGS,
    SIX_COST_COMPONENTS,
    packet_digest,
)


LEDGER_SCHEMA = "ProofLaunchGTMAllSubverticalUnifiedReviewLedgerV2"
INTAKE_SCHEMA = "ProofLaunchGTMAllSubverticalUnifiedReviewIntakeV2"
RECEIPT_SCHEMA = "ProofLaunchGTMAllSubverticalUnifiedReviewReceiptV2"


class GTMAllSubverticalUnifiedReviewError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


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


def build_unified_review_ledger(
    binding_packets: Mapping[str, Any],
    targeted_queues: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    verify_case_candidate_binding_packets(binding_packets)
    for queue in targeted_queues:
        verify_all_subvertical_review_queue(queue)

    records: list[dict[str, Any]] = []
    for packet in binding_packets["records"]:
        proposed = packet["proposed_fields"]
        records.append({
            "review_packet_id": "unified-" + _digest("gold:" + packet["packet_id"])[:20],
            "origin_kind": "gold_candidate_binding_packet",
            "origin_source": "evidence/v10/gtm-case-candidate-binding-packets-v2.json",
            "origin_id": packet["packet_id"],
            "origin_ledger_sha256": binding_packets["content_sha256"],
            "origin_packet_sha256": packet_digest(packet),
            "source_url": packet["source_url"],
            "company": proposed["company"]["value"],
            "title": proposed["campaign_or_motion"]["value"],
            "source_excerpt": " | ".join(
                fragment["bounded_exact_excerpt"]
                for fragments in packet["claim_fragments"].values()
                for fragment in fragments
            ),
            "provisional_subvertical_ids": proposed["subvertical_ids"]["value"],
            "machine_ready_for_named_review": packet["machine_ready_for_human_binding"],
            "status": "ready_for_named_review" if packet["machine_ready_for_human_binding"] else "evidence_gap",
            "source_capture_status": packet["capture_receipt"]["capture_status"],
            "source_capture_sha256": packet["capture_receipt"]["content_sha256"],
            "candidate_gate_blockers": packet["blocking_requirements"],
            "review_priority_score": packet["review_priority_score"],
            "proposed_field_values": {
                name: proposed.get(name, {}).get("value", "") for name in REQUIRED_FIELD_BINDINGS
            },
            "claim_fragments": packet["claim_fragments"],
            "corroboration_queries": packet["independent_discovery_queries"],
            "human_source_inspection_completed": False,
            "named_reviewer": None,
            "formal_candidate_quota_credit": 0,
            "automatic_promotion_allowed": False,
        })

    for queue in targeted_queues:
        for packet in queue["records"]:
            records.append({
                "review_packet_id": "unified-" + _digest(queue["source_origin"] + ":" + packet["review_item_id"])[:20],
                "origin_kind": "targeted_subvertical_review_packet",
                "origin_source": queue["source_origin"],
                "origin_id": packet["review_item_id"],
                "origin_ledger_sha256": queue["content_sha256"],
                "origin_packet_sha256": packet["packet_sha256"],
                "source_url": packet["source_url"],
                "company": packet["company"],
                "title": packet["title"],
                "source_excerpt": packet["source_excerpt"],
                "provisional_subvertical_ids": packet["provisional_subvertical_ids"],
                "machine_ready_for_named_review": packet["machine_ready_for_named_review"],
                "status": packet["status"],
                "source_capture_status": packet["source_capture_status"],
                "source_capture_sha256": packet["source_capture_content_sha256"],
                "candidate_gate_blockers": packet["candidate_gate_blockers"],
                "review_priority_score": 70 if packet["machine_ready_for_named_review"] else 20,
                "proposed_field_values": {
                    "company": packet["company"],
                    "product": "",
                    "campaign_or_motion": packet["title"],
                    "primary_audience": "",
                    "subvertical_ids": packet["provisional_subvertical_ids"],
                    "company_scale": "",
                    "observed_start": "",
                    "observed_end": "",
                    "recency_bucket": "",
                    "quota_market": "",
                    "lifecycle_state": "",
                    "budget_tier": "",
                    "outcome_type": "",
                    "result_summary": "",
                    "mechanism_summary": "",
                },
                "claim_fragments": {},
                "corroboration_queries": packet["corroboration_queries"],
                "human_source_inspection_completed": False,
                "named_reviewer": None,
                "formal_candidate_quota_credit": 0,
                "automatic_promotion_allowed": False,
            })

    records.sort(key=lambda row: (-row["review_priority_score"], row["review_packet_id"]))
    statuses = Counter(row["status"] for row in records)
    subverticals = sorted({route for row in records for route in row["provisional_subvertical_ids"]})
    origin_counts = Counter(row["origin_kind"] for row in records)
    payload: dict[str, Any] = {
        "schema": LEDGER_SCHEMA,
        "source_ledger_sha256s": [binding_packets["content_sha256"]] + [queue["content_sha256"] for queue in targeted_queues],
        "review_packet_count": len(records),
        "machine_ready_for_named_review_count": statuses["ready_for_named_review"],
        "evidence_gap_count": statuses["evidence_gap"],
        "represented_subvertical_count": len(subverticals),
        "represented_subvertical_ids": subverticals,
        "origin_counts": dict(sorted(origin_counts.items())),
        "observed_named_human_review_count": 0,
        "formal_candidate_quota_credit": 0,
        "automatic_promotion_allowed": False,
        "records": records,
        "truth_boundary": (
            "This ledger unifies source-bound review work, not admitted cases. Machine-ready means a named entity and a "
            "captured public surface are available for inspection. Every review, export and receipt remains zero-credit "
            "until independent CaseCandidateV2 admission rechecks all evidence and marginal quotas."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_unified_review_ledger(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != LEDGER_SCHEMA or supplied != _digest(unsigned):
        raise GTMAllSubverticalUnifiedReviewError("unified review ledger seal is invalid")
    records = payload.get("records")
    if not isinstance(records, list) or payload.get("review_packet_count") != len(records):
        raise GTMAllSubverticalUnifiedReviewError("unified review packet aggregate drifted")
    ids = [row.get("review_packet_id") for row in records]
    if len(ids) != len(set(ids)):
        raise GTMAllSubverticalUnifiedReviewError("unified review packet IDs are duplicated")
    statuses = Counter(row.get("status") for row in records)
    if payload.get("machine_ready_for_named_review_count") != statuses["ready_for_named_review"]:
        raise GTMAllSubverticalUnifiedReviewError("unified ready count drifted")
    if payload.get("evidence_gap_count") != statuses["evidence_gap"]:
        raise GTMAllSubverticalUnifiedReviewError("unified evidence-gap count drifted")
    routes = sorted({route for row in records for route in row.get("provisional_subvertical_ids", [])})
    if payload.get("represented_subvertical_ids") != routes or payload.get("represented_subvertical_count") != len(routes):
        raise GTMAllSubverticalUnifiedReviewError("unified subvertical coverage drifted")
    if payload.get("observed_named_human_review_count") != 0 or payload.get("formal_candidate_quota_credit") != 0:
        raise GTMAllSubverticalUnifiedReviewError("unified ledger fabricated review or candidate credit")
    if payload.get("automatic_promotion_allowed") is not False:
        raise GTMAllSubverticalUnifiedReviewError("unified ledger escaped fail-closed mode")
    for row in records:
        if (
            row.get("human_source_inspection_completed") is not False
            or row.get("named_reviewer") is not None
            or row.get("formal_candidate_quota_credit") != 0
            or row.get("automatic_promotion_allowed") is not False
            or row.get("status") not in {"ready_for_named_review", "evidence_gap"}
            or not row.get("source_url")
            or not row.get("origin_packet_sha256")
        ):
            raise GTMAllSubverticalUnifiedReviewError("unified review record escaped its evidence boundary")


def review_packet_digest(packet: Mapping[str, Any]) -> str:
    return _digest(packet)


def validate_unified_review_intake(intake: Mapping[str, Any], ledger: Mapping[str, Any]) -> None:
    verify_unified_review_ledger(ledger)
    if intake.get("schema") != INTAKE_SCHEMA:
        raise GTMAllSubverticalUnifiedReviewError("unified review intake schema is invalid")
    if intake.get("review_ledger_sha256") != ledger.get("content_sha256"):
        raise GTMAllSubverticalUnifiedReviewError("unified review intake is stale")
    if intake.get("automatic_promotion_allowed") is not False or intake.get("formal_candidate_quota_credit") != 0:
        raise GTMAllSubverticalUnifiedReviewError("unified review intake attempted promotion or quota minting")
    records = intake.get("records")
    if not isinstance(records, list) or intake.get("review_count") != len(records):
        raise GTMAllSubverticalUnifiedReviewError("unified review intake aggregate drifted")
    if len({row.get("review_packet_id") for row in records}) != len(records):
        raise GTMAllSubverticalUnifiedReviewError("unified review intake contains duplicate packets")
    packets = {row["review_packet_id"]: row for row in ledger["records"]}
    for row in records:
        packet = packets.get(row.get("review_packet_id"))
        if packet is None:
            raise GTMAllSubverticalUnifiedReviewError("unified review intake references an unknown packet")
        if row.get("source_url") != packet["source_url"] or row.get("review_packet_sha256") != review_packet_digest(packet):
            raise GTMAllSubverticalUnifiedReviewError("unified review packet binding drifted")
        if not _nonempty(row.get("reviewer_name")):
            raise GTMAllSubverticalUnifiedReviewError("unified review lacks a named human reviewer")
        if not _valid_datetime(row.get("reviewed_at")):
            raise GTMAllSubverticalUnifiedReviewError("unified review timestamp is invalid")
        if row.get("source_inspected") is not True:
            raise GTMAllSubverticalUnifiedReviewError("unified review source was not inspected")
        if row.get("decision") not in DECISIONS:
            raise GTMAllSubverticalUnifiedReviewError("unified review decision is invalid")
        if row.get("automatic_promotion_allowed") is not False or row.get("formal_candidate_quota_credit") != 0:
            raise GTMAllSubverticalUnifiedReviewError("unified review record attempted promotion or quota minting")
        gates = row.get("gate_decisions")
        if not isinstance(gates, Mapping) or set(gates) != set(GATES) or not all(isinstance(v, bool) for v in gates.values()):
            raise GTMAllSubverticalUnifiedReviewError("unified review gate set is invalid")
        if row["decision"] == "submit_for_admission_gate":
            if not all(gates.values()):
                raise GTMAllSubverticalUnifiedReviewError("unified admission submission has failed gates")
            fields = row.get("field_bindings")
            if not isinstance(fields, Mapping) or set(fields) != set(REQUIRED_FIELD_BINDINGS) or not all(_nonempty(fields[n]) for n in REQUIRED_FIELD_BINDINGS):
                raise GTMAllSubverticalUnifiedReviewError("unified admission submission has incomplete field bindings")
            costs = row.get("cost_components")
            if not isinstance(costs, Mapping) or set(costs) != set(SIX_COST_COMPONENTS) or not all(_nonempty(costs[n]) for n in SIX_COST_COMPONENTS):
                raise GTMAllSubverticalUnifiedReviewError("unified admission submission has incomplete cost evidence")
            bindings = row.get("exact_claim_bindings")
            if not isinstance(bindings, list) or not bindings:
                raise GTMAllSubverticalUnifiedReviewError("unified admission submission lacks exact claim bindings")
            for binding in bindings:
                excerpt = binding.get("exact_excerpt") if isinstance(binding, Mapping) else None
                if not _nonempty(binding.get("field")) or not _nonempty(excerpt) or binding.get("source_url") != packet["source_url"]:
                    raise GTMAllSubverticalUnifiedReviewError("unified exact claim binding is invalid")
                if binding.get("excerpt_sha256") != hashlib.sha256(excerpt.encode("utf-8")).hexdigest():
                    raise GTMAllSubverticalUnifiedReviewError("unified exact claim excerpt hash drifted")
        elif not _nonempty(row.get("decision_notes")):
            raise GTMAllSubverticalUnifiedReviewError("unified non-admission decision lacks notes")


def compile_unified_review_receipt(intake: Mapping[str, Any], ledger: Mapping[str, Any]) -> dict[str, Any]:
    validate_unified_review_intake(intake, ledger)
    counts = Counter(row["decision"] for row in intake["records"])
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "review_ledger_sha256": ledger["content_sha256"],
        "review_intake_sha256": _digest(intake),
        "review_count": len(intake["records"]),
        "decision_counts": dict(sorted(counts.items())),
        "admission_submission_count": counts["submit_for_admission_gate"],
        "formal_candidate_quota_credit": 0,
        "automatic_promotion_allowed": False,
        "records": [{
            "review_packet_id": row["review_packet_id"],
            "review_packet_sha256": row["review_packet_sha256"],
            "reviewer_name": row["reviewer_name"],
            "reviewed_at": row["reviewed_at"],
            "decision": row["decision"],
            "formal_candidate_quota_credit": 0,
        } for row in intake["records"]],
        "truth_boundary": (
            "This receipt proves a source-bound named-human intake passed validation. It does not prove the claims, "
            "causal effect, independence, deduplication, marginal quota fit or CaseCandidateV2 admission."
        ),
    }
    receipt["content_sha256"] = _digest(receipt)
    return receipt


def verify_unified_review_receipt(receipt: Mapping[str, Any]) -> None:
    unsigned = dict(receipt)
    supplied = unsigned.pop("content_sha256", None)
    if receipt.get("schema") != RECEIPT_SCHEMA or supplied != _digest(unsigned):
        raise GTMAllSubverticalUnifiedReviewError("unified review receipt seal is invalid")
    records = receipt.get("records")
    if not isinstance(records, list) or receipt.get("review_count") != len(records):
        raise GTMAllSubverticalUnifiedReviewError("unified review receipt aggregate drifted")
    if receipt.get("formal_candidate_quota_credit") != 0 or receipt.get("automatic_promotion_allowed") is not False:
        raise GTMAllSubverticalUnifiedReviewError("unified review receipt escaped zero-credit mode")
    if any(row.get("formal_candidate_quota_credit") != 0 for row in records):
        raise GTMAllSubverticalUnifiedReviewError("unified review receipt record minted quota")


__all__ = [
    "GTMAllSubverticalUnifiedReviewError",
    "INTAKE_SCHEMA",
    "LEDGER_SCHEMA",
    "RECEIPT_SCHEMA",
    "build_unified_review_ledger",
    "compile_unified_review_receipt",
    "review_packet_digest",
    "validate_unified_review_intake",
    "verify_unified_review_ledger",
    "verify_unified_review_receipt",
]
