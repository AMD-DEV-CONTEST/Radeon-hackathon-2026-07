from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Mapping


CONFIG_SCHEMA = "ProofLaunchCodexContentSchedulingSuperChallengerDraftV1"
OUTPUT_SCHEMA = "ProofLaunchContentSchedulingNamedPKSuperChallengerV1"
EXPECTED_PRODUCTS = (
    "Hootsuite", "Sprout Social", "Buffer", "Later", "Metricool",
    "Planable", "Loomly", "Publer", "SocialBee", "Postiz",
)
DEFAULT_CHANNEL_COUNTS = {"linkedin_organic": 4, "partner_communities": 2, "lifecycle_email": 1}


class ContentSchedulingNamedPKError(ValueError):
    pass


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def compile_schedule(
    config: Mapping[str, Any],
    *,
    source_candidate_sha256: str,
    source_artifact_sha256_by_path: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if config.get("schema") != CONFIG_SCHEMA:
        raise ContentSchedulingNamedPKError("schedule config schema drifted")
    slots = config.get("slots")
    stress = config.get("opponent_stress_tests")
    oss = config.get("open_source_modifications")
    if not isinstance(slots, list) or len(slots) != 7:
        raise ContentSchedulingNamedPKError("exactly seven content jobs are required")
    if not isinstance(stress, Mapping) or tuple(stress) != EXPECTED_PRODUCTS:
        raise ContentSchedulingNamedPKError("ten named scheduling stress tests are required")
    if not isinstance(oss, list) or {row.get("project_id") for row in oss if isinstance(row, Mapping)} != {"postiz", "temporal", "openlineage"}:
        raise ContentSchedulingNamedPKError("open-source scheduling modification set drifted")
    expected_channel_counts = config.get("expected_channel_counts", DEFAULT_CHANNEL_COUNTS)
    if (
        not isinstance(expected_channel_counts, Mapping)
        or not expected_channel_counts
        or any(not isinstance(channel, str) or not channel or not isinstance(count, int) or count < 1 for channel, count in expected_channel_counts.items())
        or sum(expected_channel_counts.values()) != 7
    ):
        raise ContentSchedulingNamedPKError("expected channel counts must declare all seven jobs")
    frequency_cap = config.get("frequency_cap")
    if not isinstance(frequency_cap, Mapping):
        raise ContentSchedulingNamedPKError("frequency cap is missing")
    maximum_per_channel = int(frequency_cap.get("maximum_slots_per_channel", 0))
    maximum_per_local_date = int(frequency_cap.get("maximum_slots_per_local_date", 0))
    minimum_inter_slot_hours = int(frequency_cap.get("minimum_inter_slot_hours", 0))
    if maximum_per_channel < 1 or maximum_per_local_date < 1 or minimum_inter_slot_hours < 1:
        raise ContentSchedulingNamedPKError("frequency cap values are invalid")
    ids = [row.get("slot_id") for row in slots]
    hooks = [str(row.get("hook", "")).casefold() for row in slots]
    if len(set(ids)) != 7 or len(set(hooks)) != 7 or any(len(hook) < 24 for hook in hooks):
        raise ContentSchedulingNamedPKError("slot identities and hooks must be distinct and substantive")
    counts: dict[str, int] = {}
    prior: datetime | None = None
    local_date_counts: dict[str, int] = {}
    approval_queue = []
    compiled_slots = []
    for row in slots:
        scheduled = _parse(str(row.get("scheduled_at_utc")))
        review = _parse(str(row.get("review_due_at_utc")))
        if (scheduled - review).total_seconds() < 24 * 3600:
            raise ContentSchedulingNamedPKError("every slot needs at least 24 hours of review")
        if prior is not None and (scheduled - prior).total_seconds() < minimum_inter_slot_hours * 3600:
            raise ContentSchedulingNamedPKError("adjacent slots violate the configured inter-slot cap")
        prior = scheduled
        local_date = scheduled.date().isoformat()
        local_date_counts[local_date] = local_date_counts.get(local_date, 0) + 1
        if local_date_counts[local_date] > maximum_per_local_date:
            raise ContentSchedulingNamedPKError("local-date slot count exceeds the configured cap")
        channel = str(row.get("channel"))
        counts[channel] = counts.get(channel, 0) + 1
        if counts[channel] > maximum_per_channel:
            raise ContentSchedulingNamedPKError("channel slot count exceeds the configured cap")
        for field in ("format", "creative_move", "cta", "intended_learning", "decision_rule", "failure_recovery", "source_asset"):
            if len(str(row.get(field, "")).strip()) < 12:
                raise ContentSchedulingNamedPKError(f"slot {row.get('slot_id')} has a thin {field}")
        compiled = dict(row)
        source_path = str(row["source_asset"]).split("#", 1)[0]
        source_artifact_sha256 = (
            source_artifact_sha256_by_path.get(source_path)
            if source_artifact_sha256_by_path is not None
            else source_candidate_sha256
        )
        if not isinstance(source_artifact_sha256, str) or len(source_artifact_sha256) != 64:
            raise ContentSchedulingNamedPKError(f"slot {row.get('slot_id')} has no content-bound source digest")
        compiled.update({
            "status": "draft_pending_content_bound_human_review",
            "release_mode": "named_human_review_then_manual_activation",
            "external_activation_executed": False,
            "source_candidate_sha256": source_candidate_sha256,
            "source_artifact_sha256": source_artifact_sha256,
        })
        compiled_slots.append(compiled)
        approval_queue.append({
            "slot_id": row["slot_id"],
            "review_due_at_utc": row["review_due_at_utc"],
            "required_actor": "named_human_release_owner",
            "decision": "pending",
        })
    if counts != dict(expected_channel_counts):
        raise ContentSchedulingNamedPKError("channel mix drifted")
    payload = {
        "schema": OUTPUT_SCHEMA,
        "campaign_id": config["campaign_id"],
        "timezone": config["timezone"],
        "operating_thesis": config["operating_thesis"],
        "source_candidate_sha256": source_candidate_sha256,
        "source_artifact_count": len({str(row["source_asset"]).split("#", 1)[0] for row in slots}),
        "slot_count": 7,
        "channel_slot_counts": counts,
        "slots": compiled_slots,
        "approval_queue": approval_queue,
        "frequency_cap": dict(frequency_cap),
        "opponent_stress_tests": dict(stress),
        "open_source_modifications": [dict(row) for row in oss],
        "automatic_publish_enabled": False,
        "automatic_rescheduling_enabled": False,
        "automatic_strategy_mutation_enabled": False,
        "external_activation_executed": False,
        "qualified_human_review_count": 0,
        "completed_named_product_pk_count": 0,
        "candidate_win_count": 0,
        "release_eligible": False,
        "truth_boundary": config["truth_boundary"],
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_schedule(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != OUTPUT_SCHEMA or supplied != _digest(unsigned):
        raise ContentSchedulingNamedPKError("schedule seal is invalid")
    if payload.get("slot_count") != 7 or payload.get("completed_named_product_pk_count") != 0 or payload.get("candidate_win_count") != 0:
        raise ContentSchedulingNamedPKError("schedule truth boundary drifted")
    if any(payload.get(field) is not False for field in ("automatic_publish_enabled", "automatic_rescheduling_enabled", "automatic_strategy_mutation_enabled", "external_activation_executed", "release_eligible")):
        raise ContentSchedulingNamedPKError("schedule escaped human authority")


__all__ = ["ContentSchedulingNamedPKError", "compile_schedule", "verify_schedule"]
