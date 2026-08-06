from __future__ import annotations

import hashlib
import json
import statistics
from pathlib import Path
from typing import Any, Mapping, Sequence


KIT_SCHEMA = "ProofLaunchCodexLighthouseHumanReviewKitV1"
REVIEW_SCHEMA = "ProofLaunchCodexLighthouseHumanReviewV1"
AGGREGATE_SCHEMA = "ProofLaunchCodexLighthouseHumanReviewAggregateV1"
PRIVATE_MAPPING_SCHEMA = "ProofLaunchCodexLighthousePrivateMappingV1"
DIMENSIONS = (
    "strategy_quality",
    "platform_native_copy",
    "originality",
    "audience_fit",
    "evidence_discipline",
    "execution_coherence",
)
ATTESTATION = (
    "I independently reviewed the complete source-hidden case without model, author, "
    "other-reviewer, or private-mapping information. My answers are my own human judgment."
)
DEFECTS = {"none", "strategy", "platform", "copy", "proof", "legal", "other"}


class LighthouseHumanReviewError(ValueError):
    pass


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _sealed(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["content_sha256"] = digest(result)
    return result


def _text(value: object, *, field: str, minimum: int) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise LighthouseHumanReviewError(f"{field} must contain at least {minimum} characters")
    return value.strip()


def load_review_contract(kit_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads((kit_root / "manifest.json").read_text(encoding="utf-8"))
    mapping = json.loads((kit_root / "private/blind-case-mapping.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != KIT_SCHEMA:
        raise LighthouseHumanReviewError("review kit schema drifted")
    unsigned_manifest = dict(manifest)
    supplied_manifest = unsigned_manifest.pop("content_sha256", None)
    if supplied_manifest != digest(unsigned_manifest):
        raise LighthouseHumanReviewError("review kit manifest seal is invalid")
    if mapping.get("schema") != PRIVATE_MAPPING_SCHEMA:
        raise LighthouseHumanReviewError("private mapping schema drifted")
    unsigned_mapping = dict(mapping)
    supplied_mapping = unsigned_mapping.pop("content_sha256", None)
    if supplied_mapping != digest(unsigned_mapping):
        raise LighthouseHumanReviewError("private mapping seal is invalid")
    rows = mapping.get("rows")
    if not isinstance(rows, list) or len(rows) != 8:
        raise LighthouseHumanReviewError("private mapping must contain eight cases")
    if manifest.get("candidate_count") != 8 or manifest.get("reviewer_count") != 5:
        raise LighthouseHumanReviewError("review kit count contract drifted")
    return manifest, mapping


def verify_review_payload(
    payload: Mapping[str, Any],
    *,
    expected_by_blind_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if payload.get("schema") != REVIEW_SCHEMA or payload.get("kit_schema") != KIT_SCHEMA:
        raise LighthouseHumanReviewError("review payload schema drifted")
    unsigned = dict(payload)
    supplied = unsigned.pop("review_payload_sha256", None)
    if supplied != digest(unsigned):
        raise LighthouseHumanReviewError("review payload seal is invalid")
    slot = payload.get("reviewer_slot")
    if not isinstance(slot, int) or isinstance(slot, bool) or not 1 <= slot <= 5:
        raise LighthouseHumanReviewError("reviewer_slot must be in [1, 5]")
    reviewer = _text(payload.get("reviewer_pseudonym"), field="reviewer_pseudonym", minimum=3)
    if payload.get("human_attestation") != ATTESTATION:
        raise LighthouseHumanReviewError("human attestation drifted")
    if payload.get("independent_attestation") is not True or payload.get("conflict_disclosed") is not True:
        raise LighthouseHumanReviewError("independence and conflict attestations are required")
    _text(payload.get("reviewed_at"), field="reviewed_at", minimum=16)
    reviews = payload.get("reviews")
    if not isinstance(reviews, list) or len(reviews) != 8:
        raise LighthouseHumanReviewError("each reviewer must submit exactly eight cases")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for row in reviews:
        if not isinstance(row, Mapping):
            raise LighthouseHumanReviewError("review row must be an object")
        blind_id = row.get("blind_case_id")
        if not isinstance(blind_id, str) or blind_id not in expected_by_blind_id or blind_id in seen:
            raise LighthouseHumanReviewError("review contains an unknown or duplicate blind case")
        seen.add(blind_id)
        expected = expected_by_blind_id[blind_id]
        if row.get("candidate_content_sha256") != expected["candidate_content_sha256"]:
            raise LighthouseHumanReviewError("review candidate digest does not match private mapping")
        scores = row.get("scores")
        if not isinstance(scores, Mapping) or set(scores) != set(DIMENSIONS):
            raise LighthouseHumanReviewError("review score dimensions drifted")
        for dimension, value in scores.items():
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 5:
                raise LighthouseHumanReviewError(f"{dimension} score must be an integer in [1, 5]")
        directly = row.get("directly_publishable")
        major = row.get("major_rework")
        if not isinstance(directly, bool) or not isinstance(major, bool) or (directly and major):
            raise LighthouseHumanReviewError("publishability and major-rework verdicts are invalid")
        defect = row.get("blocking_defect")
        if defect not in DEFECTS:
            raise LighthouseHumanReviewError("blocking defect value is invalid")
        normalized.append({
            "blind_case_id": blind_id,
            "candidate_id": expected["candidate_id"],
            "candidate_content_sha256": expected["candidate_content_sha256"],
            "scores": dict(scores),
            "directly_publishable": directly,
            "major_rework": major,
            "blocking_defect": defect,
            "rationale": _text(row.get("rationale"), field="rationale", minimum=40),
            "strongest_element": _text(row.get("strongest_element"), field="strongest_element", minimum=20),
            "first_repair": _text(row.get("first_repair"), field="first_repair", minimum=20),
        })
    if seen != set(expected_by_blind_id):
        raise LighthouseHumanReviewError("review does not cover the complete frozen case set")
    return {"slot": slot, "reviewer": reviewer, "rows": normalized, "payload_sha256": supplied}


def aggregate_reviews(kit_root: Path, review_payloads: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    manifest, mapping = load_review_contract(kit_root)
    expected = {str(row["blind_case_id"]): row for row in mapping["rows"]}
    verified = [verify_review_payload(payload, expected_by_blind_id=expected) for payload in review_payloads]
    slots = [row["slot"] for row in verified]
    reviewers = [row["reviewer"] for row in verified]
    if len(slots) != len(set(slots)):
        raise LighthouseHumanReviewError("duplicate reviewer slot")
    if len(reviewers) != len(set(reviewers)):
        raise LighthouseHumanReviewError("the same reviewer cannot fill multiple slots")

    case_rows: list[dict[str, Any]] = []
    qualified = 0
    for blind_id, map_row in expected.items():
        observations = [row for review in verified for row in review["rows"] if row["blind_case_id"] == blind_id]
        medians = {
            dimension: statistics.median(row["scores"][dimension] for row in observations)
            if observations else None
            for dimension in DIMENSIONS
        }
        direct_count = sum(row["directly_publishable"] for row in observations)
        major_count = sum(row["major_rework"] for row in observations)
        defect_count = sum(row["blocking_defect"] != "none" for row in observations)
        complete = len(observations) == 5
        passed = bool(
            complete
            and all(value is not None and value >= 4 for value in medians.values())
            and direct_count == 5
            and major_count == 0
            and defect_count == 0
        )
        qualified += int(passed)
        case_rows.append({
            "blind_case_id": blind_id,
            "candidate_id": map_row["candidate_id"],
            "candidate_content_sha256": map_row["candidate_content_sha256"],
            "human_review_count": len(observations),
            "dimension_medians": medians,
            "directly_publishable_count": direct_count,
            "major_rework_count": major_count,
            "blocking_defect_count": defect_count,
            "human_development_eval_passed": passed,
        })

    submitted = len(verified) * 8
    complete = len(verified) == 5 and submitted == 40
    payload = {
        "schema": AGGREGATE_SCHEMA,
        "source_kit_sha256": manifest["content_sha256"],
        "reviewer_file_count": len(verified),
        "distinct_reviewer_count": len(set(reviewers)),
        "submitted_human_review_count": submitted,
        "expected_human_review_count": 40,
        "human_review_set_complete": complete,
        "qualified_candidate_count": qualified,
        "all_candidates_passed_human_development_eval": complete and qualified == 8,
        "cases": case_rows,
        "named_product_baseline_count": 0,
        "named_product_pk_completed_count": 0,
        "production_effect_observed_count": 0,
        "release_authorized_count": 0,
        "four_a_claim_eligible": False,
        "status": "human_development_eval_complete" if complete else "awaiting_40_human_reviews",
        "truth_boundary": "Human development review, when complete, evaluates these eight clean-room candidates only. It never establishes a named-product PK win, production effect, causal revenue lift, or release authorization.",
    }
    return _sealed(payload)


def verify_aggregate(payload: Mapping[str, Any]) -> None:
    if payload.get("schema") != AGGREGATE_SCHEMA:
        raise LighthouseHumanReviewError("aggregate schema drifted")
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != digest(unsigned):
        raise LighthouseHumanReviewError("aggregate seal is invalid")
    if payload.get("named_product_pk_completed_count") != 0 or payload.get("production_effect_observed_count") != 0:
        raise LighthouseHumanReviewError("aggregate leaked effect authority")
    if payload.get("release_authorized_count") != 0 or payload.get("four_a_claim_eligible") is not False:
        raise LighthouseHumanReviewError("aggregate leaked release or 4A authority")


__all__ = [
    "AGGREGATE_SCHEMA",
    "ATTESTATION",
    "DIMENSIONS",
    "KIT_SCHEMA",
    "LighthouseHumanReviewError",
    "REVIEW_SCHEMA",
    "aggregate_reviews",
    "digest",
    "load_review_contract",
    "verify_aggregate",
    "verify_review_payload",
]
