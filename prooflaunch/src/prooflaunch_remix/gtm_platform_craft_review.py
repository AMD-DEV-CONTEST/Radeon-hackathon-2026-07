from __future__ import annotations

import hashlib
import hmac
import json
from collections import defaultdict
from datetime import datetime
from typing import Any, Mapping, Sequence

from .gtm_platform_native_challenger import (
    verify_platform_native_challenger_plan,
    verify_platform_native_receipt,
)
from .gtm_human_capability_kernel import SURFACE_PLAYBOOKS
from .gtm_platform_native_publication_audit import (
    verify_platform_native_publication_audit,
)


PUBLIC_SCHEMA = "ProofLaunchPlatformCraftBlindReviewPacketV1"
PRIVATE_SCHEMA = "ProofLaunchPlatformCraftBlindReviewPrivateMappingV1"
REVIEW_SCHEMA = "ProofLaunchPlatformCraftHumanReviewV1"
AGGREGATE_SCHEMA = "ProofLaunchPlatformCraftReviewAggregateV1"
HUMAN_ATTESTATION = (
    "I independently reviewed this source-hidden platform artifact without provider, "
    "model, private-mapping, or other-reviewer information."
)
DIMENSIONS = (
    "strategic_fit",
    "platform_nativeness",
    "hook_strength",
    "editorial_craft",
    "proof_discipline",
    "participation_mechanism",
    "direct_publishability",
)
GATE = {
    "required_reviewers_per_artifact": 5,
    "minimum_overall_dimension_mean": 4.7,
    "minimum_each_dimension_mean": 4.5,
    "minimum_direct_publishable_rate": 1.0,
    "maximum_major_rework_rate": 0.0,
    "blocking_defects_allowed": 0,
}
EXPECTED_SURFACES = tuple(SURFACE_PLAYBOOKS)


class PlatformCraftReviewError(ValueError):
    pass


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _seal(payload: Mapping[str, Any]) -> dict[str, Any]:
    sealed = dict(payload)
    sealed["content_sha256"] = digest(payload)
    return sealed


def _verify_seal(value: object, *, schema: str, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != schema:
        raise PlatformCraftReviewError(f"{label} schema is invalid")
    unsigned = dict(value)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != digest(unsigned):
        raise PlatformCraftReviewError(f"{label} digest is invalid")
    return value


def _public_artifact(
    *,
    candidate: Mapping[str, Any],
    request: Mapping[str, Any],
    brief: Mapping[str, Any],
    blind_artifact_id: str,
) -> dict[str, Any]:
    artifact: dict[str, Any] = {
        "blind_artifact_id": blind_artifact_id,
        "surface_id": candidate["surface_id"],
        "native_format_contract": request["native_format_contract"],
        "review_context": {
            key: brief[key]
            for key in ("audience", "problem", "offer", "approved_claim", "voice")
        },
        "artifact": {
            key: candidate[key]
            for key in (
                "campaign_platform",
                "hook",
                "progression",
                "body",
                "cta",
                "participation_mechanism",
                "proof_integration",
                "falsifier",
            )
        },
        "rubric_dimensions": list(DIMENSIONS),
        "mechanical_publication_gate_passed": True,
        "source_hidden": True,
        "provider_and_model_hidden": True,
    }
    artifact["artifact_sha256"] = digest(artifact)
    return artifact


def build_platform_craft_review_bundle(
    *,
    plan: Mapping[str, Any],
    receipt: Mapping[str, Any],
    publication_audit: Mapping[str, Any],
    randomization_secret: str,
    reviewer_count: int = 5,
) -> dict[str, dict[str, Any]]:
    verify_platform_native_challenger_plan(plan)
    verify_platform_native_receipt(receipt, plan=plan)
    verify_platform_native_publication_audit(publication_audit)
    if plan.get("business_model") != "b2b":
        raise PlatformCraftReviewError("craft review admits only the real B2B brief")
    if receipt.get("accepted_surface_count") != 13:
        raise PlatformCraftReviewError("craft review requires thirteen accepted candidates")
    if not isinstance(randomization_secret, str) or len(randomization_secret) < 32:
        raise PlatformCraftReviewError("randomization secret must contain at least 32 characters")
    if reviewer_count != 5:
        raise PlatformCraftReviewError("craft review requires exactly five reviewers")
    audit_rows = {
        row["surface_id"]: row
        for row in publication_audit["rows"]
        if row.get("business_model") == "b2b"
    }
    if set(audit_rows) != set(EXPECTED_SURFACES) or any(
        not row.get("mechanical_publication_ready") for row in audit_rows.values()
    ):
        raise PlatformCraftReviewError("all thirteen B2B artifacts must pass publication audit")
    requests = {row["surface_id"]: row for row in plan["requests"]}
    candidates = {row["surface_id"]: row for row in receipt["accepted_candidates"]}
    secret = randomization_secret.encode("utf-8")
    artifacts: list[dict[str, Any]] = []
    mappings: list[dict[str, Any]] = []
    for surface_id in EXPECTED_SURFACES:
        candidate = candidates[surface_id]
        commitment = hmac.new(
            secret,
            canonical_json(
                {
                    "plan_sha256": plan["content_sha256"],
                    "receipt_sha256": receipt["content_sha256"],
                    "candidate_sha256": candidate["content_sha256"],
                    "surface_id": surface_id,
                }
            ).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        blind_id = f"craft-{digest({'commitment': commitment})[:20]}"
        public_artifact = _public_artifact(
            candidate=candidate,
            request=requests[surface_id],
            brief=plan["brief"],
            blind_artifact_id=blind_id,
        )
        artifacts.append(public_artifact)
        mappings.append(
            {
                "blind_artifact_id": blind_id,
                "artifact_sha256": public_artifact["artifact_sha256"],
                "surface_id": surface_id,
                "candidate_sha256": candidate["content_sha256"],
                "randomization_commitment": commitment,
            }
        )
    artifacts.sort(key=lambda row: row["blind_artifact_id"])
    tasks: list[dict[str, Any]] = []
    for reviewer_slot in range(1, reviewer_count + 1):
        for artifact in artifacts:
            task_id = (
                f"{artifact['blind_artifact_id']}-reviewer-{reviewer_slot:02d}"
            )
            tasks.append(
                {
                    "schema": REVIEW_SCHEMA,
                    "review_task_id": task_id,
                    "blind_artifact_id": artifact["blind_artifact_id"],
                    "artifact_sha256": artifact["artifact_sha256"],
                    "reviewer_slot": reviewer_slot,
                    "reviewer_pseudonym": None,
                    "human_attestation": None,
                    "conflict_disclosed": None,
                    "dimension_scores": None,
                    "directly_publishable": None,
                    "major_rework": None,
                    "blocking_defect": None,
                    "blocking_defect_reason": None,
                    "rationale": None,
                    "reviewed_at": None,
                    "review_content_sha256": None,
                }
            )
    public = _seal(
        {
            "schema": PUBLIC_SCHEMA,
            "plan_sha256": plan["content_sha256"],
            "receipt_sha256": receipt["content_sha256"],
            "publication_audit_sha256": publication_audit["content_sha256"],
            "artifact_count": 13,
            "reviewer_count": 5,
            "review_task_count": 65,
            "artifacts": artifacts,
            "review_tasks": tasks,
            "quality_gate": dict(GATE),
            "submitted_human_review_count": 0,
            "source_identity_exposed": False,
            "provider_identity_exposed": False,
            "model_identity_exposed": False,
            "automatic_scoring_executed": False,
            "craft_review_completed": False,
            "named_product_comparison_executed": False,
            "winner_selected": False,
            "external_publish_executed": False,
            "truth_boundary": (
                "This packet schedules sixty-five empty source-hidden craft reviews over thirteen mechanically valid B2B platform artifacts. "
                "It contains no human observation and proves no named-product preference, 4A quality, organic breakout, conversion, revenue or causal effect."
            ),
        }
    )
    private = _seal(
        {
            "schema": PRIVATE_SCHEMA,
            "public_packet_sha256": public["content_sha256"],
            "source_plan_sha256": plan["content_sha256"],
            "source_receipt_sha256": receipt["content_sha256"],
            "source_model": dict(receipt["model"]),
            "mapping_count": 13,
            "mappings": mappings,
            "randomization_secret_persisted": False,
            "craft_review_completed": False,
            "winner_selected": False,
            "external_publish_executed": False,
        }
    )
    verify_platform_craft_review_bundle(public, private)
    return {"public_packet": public, "private_mapping": private}


def verify_platform_craft_review_bundle(
    public: Mapping[str, Any], private: Mapping[str, Any]
) -> None:
    public = _verify_seal(public, schema=PUBLIC_SCHEMA, label="public craft packet")
    private = _verify_seal(private, schema=PRIVATE_SCHEMA, label="private craft mapping")
    if private.get("public_packet_sha256") != public.get("content_sha256"):
        raise PlatformCraftReviewError("private mapping is not bound to public packet")
    artifacts = public.get("artifacts")
    tasks = public.get("review_tasks")
    mappings = private.get("mappings")
    if (
        not isinstance(artifacts, list)
        or len(artifacts) != 13
        or public.get("artifact_count") != 13
        or not isinstance(tasks, list)
        or len(tasks) != 65
        or public.get("review_task_count") != 65
        or public.get("reviewer_count") != 5
        or not isinstance(mappings, list)
        or len(mappings) != 13
        or private.get("mapping_count") != 13
    ):
        raise PlatformCraftReviewError("craft review coverage is incomplete")
    artifact_by_id = {row.get("blind_artifact_id"): row for row in artifacts}
    mapping_by_id = {row.get("blind_artifact_id"): row for row in mappings}
    if len(artifact_by_id) != 13 or set(artifact_by_id) != set(mapping_by_id):
        raise PlatformCraftReviewError("craft review blind identities are invalid")
    if {row.get("surface_id") for row in artifacts} != set(EXPECTED_SURFACES):
        raise PlatformCraftReviewError("craft review surface coverage drifted")
    for blind_id, artifact in artifact_by_id.items():
        unsigned = dict(artifact)
        supplied = unsigned.pop("artifact_sha256", None)
        if supplied != digest(unsigned):
            raise PlatformCraftReviewError("public craft artifact digest is invalid")
        if mapping_by_id[blind_id].get("artifact_sha256") != supplied:
            raise PlatformCraftReviewError("public artifact lacks private binding")
        if artifact.get("provider_and_model_hidden") is not True:
            raise PlatformCraftReviewError("public artifact exposes provider or model")
    expected_task_keys = {
        (blind_id, slot)
        for blind_id in artifact_by_id
        for slot in range(1, 6)
    }
    observed_task_keys: set[tuple[str, int]] = set()
    empty_fields = (
        "reviewer_pseudonym",
        "human_attestation",
        "conflict_disclosed",
        "dimension_scores",
        "directly_publishable",
        "major_rework",
        "blocking_defect",
        "blocking_defect_reason",
        "rationale",
        "reviewed_at",
        "review_content_sha256",
    )
    for task in tasks:
        blind_id = task.get("blind_artifact_id")
        slot = task.get("reviewer_slot")
        if (
            task.get("schema") != REVIEW_SCHEMA
            or blind_id not in artifact_by_id
            or type(slot) is not int
            or slot not in range(1, 6)
            or task.get("artifact_sha256") != artifact_by_id[blind_id]["artifact_sha256"]
            or any(task.get(field) is not None for field in empty_fields)
        ):
            raise PlatformCraftReviewError("craft review task is invalid or fabricated")
        observed_task_keys.add((blind_id, slot))
    if observed_task_keys != expected_task_keys:
        raise PlatformCraftReviewError("craft review task matrix is incomplete")
    for field in (
        "source_identity_exposed",
        "provider_identity_exposed",
        "model_identity_exposed",
        "automatic_scoring_executed",
        "craft_review_completed",
        "named_product_comparison_executed",
        "winner_selected",
        "external_publish_executed",
    ):
        if public.get(field) is not False:
            raise PlatformCraftReviewError(f"public craft packet escaped {field} boundary")


def review_digest(review: Mapping[str, Any]) -> str:
    unsigned = dict(review)
    unsigned.pop("review_content_sha256", None)
    return digest(unsigned)


def validate_platform_craft_review(
    review: Mapping[str, Any], public_packet: Mapping[str, Any]
) -> tuple[str, ...]:
    failures: list[str] = []
    tasks = {
        row["review_task_id"]: row for row in public_packet.get("review_tasks", ())
    }
    task = tasks.get(review.get("review_task_id"))
    if review.get("schema") != REVIEW_SCHEMA:
        failures.append("schema")
    if task is None:
        failures.append("review_task_binding")
    else:
        for field in (
            "blind_artifact_id",
            "artifact_sha256",
            "reviewer_slot",
        ):
            if review.get(field) != task.get(field):
                failures.append(field)
    pseudonym = review.get("reviewer_pseudonym")
    if not isinstance(pseudonym, str) or not 3 <= len(pseudonym.strip()) <= 120:
        failures.append("reviewer_pseudonym")
    if review.get("human_attestation") != HUMAN_ATTESTATION:
        failures.append("human_attestation")
    if review.get("conflict_disclosed") is not True:
        failures.append("conflict_disclosed")
    scores = review.get("dimension_scores")
    if (
        not isinstance(scores, dict)
        or set(scores) != set(DIMENSIONS)
        or any(type(score) is not int or score not in range(1, 6) for score in scores.values())
    ):
        failures.append("dimension_scores")
    publishable = review.get("directly_publishable")
    major = review.get("major_rework")
    blocker = review.get("blocking_defect")
    if type(publishable) is not bool or type(major) is not bool or type(blocker) is not bool:
        failures.append("delivery_verdicts")
    elif publishable and major:
        failures.append("publishable_major_rework_conflict")
    reason = review.get("blocking_defect_reason")
    if not isinstance(reason, str) or len(reason) > 1200 or (blocker and len(reason.strip()) < 16):
        failures.append("blocking_defect_reason")
    rationale = review.get("rationale")
    if not isinstance(rationale, str) or not 40 <= len(rationale.strip()) <= 2400:
        failures.append("rationale")
    try:
        timestamp = datetime.fromisoformat(str(review.get("reviewed_at")).replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError
    except (TypeError, ValueError):
        failures.append("reviewed_at")
    if review.get("review_content_sha256") != review_digest(review):
        failures.append("review_content_sha256")
    return tuple(dict.fromkeys(failures))


def aggregate_platform_craft_reviews(
    *,
    public_packet: Mapping[str, Any],
    private_mapping: Mapping[str, Any],
    reviews: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    verify_platform_craft_review_bundle(public_packet, private_mapping)
    failures: list[str] = []
    task_ids = {row["review_task_id"] for row in public_packet["review_tasks"]}
    observed: set[str] = set()
    pseudonyms_by_slot: dict[int, set[str]] = defaultdict(set)
    rows_by_artifact: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for index, review in enumerate(reviews, start=1):
        row_failures = validate_platform_craft_review(review, public_packet)
        failures.extend(f"review-{index}:{failure}" for failure in row_failures)
        task_id = str(review.get("review_task_id", ""))
        if task_id in observed:
            failures.append(f"duplicate_review_task:{task_id}")
        observed.add(task_id)
        slot = review.get("reviewer_slot")
        if type(slot) is int:
            pseudonyms_by_slot[slot].add(str(review.get("reviewer_pseudonym", "")))
        if not row_failures:
            rows_by_artifact[str(review["blind_artifact_id"])].append(review)
    if len(reviews) != 65:
        failures.append("review_count_must_equal_65")
    if observed != task_ids:
        failures.append("review_task_coverage_incomplete")
    if set(pseudonyms_by_slot) != set(range(1, 6)):
        failures.append("five_reviewer_slots_required")
    if any(len(values) != 1 or "" in values for values in pseudonyms_by_slot.values()):
        failures.append("reviewer_slot_identity_drift")
    stable_pseudonyms = {
        next(iter(values)) for values in pseudonyms_by_slot.values() if len(values) == 1
    }
    if len(stable_pseudonyms) != 5:
        failures.append("five_distinct_human_reviewers_required")
    artifacts = {
        row["blind_artifact_id"]: row for row in public_packet["artifacts"]
    }
    results: list[dict[str, Any]] = []
    for blind_id, artifact in artifacts.items():
        rows = rows_by_artifact.get(blind_id, [])
        dimension_means = {
            dimension: (
                sum(int(row["dimension_scores"][dimension]) for row in rows) / len(rows)
                if rows
                else None
            )
            for dimension in DIMENSIONS
        }
        all_scores = [
            int(row["dimension_scores"][dimension])
            for row in rows
            for dimension in DIMENSIONS
        ]
        overall = sum(all_scores) / len(all_scores) if all_scores else None
        publishable = sum(row["directly_publishable"] is True for row in rows)
        major = sum(row["major_rework"] is True for row in rows)
        blocker = sum(row["blocking_defect"] is True for row in rows)
        total = len(rows)
        checks = {
            "reviewer_count": total == 5,
            "overall_dimension_mean": overall is not None and overall >= 4.7,
            "every_dimension_mean": bool(rows) and all(
                value is not None and value >= 4.5 for value in dimension_means.values()
            ),
            "direct_publishable_rate": total == 5 and publishable / total >= 1.0,
            "major_rework_rate": total == 5 and major / total <= 0.0,
            "blocking_defects": blocker == 0,
        }
        results.append(
            {
                "blind_artifact_id": blind_id,
                "surface_id": artifact["surface_id"],
                "artifact_sha256": artifact["artifact_sha256"],
                "reviewer_count": total,
                "dimension_means": {
                    key: round(value, 6) if value is not None else None
                    for key, value in dimension_means.items()
                },
                "overall_dimension_mean": round(overall, 6) if overall is not None else None,
                "direct_publishable_count": publishable,
                "major_rework_count": major,
                "blocking_defect_count": blocker,
                "gate_checks": checks,
                "craft_gate_passed": all(checks.values()),
            }
        )
    complete = not failures
    passed = sum(row["craft_gate_passed"] for row in results) if complete else 0
    payload = _seal(
        {
            "schema": AGGREGATE_SCHEMA,
            "public_packet_sha256": public_packet["content_sha256"],
            "private_mapping_sha256": private_mapping["content_sha256"],
            "submitted_human_review_count": len(reviews),
            "distinct_reviewer_count": len(stable_pseudonyms),
            "review_complete": complete,
            "failures": failures,
            "artifact_results": results,
            "craft_gate_passed_count": passed,
            "all_thirteen_craft_gates_passed": complete and passed == 13,
            "named_product_comparison_executed": False,
            "winner_selected": False,
            "external_publish_executed": False,
            "production_effect_observed": False,
            "four_a_claim_eligible": False,
            "top1_claim_eligible": False,
            "truth_boundary": (
                "A complete aggregate proves only the recorded source-hidden human craft judgments for these thirteen drafts. "
                "It does not prove named-product superiority, publication outcome, organic breakout, conversion, causal revenue, 4A or Top-1 status."
            ),
        }
    )
    verify_platform_craft_review_aggregate(payload)
    return payload


def verify_platform_craft_review_aggregate(value: object) -> None:
    aggregate = _verify_seal(
        value, schema=AGGREGATE_SCHEMA, label="platform craft aggregate"
    )
    results = aggregate.get("artifact_results")
    if not isinstance(results, list) or len(results) != 13:
        raise PlatformCraftReviewError("platform craft aggregate coverage is invalid")
    if aggregate.get("named_product_comparison_executed") is not False:
        raise PlatformCraftReviewError("craft aggregate escaped named-product boundary")
    for field in (
        "winner_selected",
        "external_publish_executed",
        "production_effect_observed",
        "four_a_claim_eligible",
        "top1_claim_eligible",
    ):
        if aggregate.get(field) is not False:
            raise PlatformCraftReviewError(f"craft aggregate escaped {field} boundary")
    complete = aggregate.get("review_complete") is True
    submitted = aggregate.get("submitted_human_review_count")
    distinct = aggregate.get("distinct_reviewer_count")
    if complete != (submitted == 65 and distinct == 5 and not aggregate.get("failures")):
        raise PlatformCraftReviewError("craft aggregate completion state is inconsistent")
    passed = sum(row.get("craft_gate_passed") is True for row in results)
    if aggregate.get("craft_gate_passed_count") != (passed if complete else 0):
        raise PlatformCraftReviewError("craft aggregate passed count is invalid")
    if aggregate.get("all_thirteen_craft_gates_passed") != (complete and passed == 13):
        raise PlatformCraftReviewError("craft aggregate global gate is invalid")
