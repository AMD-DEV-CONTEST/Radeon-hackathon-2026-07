from __future__ import annotations

import hashlib
import hmac
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .files import atomic_write_text
from .gtm_craft_handoff import (
    GTMCraftHandoffError,
    REVIEW_SCHEMA,
    build_craft_review_requests,
    validate_craft_review,
)
from .gtm_text_challenger import (
    TextChallengerError,
    build_text_challenger_receipt,
    validate_text_candidate,
    verify_text_challenger_plan,
)
from .inference_gateway import (
    GatewayResult,
    InferenceGatewayCallError,
    InferenceScope,
)
from .quality_contract import wilson_lower_bound


EXECUTION_SCHEMA = "ProofLaunchTextCreativeChallengerExecutionV1"
CRAFT_QUALITY_EXECUTION_SCHEMA = "ProofLaunchTextCraftQualityExecutionV1"
BLIND_PACKET_SCHEMA = "ProofLaunchTextCreativeBlindReviewPacketV1"
PRIVATE_MAPPING_SCHEMA = "ProofLaunchTextCreativeBlindMappingV1"
_SHA256 = "0123456789abcdef"
_BASELINE_FIELDS = frozenset(
    {
        "draft_id",
        "channel",
        "native_format",
        "hook",
        "body",
        "call_to_action",
        "citation",
        "growth_tension_id",
        "truth_status",
        "human_release_required",
        "automated_publish_allowed",
    }
)
_TERRITORY_IDS = ("decision_xray", "proof_before_promise", "voluntary_relay")
_RUBRIC = (
    "Which draft makes the decision tension clearer without overstating the evidence?",
    "Which draft is more creatively distinctive while remaining useful before the ask?",
    "Which draft fits the named channel behavior more naturally?",
    "Which draft integrates the approved proof as part of the idea rather than decoration?",
    "Which draft would you choose to advance for a controlled human-released test?",
)
TEXT_BLIND_HUMAN_ATTESTATION = (
    "I reviewed this pair independently as a human, saw no provider, model, territory "
    "or candidate-side identity, and did not substitute model-generated ratings."
)


class TextChallengerRunError(ValueError):
    """The model-execution or blind-review boundary was violated."""


class InferenceGatewayProtocol(Protocol):
    def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        *,
        scope: InferenceScope,
        purpose: str,
        max_tokens: int,
        temperature: float,
        timeout_seconds: float,
        official_models: Sequence[str] | None,
        official_retry_rounds: int,
    ) -> GatewayResult: ...


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in _SHA256 for char in value)
    )


def _gateway_request_sha256(result: GatewayResult) -> str | None:
    receipt = result.receipt
    direct = receipt.get("request_sha256")
    if isinstance(direct, str):
        return direct
    if result.route == "official_tokenfactory":
        official = receipt.get("official")
        if isinstance(official, Mapping):
            value = official.get("request_sha256")
            return str(value) if value is not None else None
    attempts = receipt.get("third_party_attempts")
    if isinstance(attempts, Sequence) and not isinstance(attempts, (str, bytes)):
        for row in reversed(attempts):
            if isinstance(row, Mapping) and row.get("status") == "passed":
                value = row.get("request_sha256")
                return str(value) if value is not None else None
    return None


def execute_text_challenger_plan(
    plan: Mapping[str, Any],
    gateway: InferenceGatewayProtocol,
    *,
    official_models: Sequence[str] | None = None,
    timeout_seconds: float = 45.0,
    official_retry_rounds: int = 0,
) -> dict[str, Any]:
    """Run the three planned calls sequentially and stop on the first unsafe result.

    The coordinator never selects a winner. A third-party development fallback may
    satisfy generation, but it can never become Radeon-local or competition-core
    evidence.
    """

    try:
        verify_text_challenger_plan(plan)
    except TextChallengerError as error:
        raise TextChallengerRunError(f"invalid challenger plan: {error}") from error
    if plan.get("maximum_model_calls") != 3 or plan.get("territory_count") != 3:
        raise TextChallengerRunError("challenger execution requires exactly three bounded calls")
    if not isinstance(timeout_seconds, (int, float)) or not 1 <= timeout_seconds <= 120:
        raise TextChallengerRunError("timeout_seconds must be in [1, 120]")
    if not isinstance(official_retry_rounds, int) or official_retry_rounds not in range(0, 3):
        raise TextChallengerRunError("official_retry_rounds must be 0, 1, or 2")

    candidates: list[dict[str, Any]] = []
    failure: dict[str, Any] | None = None
    for request in plan["requests"]:
        request_id = str(request["request_id"])
        territory_id = str(request["territory_id"])
        try:
            result = gateway.complete(
                request["messages"],
                scope=InferenceScope.DEVELOPMENT_CORE,
                purpose=str(request["purpose"]),
                max_tokens=int(request["maximum_output_tokens"]),
                temperature=float(request["temperature"]),
                timeout_seconds=float(timeout_seconds),
                official_models=official_models,
                official_retry_rounds=official_retry_rounds,
            )
            observed_request_sha256 = _gateway_request_sha256(result)
            if observed_request_sha256 != request["request_sha256"]:
                raise TextChallengerRunError(
                    "gateway receipt is not bound to the planned request"
                )
            candidate = validate_text_candidate(
                result.content,
                plan,
                territory_id=territory_id,
            )
            record: dict[str, Any] = {
                "request_id": request_id,
                "request_sha256": request["request_sha256"],
                "territory_id": territory_id,
                "provider": result.provider,
                "model": result.model,
                "route": result.route,
                "response_id": result.response_id,
                "finish_reason": result.finish_reason,
                "usage": dict(result.usage),
                "gateway_receipt": dict(result.receipt),
                "candidate": candidate,
                "competition_core_eligible": False,
                "radeon_local_inference": False,
                "winner_selected": False,
                "blind_review_completed": False,
                "external_publish_executed": False,
            }
            record["record_sha256"] = _digest(record)
            candidates.append(record)
        except InferenceGatewayCallError as error:
            failure = {
                "request_id": request_id,
                "territory_id": territory_id,
                "error_type": type(error).__name__,
                "error_code": "gateway_call_failed",
                "gateway_receipt": error.receipt,
            }
            break
        except (TextChallengerError, TextChallengerRunError) as error:
            failure = {
                "request_id": request_id,
                "territory_id": territory_id,
                "error_type": type(error).__name__,
                "error_code": "candidate_contract_failed",
                "message": str(error),
            }
            break

    validated_candidates = [record["candidate"] for record in candidates]
    challenger_receipt = (
        build_text_challenger_receipt(plan, validated_candidates)
        if failure is None and len(validated_candidates) == 3
        else None
    )
    payload: dict[str, Any] = {
        "schema": EXECUTION_SCHEMA,
        "plan_sha256": plan["content_sha256"],
        "strategy_id": plan["strategy_id"],
        "status": (
            "generated_validated_unreviewed"
            if challenger_receipt is not None
            else "blocked_partial_or_no_generation"
        ),
        "planned_call_count": 3,
        "completed_call_count": len(candidates),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "challenger_receipt": challenger_receipt,
        "failure": failure,
        "official_first_required": True,
        "competition_core_eligible": False,
        "radeon_local_inference_observed": False,
        "winner_selected": False,
        "blind_review_completed": False,
        "external_publish_executed": False,
        "truth_boundary": (
            "A completed receipt proves three development-core model responses passed "
            "mechanical grounding, semantic specificity, cross-channel distinction and "
            "cross-territory creative validation. It does not prove human preference, "
            "Radeon-local execution, publication, lift, virality, conversion or revenue."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    verify_text_challenger_execution(payload)
    return payload


def execute_text_craft_quality_loop(
    plan: Mapping[str, Any],
    execution: Mapping[str, Any],
    gateway: InferenceGatewayProtocol,
    *,
    official_models: Sequence[str] | None = None,
    timeout_seconds: float = 45.0,
    official_retry_rounds: int = 0,
) -> dict[str, Any]:
    """Run three independent advisory reviews, one repair, then three re-reviews.

    This never releases, ranks, publishes, sends, or spends. A model-review pass only
    makes a candidate eligible for the already-required source-hidden human review.
    """

    verify_text_challenger_plan(plan)
    verify_text_challenger_execution(execution)
    if execution.get("status") != "generated_validated_unreviewed":
        raise TextChallengerRunError("craft quality loop requires three validated candidates")
    if not 1 <= timeout_seconds <= 120:
        raise TextChallengerRunError("timeout_seconds must be in [1, 120]")
    if official_retry_rounds not in range(0, 3):
        raise TextChallengerRunError("official_retry_rounds must be 0, 1, or 2")

    handoffs = {
        row["territory_id"]: row for row in plan.get("craft_handoff_plans", [])
    }
    records: list[dict[str, Any]] = []
    total_calls = 0

    def run_reviews(
        handoff: Mapping[str, Any], candidate: Mapping[str, Any], *, round_id: str
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        nonlocal total_calls
        reviews: list[dict[str, Any]] = []
        failure: dict[str, Any] | None = None
        try:
            requests = build_craft_review_requests(handoff, candidate)
        except GTMCraftHandoffError as error:
            return [], {"error_code": "review_plan_failed", "message": str(error)}
        for request in requests:
            result: GatewayResult | None = None
            try:
                result = gateway.complete(
                    request["messages"],
                    scope=InferenceScope.DEVELOPMENT_CORE,
                    purpose="independent_gtm_craft_advisory_review",
                    max_tokens=int(request["maximum_output_tokens"]),
                    temperature=float(request["temperature"]),
                    timeout_seconds=float(timeout_seconds),
                    official_models=official_models,
                    official_retry_rounds=official_retry_rounds,
                )
                total_calls += 1
                if _gateway_request_sha256(result) != request["request_sha256"]:
                    raise TextChallengerRunError(
                        "craft review gateway receipt lost request binding"
                    )
                review = validate_craft_review(
                    result.content,
                    handoff_plan=handoff,
                    candidate=candidate,
                    work_order_id=str(request["work_order_id"]),
                )
                reviews.append(
                    {
                        "round": round_id,
                        "provider": result.provider,
                        "model": result.model,
                        "route": result.route,
                        "gateway_receipt": dict(result.receipt),
                        "review": review,
                    }
                )
            except (InferenceGatewayCallError, GTMCraftHandoffError, TextChallengerRunError) as error:
                failure = {
                    "error_code": "craft_review_failed",
                    "work_order_id": request["work_order_id"],
                    "error_type": type(error).__name__,
                    "message": str(error),
                    "gateway_receipt": (
                        dict(result.receipt) if result is not None else None
                    ),
                }
                break
        return reviews, failure

    for candidate_record in execution["candidates"]:
        territory_id = str(candidate_record["territory_id"])
        handoff = handoffs.get(territory_id)
        if not isinstance(handoff, Mapping):
            raise TextChallengerRunError("craft quality loop lost territory handoff")
        candidate = candidate_record["candidate"]
        initial_reviews, failure = run_reviews(
            handoff, candidate, round_id="pre_repair"
        )
        decisions = [row["review"]["decision"] for row in initial_reviews]
        final_candidate = candidate
        repair_record: dict[str, Any] | None = None
        post_reviews: list[dict[str, Any]] = []
        status = "blocked_review_failure"
        if failure is None and "block" in decisions:
            status = "blocked_by_advisory_review"
        elif failure is None and decisions == ["pass", "pass", "pass"]:
            status = "advisory_pass_pending_human_review"
        elif failure is None and "revise" in decisions:
            original_request = next(
                row for row in plan["requests"] if row["territory_id"] == territory_id
            )
            original_user = json.loads(original_request["messages"][1]["content"])
            raw_candidate = {
                key: candidate[key]
                for key in (
                    "schema", "territory_id", "strategy_id", "proof_claim_id",
                    "cultural_tension", "organizing_idea", "participation_mechanism",
                    "share_trigger", "proof_role", "falsifier", "factual_claims", "channels",
                )
            }
            repair_user = {
                "task": "Repair only the listed advisory findings. Preserve every bound identity, approved proof, exact CTA and closed output schema. Return one JSON object and no markdown.",
                "territory": original_user["territory"],
                "context": original_user["context"],
                "craft_handoff": original_user["craft_handoff"],
                "candidate": raw_candidate,
                "advisory_reviews": [row["review"] for row in initial_reviews],
                "output_contract": original_user["output_contract"],
                "maximum_revision_rounds": 1,
            }
            repair_messages = [
                {
                    "role": "system",
                    "content": (
                        "Perform one bounded senior craft repair. Do not introduce facts, "
                        "change the proof or CTA, choose a winner, or claim human approval."
                    ),
                },
                {"role": "user", "content": _canonical(repair_user)},
            ]
            repair_sha = _digest(repair_messages)
            result: GatewayResult | None = None
            try:
                result = gateway.complete(
                    repair_messages,
                    scope=InferenceScope.DEVELOPMENT_CORE,
                    purpose="bounded_gtm_craft_repair",
                    max_tokens=1400,
                    temperature=0.2,
                    timeout_seconds=float(timeout_seconds),
                    official_models=official_models,
                    official_retry_rounds=official_retry_rounds,
                )
                total_calls += 1
                if _gateway_request_sha256(result) != repair_sha:
                    raise TextChallengerRunError(
                        "craft repair gateway receipt lost request binding"
                    )
                final_candidate = validate_text_candidate(
                    result.content, plan, territory_id=territory_id
                )
                repair_record = {
                    "request_sha256": repair_sha,
                    "provider": result.provider,
                    "model": result.model,
                    "route": result.route,
                    "candidate": final_candidate,
                    "revision_round": 1,
                }
                post_reviews, failure = run_reviews(
                    handoff, final_candidate, round_id="post_repair"
                )
                post_decisions = [row["review"]["decision"] for row in post_reviews]
                status = (
                    "repaired_advisory_pass_pending_human_review"
                    if failure is None and post_decisions == ["pass", "pass", "pass"]
                    else "blocked_after_single_repair"
                )
            except (InferenceGatewayCallError, TextChallengerError, TextChallengerRunError) as error:
                failure = {
                    "error_code": "craft_repair_failed",
                    "error_type": type(error).__name__,
                    "message": str(error),
                    "gateway_receipt": (
                        dict(result.receipt) if result is not None else None
                    ),
                }
                status = "blocked_after_single_repair"
        quality_record = {
                "territory_id": territory_id,
                "source_candidate_sha256": candidate["candidate_content_sha256"],
                "initial_reviews": initial_reviews,
                "repair": repair_record,
                "post_repair_reviews": post_reviews,
                "final_candidate": final_candidate,
                "status": status,
                "failure": failure,
                "winner_selected": False,
                "human_release_granted": False,
                "external_publish_executed": False,
            }
        quality_record["record_sha256"] = _digest(quality_record)
        records.append(quality_record)

    permitted_statuses = {
        "advisory_pass_pending_human_review",
        "repaired_advisory_pass_pending_human_review",
    }
    all_advisory_pass = all(
        row["status"] in permitted_statuses for row in records
    )
    human_review_execution = None
    if all_advisory_pass:
        final_candidates = []
        for original, quality_record in zip(
            execution["candidates"], records, strict=True
        ):
            candidate_record = dict(original)
            candidate_record["candidate"] = quality_record["final_candidate"]
            candidate_record["craft_quality_record_sha256"] = quality_record[
                "record_sha256"
            ]
            candidate_record.pop("record_sha256", None)
            candidate_record["record_sha256"] = _digest(candidate_record)
            final_candidates.append(candidate_record)
        human_review_execution = dict(execution)
        human_review_execution["candidates"] = final_candidates
        human_review_execution["challenger_receipt"] = build_text_challenger_receipt(
            plan, [row["candidate"] for row in final_candidates]
        )
        human_review_execution.pop("content_sha256", None)
        human_review_execution["content_sha256"] = _digest(human_review_execution)
        verify_text_challenger_execution(human_review_execution)

    payload: dict[str, Any] = {
        "schema": CRAFT_QUALITY_EXECUTION_SCHEMA,
        "plan_sha256": plan["content_sha256"],
        "source_execution_sha256": execution["content_sha256"],
        "territory_count": len(records),
        "records": records,
        "craft_quality_call_count": total_calls,
        "maximum_craft_quality_calls": plan["maximum_craft_quality_calls"],
        "all_territories_advisory_pass": all_advisory_pass,
        "human_review_execution": human_review_execution,
        "blind_human_review_completed": False,
        "winner_selected": False,
        "human_release_granted": False,
        "external_publish_executed": False,
        "truth_boundary": (
            "This receipt proves bounded model-assisted specialist review and, when needed, "
            "one repair plus re-review. Advisory passes are not human judgments and do not "
            "prove preference, publication, lift, virality, conversion or revenue."
        ),
    }
    if total_calls > plan["maximum_craft_quality_calls"]:
        raise TextChallengerRunError("craft quality loop exceeded its model-call budget")
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_text_challenger_execution(payload: Mapping[str, Any]) -> None:
    if payload.get("schema") != EXECUTION_SCHEMA:
        raise TextChallengerRunError("execution schema is invalid")
    supplied = payload.get("content_sha256")
    if not _is_sha256(supplied):
        raise TextChallengerRunError("execution content digest is invalid")
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise TextChallengerRunError("execution content digest does not match")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != payload.get("candidate_count"):
        raise TextChallengerRunError("execution candidate count is inconsistent")
    if payload.get("completed_call_count") != len(candidates) or len(candidates) > 3:
        raise TextChallengerRunError("execution call count is inconsistent")
    expected_ids = list(_TERRITORY_IDS[: len(candidates)])
    if [row.get("territory_id") for row in candidates] != expected_ids:
        raise TextChallengerRunError("execution candidate order is invalid")
    for record in candidates:
        record_sha = record.get("record_sha256")
        unsigned_record = dict(record)
        unsigned_record.pop("record_sha256", None)
        if not _is_sha256(record_sha) or record_sha != _digest(unsigned_record):
            raise TextChallengerRunError("execution candidate record digest is invalid")
        if record.get("request_sha256") != _gateway_request_sha256(
            GatewayResult(
                provider=str(record.get("provider", "")),
                model=str(record.get("model", "")),
                route=str(record.get("route", "")),
                content="redacted-after-validation",
                response_id=None,
                finish_reason=None,
                usage={},
                receipt=record.get("gateway_receipt", {}),
            )
        ):
            raise TextChallengerRunError("execution gateway request binding is invalid")
        for field in (
            "competition_core_eligible",
            "radeon_local_inference",
            "winner_selected",
            "blind_review_completed",
            "external_publish_executed",
        ):
            if record.get(field) is not False:
                raise TextChallengerRunError(f"execution record escaped {field} boundary")
    for field in (
        "competition_core_eligible",
        "radeon_local_inference_observed",
        "winner_selected",
        "blind_review_completed",
        "external_publish_executed",
    ):
        if payload.get(field) is not False:
            raise TextChallengerRunError(f"execution escaped {field} boundary")
    complete = payload.get("status") == "generated_validated_unreviewed"
    if complete != (len(candidates) == 3 and payload.get("failure") is None):
        raise TextChallengerRunError("execution completion state is inconsistent")


def _normalized_baseline(channel_copy: Mapping[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for role in ("primary", "secondary"):
        row = channel_copy.get(role)
        if not isinstance(row, Mapping) or not _BASELINE_FIELDS.issubset(row):
            raise TextChallengerRunError("baseline channel-copy artifact is incomplete")
        normalized[role] = {field: row[field] for field in _BASELINE_FIELDS}
    return normalized


def _public_draft(
    row: Mapping[str, Any],
    *,
    blind_id: str,
    baseline: bool,
) -> dict[str, Any]:
    return {
        "blind_id": blind_id,
        "channel": row["channel"],
        "native_format": row["native_format"],
        "hook": row["hook"],
        "body": list(row["body"]),
        "cta": row["call_to_action"] if baseline else row["cta"],
        "disclosure": "draft_pending_human_review",
    }


def build_text_blind_review_bundle(
    plan: Mapping[str, Any],
    execution: Mapping[str, Any],
    channel_copy: Mapping[str, Any],
    *,
    randomization_secret: str,
    reviewer_count: int = 5,
) -> dict[str, dict[str, Any]]:
    """Create six role-hidden content pairs and thirty empty human assignments."""

    verify_text_challenger_plan(plan)
    verify_text_challenger_execution(execution)
    if execution.get("status") != "generated_validated_unreviewed":
        raise TextChallengerRunError("blind review requires three validated candidates")
    if execution.get("plan_sha256") != plan.get("content_sha256"):
        raise TextChallengerRunError("execution is not bound to the challenger plan")
    if not isinstance(randomization_secret, str) or len(randomization_secret) < 32:
        raise TextChallengerRunError("randomization_secret must contain at least 32 characters")
    if reviewer_count != 5:
        raise TextChallengerRunError("the launch blind-review packet requires five reviewers")

    baseline = _normalized_baseline(channel_copy)
    if _digest(baseline) != plan.get("baseline_copy_sha256"):
        raise TextChallengerRunError("baseline channel copy does not match the planned digest")
    secret = randomization_secret.encode("utf-8")
    public_pairs: list[dict[str, Any]] = []
    private_pairs: list[dict[str, Any]] = []
    review_tasks: list[dict[str, Any]] = []

    for candidate_record in execution["candidates"]:
        territory_id = str(candidate_record["territory_id"])
        candidate = candidate_record["candidate"]
        for index, role in enumerate(("primary", "secondary")):
            candidate_draft = candidate["channels"][index]
            baseline_draft = baseline[role]
            if candidate_draft["channel"] != baseline_draft["channel"]:
                raise TextChallengerRunError("candidate and baseline channels do not match")
            pair_material = {
                "plan_sha256": plan["content_sha256"],
                "candidate_sha256": candidate["candidate_content_sha256"],
                "baseline_sha256": plan["baseline_copy_sha256"],
                "channel": candidate_draft["channel"],
                "role": role,
            }
            commitment = hmac.new(
                secret,
                _canonical(pair_material).encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            pair_id = f"blind-pair-{_digest({'commitment': commitment})[:20]}"
            candidate_left = int(commitment[:8], 16) % 2 == 0
            left_blind_id = hmac.new(
                secret, f"{pair_id}:left".encode("utf-8"), hashlib.sha256
            ).hexdigest()
            right_blind_id = hmac.new(
                secret, f"{pair_id}:right".encode("utf-8"), hashlib.sha256
            ).hexdigest()
            candidate_public = _public_draft(
                candidate_draft,
                blind_id=left_blind_id if candidate_left else right_blind_id,
                baseline=False,
            )
            baseline_public = _public_draft(
                baseline_draft,
                blind_id=right_blind_id if candidate_left else left_blind_id,
                baseline=True,
            )
            left = candidate_public if candidate_left else baseline_public
            right = baseline_public if candidate_left else candidate_public
            public_pair = {
                "pair_id": pair_id,
                "channel": candidate_draft["channel"],
                "native_format": candidate_draft["native_format"],
                "left": left,
                "right": right,
                "rubric": list(_RUBRIC),
                "allowed_choices": ["left", "right", "abstain"],
                "sources_hidden": True,
                "candidate_role_hidden": True,
                "provider_and_model_hidden": True,
            }
            public_pair["pair_sha256"] = _digest(public_pair)
            public_pairs.append(public_pair)
            private_pairs.append(
                {
                    "pair_id": pair_id,
                    "pair_sha256": public_pair["pair_sha256"],
                    "randomization_commitment": commitment,
                    "candidate_side": "left" if candidate_left else "right",
                    "candidate_territory_id": territory_id,
                    "candidate_content_sha256": candidate["candidate_content_sha256"],
                    "candidate_record_sha256": candidate_record["record_sha256"],
                    "baseline_draft_id": baseline_draft["draft_id"],
                    "channel": candidate_draft["channel"],
                }
            )
            for reviewer_slot in range(1, reviewer_count + 1):
                task: dict[str, Any] = {
                    "schema": "ProofLaunchTextCreativeHumanBlindReviewV1",
                    "review_task_id": f"{pair_id}-reviewer-{reviewer_slot}",
                    "pair_id": pair_id,
                    "pair_sha256": public_pair["pair_sha256"],
                    "reviewer_slot": reviewer_slot,
                    "reviewer_pseudonym": None,
                    "human_attestation": None,
                    "choice": None,
                    "reason": None,
                    "critical_failure": None,
                    "reviewed_at": None,
                    "review_content_sha256": None,
                }
                review_tasks.append(task)

    public: dict[str, Any] = {
        "schema": BLIND_PACKET_SCHEMA,
        "strategy_id": plan["strategy_id"],
        "plan_sha256": plan["content_sha256"],
        "execution_sha256": execution["content_sha256"],
        "pair_count": len(public_pairs),
        "reviewer_count": reviewer_count,
        "review_task_count": len(review_tasks),
        "pairs": public_pairs,
        "review_tasks": review_tasks,
        "candidate_identity_exposed": False,
        "provider_identity_exposed": False,
        "automatic_scoring_executed": False,
        "blind_review_completed": False,
        "winner_selected": False,
        "external_publish_executed": False,
        "truth_boundary": (
            "This packet contains six randomized candidate-versus-baseline content pairs "
            "and thirty empty independent human assignments. It contains no submitted vote, "
            "preference result, winner, publication or business-effect evidence."
        ),
    }
    public["content_sha256"] = _digest(public)
    private: dict[str, Any] = {
        "schema": PRIVATE_MAPPING_SCHEMA,
        "public_packet_sha256": public["content_sha256"],
        "randomization_secret_persisted": False,
        "pair_count": len(private_pairs),
        "pairs": private_pairs,
        "blind_review_completed": False,
        "winner_selected": False,
        "external_publish_executed": False,
    }
    private["content_sha256"] = _digest(private)
    verify_text_blind_review_bundle(public, private)
    return {"public_packet": public, "private_mapping": private}


def verify_text_blind_review_bundle(
    public: Mapping[str, Any], private: Mapping[str, Any]
) -> None:
    if public.get("schema") != BLIND_PACKET_SCHEMA or private.get("schema") != PRIVATE_MAPPING_SCHEMA:
        raise TextChallengerRunError("blind review bundle schema is invalid")
    for name, payload in (("public", public), ("private", private)):
        supplied = payload.get("content_sha256")
        unsigned = dict(payload)
        unsigned.pop("content_sha256", None)
        if not _is_sha256(supplied) or supplied != _digest(unsigned):
            raise TextChallengerRunError(f"{name} blind bundle digest is invalid")
    if private.get("public_packet_sha256") != public.get("content_sha256"):
        raise TextChallengerRunError("private mapping is not bound to the public packet")
    pairs = public.get("pairs")
    mappings = private.get("pairs")
    tasks = public.get("review_tasks")
    if not isinstance(pairs, list) or len(pairs) != 6 or public.get("pair_count") != 6:
        raise TextChallengerRunError("blind packet must contain six content pairs")
    if not isinstance(mappings, list) or len(mappings) != 6 or private.get("pair_count") != 6:
        raise TextChallengerRunError("private mapping must contain six content pairs")
    if not isinstance(tasks, list) or len(tasks) != 30 or public.get("review_task_count") != 30:
        raise TextChallengerRunError("blind packet must contain thirty review assignments")
    mapping_by_id = {row.get("pair_id"): row for row in mappings}
    if len(mapping_by_id) != 6:
        raise TextChallengerRunError("private pair identities are not unique")
    for pair in pairs:
        unsigned_pair = dict(pair)
        supplied = unsigned_pair.pop("pair_sha256", None)
        if not _is_sha256(supplied) or supplied != _digest(unsigned_pair):
            raise TextChallengerRunError("public pair digest is invalid")
        mapping = mapping_by_id.get(pair.get("pair_id"))
        if not isinstance(mapping, Mapping) or mapping.get("pair_sha256") != supplied:
            raise TextChallengerRunError("public pair lacks a bound private mapping")
        if pair.get("candidate_role_hidden") is not True or pair.get("provider_and_model_hidden") is not True:
            raise TextChallengerRunError("blind packet exposed candidate or provider identity")
        left = pair.get("left")
        right = pair.get("right")
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            raise TextChallengerRunError("blind pair content is invalid")
        if left.get("blind_id") == right.get("blind_id") or left == right:
            raise TextChallengerRunError("blind pair contains duplicate sides")
    for task in tasks:
        if any(
            task.get(field) is not None
            for field in (
                "reviewer_pseudonym",
                "human_attestation",
                "choice",
                "reason",
                "critical_failure",
                "reviewed_at",
                "review_content_sha256",
            )
        ):
            raise TextChallengerRunError("blind review packet contains a fabricated human result")
    for field in (
        "candidate_identity_exposed",
        "provider_identity_exposed",
        "automatic_scoring_executed",
        "blind_review_completed",
        "winner_selected",
        "external_publish_executed",
    ):
        if public.get(field) is not False:
            raise TextChallengerRunError(f"public blind packet escaped {field} boundary")
    for field in (
        "randomization_secret_persisted",
        "blind_review_completed",
        "winner_selected",
        "external_publish_executed",
    ):
        if private.get(field) is not False:
            raise TextChallengerRunError(f"private blind mapping escaped {field} boundary")


def text_blind_review_digest(review: Mapping[str, Any]) -> str:
    material = dict(review)
    material["review_content_sha256"] = None
    return _digest(material)


def validate_text_blind_review(
    review: Mapping[str, Any], public_packet: Mapping[str, Any]
) -> tuple[str, ...]:
    failures: list[str] = []
    tasks = public_packet.get("review_tasks")
    expected = (
        {
            str(task.get("review_task_id")): task
            for task in tasks
            if isinstance(task, Mapping)
        }
        if isinstance(tasks, list)
        else {}
    )
    task = expected.get(str(review.get("review_task_id", "")))
    if review.get("schema") != "ProofLaunchTextCreativeHumanBlindReviewV1":
        failures.append("schema")
    if task is None:
        failures.append("review_task_binding")
    else:
        for field in ("pair_id", "pair_sha256", "reviewer_slot"):
            if review.get(field) != task.get(field):
                failures.append(field)
    pseudonym = str(review.get("reviewer_pseudonym") or "").strip()
    if not pseudonym or len(pseudonym) > 120:
        failures.append("reviewer_pseudonym")
    if review.get("human_attestation") != TEXT_BLIND_HUMAN_ATTESTATION:
        failures.append("human_attestation")
    if review.get("choice") not in {"left", "right", "abstain"}:
        failures.append("choice")
    if not str(review.get("reason") or "").strip():
        failures.append("reason")
    if not isinstance(review.get("critical_failure"), bool):
        failures.append("critical_failure")
    reviewed_at = review.get("reviewed_at")
    try:
        parsed = datetime.fromisoformat(str(reviewed_at).replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timezone required")
    except (TypeError, ValueError):
        failures.append("reviewed_at")
    if review.get("review_content_sha256") != text_blind_review_digest(review):
        failures.append("review_content_sha256")
    return tuple(dict.fromkeys(failures))


def aggregate_text_blind_reviews(
    public_packet: Mapping[str, Any],
    private_mapping: Mapping[str, Any],
    reviews: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Deblind completed human choices without automatically selecting a winner."""

    verify_text_blind_review_bundle(public_packet, private_mapping)
    expected_tasks = {
        str(task["review_task_id"]): task for task in public_packet["review_tasks"]
    }
    failures: list[str] = []
    observed_task_ids: set[str] = set()
    pseudonyms_by_slot: dict[int, set[str]] = defaultdict(set)
    pair_mapping = {str(row["pair_id"]): row for row in private_mapping["pairs"]}
    counts: dict[str, dict[str, int]] = {
        territory_id: {"preferred": 0, "eligible": 0, "abstain": 0, "critical": 0}
        for territory_id in _TERRITORY_IDS
    }
    for index, review in enumerate(reviews):
        row_failures = validate_text_blind_review(review, public_packet)
        failures.extend(f"review-{index + 1}:{failure}" for failure in row_failures)
        task_id = str(review.get("review_task_id", ""))
        if task_id in observed_task_ids:
            failures.append(f"duplicate_review_task:{task_id}")
        observed_task_ids.add(task_id)
        slot = review.get("reviewer_slot")
        if isinstance(slot, int) and not isinstance(slot, bool):
            pseudonyms_by_slot[slot].add(str(review.get("reviewer_pseudonym") or ""))
        mapping = pair_mapping.get(str(review.get("pair_id", "")))
        if mapping is None or row_failures:
            continue
        territory_id = str(mapping["candidate_territory_id"])
        if review.get("critical_failure") is True:
            counts[territory_id]["critical"] += 1
        choice = review.get("choice")
        if choice == "abstain":
            counts[territory_id]["abstain"] += 1
            continue
        counts[territory_id]["eligible"] += 1
        if choice == mapping["candidate_side"]:
            counts[territory_id]["preferred"] += 1

    missing = set(expected_tasks) - observed_task_ids
    unknown = observed_task_ids - set(expected_tasks)
    if missing:
        failures.append(f"missing_review_tasks:{len(missing)}")
    if unknown:
        failures.append(f"unknown_review_tasks:{len(unknown)}")
    if len(reviews) != 30:
        failures.append("review_count_must_equal_30")
    expected_slots = set(range(1, 6))
    if set(pseudonyms_by_slot) != expected_slots:
        failures.append("five_reviewer_slots_required")
    if any(len(names) != 1 or "" in names for names in pseudonyms_by_slot.values()):
        failures.append("reviewer_slot_identity_drift")
    stable_pseudonyms = {
        next(iter(names)) for names in pseudonyms_by_slot.values() if len(names) == 1
    }
    if len(stable_pseudonyms) != 5:
        failures.append("five_distinct_human_reviewers_required")

    territory_results: list[dict[str, Any]] = []
    for territory_id in _TERRITORY_IDS:
        row = counts[territory_id]
        eligible = row["eligible"]
        preferred = row["preferred"]
        rate = preferred / eligible if eligible else None
        lower = wilson_lower_bound(preferred, eligible) if eligible else None
        territory_results.append(
            {
                "territory_id": territory_id,
                **row,
                "preference_rate": round(rate, 6) if rate is not None else None,
                "wilson_lower_95": round(lower, 6) if lower is not None else None,
                "promotion_threshold_passed": bool(
                    eligible >= 8
                    and row["critical"] == 0
                    and rate is not None
                    and rate >= 0.60
                    and lower is not None
                    and lower > 0.50
                ),
            }
        )
    ordered = sorted(
        territory_results,
        key=lambda row: (
            row["promotion_threshold_passed"],
            row["wilson_lower_95"] if row["wilson_lower_95"] is not None else -1,
            row["preference_rate"] if row["preference_rate"] is not None else -1,
        ),
        reverse=True,
    )
    eligible_rows = [row for row in ordered if row["promotion_threshold_passed"]]
    unique_leader = bool(
        eligible_rows
        and (
            len(eligible_rows) == 1
            or (
                eligible_rows[0]["wilson_lower_95"],
                eligible_rows[0]["preference_rate"],
            )
            != (
                eligible_rows[1]["wilson_lower_95"],
                eligible_rows[1]["preference_rate"],
            )
        )
    )
    review_complete = not failures
    recommendation = eligible_rows[0]["territory_id"] if review_complete and unique_leader else None
    receipt: dict[str, Any] = {
        "schema": "ProofLaunchTextCreativeBlindReviewAggregateV1",
        "public_packet_sha256": public_packet["content_sha256"],
        "private_mapping_sha256": private_mapping["content_sha256"],
        "submitted_review_count": len(reviews),
        "expected_review_count": 30,
        "reviewer_identity_count": len(stable_pseudonyms),
        "review_complete": review_complete,
        "territory_results": territory_results,
        "recommended_territory_id": recommendation,
        "human_selection_eligible": recommendation is not None,
        "automatic_winner_selection_enabled": False,
        "winner_selected": False,
        "external_publish_executed": False,
        "failure_count": len(failures),
        "failures": failures,
        "truth_boundary": (
            "A complete aggregate reports blinded human preference against the deterministic "
            "baseline. Recommendation is not automatic selection, publication, causal lift, "
            "revenue proof, universal 4A quality or Top-1 standing."
        ),
    }
    receipt["content_sha256"] = _digest(receipt)
    return receipt


def write_text_challenger_bundle(
    output_dir: str | Path,
    *,
    plan: Mapping[str, Any],
    execution: Mapping[str, Any],
    public_packet: Mapping[str, Any] | None = None,
    private_mapping: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    root = Path(output_dir).expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        raise TextChallengerRunError("output directory must be empty")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    verify_text_challenger_plan(plan)
    verify_text_challenger_execution(execution)
    documents: dict[str, Mapping[str, Any]] = {
        "text-creative-challenger-plan.json": plan,
        "text-creative-challenger-execution.json": execution,
    }
    if (public_packet is None) != (private_mapping is None):
        raise TextChallengerRunError("public and private blind artifacts must be supplied together")
    if public_packet is not None and private_mapping is not None:
        verify_text_blind_review_bundle(public_packet, private_mapping)
        documents["text-creative-blind-review-public.json"] = public_packet
        documents["text-creative-blind-review-private.json"] = private_mapping
    output: dict[str, str] = {}
    for name, document in documents.items():
        path = root / name
        atomic_write_text(path, json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        path.chmod(0o600)
        output[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return output
