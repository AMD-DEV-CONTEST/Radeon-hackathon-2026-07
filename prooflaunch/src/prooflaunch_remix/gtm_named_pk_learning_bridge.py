from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .gtm_genome_learning_memory import compile_genome_learning_memory
from .gtm_multimodal_breakout_factory import verify_multimodal_breakout_factory
from .gtm_named_capability_distillation import verify_named_capability_distillation


SCHEMA = "ProofLaunchGTMNamedPKLearningBridgeV1"


class GTMNamedPKLearningBridgeError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def compile_named_pk_learning_bridge(
    *,
    factory: Mapping[str, Any],
    distillation: Mapping[str, Any],
    category_id: str,
    review_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    verify_multimodal_breakout_factory(factory)
    verify_named_capability_distillation(distillation)
    category = next((row for row in distillation["categories"] if row["category_id"] == category_id), None)
    if category is None:
        raise GTMNamedPKLearningBridgeError("category is absent from named capability distillation")
    required = {
        "reference_product", "candidate_genome_id", "reviewer_ids", "source_hidden",
        "authorized_baseline_present", "candidate_preference_rate", "wilson_lower_95",
        "direct_publishable_rate", "major_rework_rate", "critical_defect_count",
        "diagnostic_axis_pairs", "evidence_sha256", "approved_by", "human_approved",
    }
    if not isinstance(review_rows, Sequence) or isinstance(review_rows, (str, bytes)) or len(review_rows) != 10:
        raise GTMNamedPKLearningBridgeError("one category learning decision requires exactly ten named-product reviews")
    if {row.get("reference_product") for row in review_rows} != set(category["reference_products"]):
        raise GTMNamedPKLearningBridgeError("reviews do not cover the category's ten named products exactly")
    candidate_ids = {row.get("candidate_genome_id") for row in review_rows}
    if len(candidate_ids) != 1:
        raise GTMNamedPKLearningBridgeError("one learning decision must evaluate one unchanged genome")
    genome_id = next(iter(candidate_ids))
    candidate = next((row for row in factory["candidate_campaigns"] if row["genome_id"] == genome_id), None)
    if candidate is None:
        raise GTMNamedPKLearningBridgeError("reviewed genome is absent from the bound factory")
    genome = next(
        row["genome"] for row in factory["creative_kernel"]["candidate_blueprints"] if row["genome_id"] == genome_id
    )
    normalized_rows = []
    for index, row in enumerate(review_rows):
        if set(row) != required:
            raise GTMNamedPKLearningBridgeError(f"review row {index} violates the closed contract")
        reviewers = row["reviewer_ids"]
        if not isinstance(reviewers, list) or len(reviewers) < 5 or len(set(reviewers)) != len(reviewers):
            raise GTMNamedPKLearningBridgeError("each named comparison requires five distinct reviewers")
        if row["source_hidden"] is not True or row["authorized_baseline_present"] is not True:
            raise GTMNamedPKLearningBridgeError("source-hidden authorized baseline evidence is required")
        if row["human_approved"] is not True or not isinstance(row["approved_by"], str) or not row["approved_by"].strip():
            raise GTMNamedPKLearningBridgeError("named human approval is required")
        for field in ("candidate_preference_rate", "wilson_lower_95", "direct_publishable_rate", "major_rework_rate"):
            value = row[field]
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
                raise GTMNamedPKLearningBridgeError(f"{field} must be a bounded rate")
        if not isinstance(row["critical_defect_count"], int) or isinstance(row["critical_defect_count"], bool) or row["critical_defect_count"] < 0:
            raise GTMNamedPKLearningBridgeError("critical_defect_count is invalid")
        pairs = row["diagnostic_axis_pairs"]
        if not isinstance(pairs, list) or not 1 <= len(pairs) <= 3:
            raise GTMNamedPKLearningBridgeError("diagnostic_axis_pairs must contain one to three pairs")
        for pair in pairs:
            if not isinstance(pair, str) or ":" not in pair:
                raise GTMNamedPKLearningBridgeError("diagnostic axis pair is invalid")
            axis, value = pair.split(":", 1)
            if axis not in genome or genome[axis]["id"] != value:
                raise GTMNamedPKLearningBridgeError("diagnostic axis pair does not match the reviewed genome")
        if not isinstance(row["evidence_sha256"], str) or len(row["evidence_sha256"]) != 64:
            raise GTMNamedPKLearningBridgeError("evidence_sha256 is invalid")
        normalized_rows.append(dict(row))
    def passed(row: Mapping[str, Any]) -> bool:
        return (
            row["candidate_preference_rate"] >= 0.75
            and row["wilson_lower_95"] > 0.50
            and row["direct_publishable_rate"] >= 0.95
            and row["major_rework_rate"] <= 0.05
            and row["critical_defect_count"] == 0
        )
    if all(passed(row) for row in normalized_rows):
        verdict = "promote"
    elif any(row["critical_defect_count"] > 0 for row in normalized_rows):
        verdict = "retire"
    else:
        verdict = "repair"
    shared_pairs = set(normalized_rows[0]["diagnostic_axis_pairs"])
    for row in normalized_rows[1:]:
        shared_pairs &= set(row["diagnostic_axis_pairs"])
    if not shared_pairs:
        raise GTMNamedPKLearningBridgeError("ten comparisons do not agree on a diagnostic mechanism")
    evidence_sha = _digest({
        "factory": factory["content_sha256"], "distillation": distillation["content_sha256"],
        "category": category_id, "reviews": normalized_rows,
    })
    approvers = sorted({row["approved_by"] for row in normalized_rows})
    memory = compile_genome_learning_memory([{
        "record_id": f"named-pk-{category_id}-{genome_id[:12]}",
        "genome_id": genome_id,
        "verdict": verdict,
        "business_model": factory["brief"]["business_model"],
        "platform": factory["brief"]["platform"],
        "category": factory["brief"]["category"],
        "axis_pairs": sorted(shared_pairs)[:3],
        "evidence_sha256": evidence_sha,
        "approved_by": ",".join(approvers),
        "human_approved": True,
    }])
    payload = {
        "schema": SCHEMA,
        "category_id": category_id,
        "named_product_review_count": len(normalized_rows),
        "reference_products": sorted(row["reference_product"] for row in normalized_rows),
        "candidate_genome_id": genome_id,
        "all_rows_passed": all(passed(row) for row in normalized_rows),
        "critical_defect_count": sum(row["critical_defect_count"] for row in normalized_rows),
        "verdict": verdict,
        "learning_memory": memory,
        "automatic_winner_selection": False,
        "current_run_mutation": False,
        "truth_boundary": "This bridge converts ten authorized, source-hidden, named-human comparisons into one next-run mechanism prior. It does not publish, select a current-run winner or claim organic effects.",
    }
    payload["content_sha256"] = _digest(payload)
    return payload


__all__ = ["GTMNamedPKLearningBridgeError", "SCHEMA", "compile_named_pk_learning_bridge"]
