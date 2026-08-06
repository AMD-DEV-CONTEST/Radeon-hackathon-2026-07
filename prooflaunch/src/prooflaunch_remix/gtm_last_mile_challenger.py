from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping


class LastMileChallengerError(ValueError):
    """Raised when a generated last-mile challenger violates the frozen contract."""


LANE_FIELDS: Mapping[str, tuple[str, ...]] = {
    "integrated_gtm_strategy": (
        "diagnosis",
        "strategic_choice",
        "big_idea",
        "channel_sequence",
        "commercial_hypothesis",
    ),
    "organic_social_copy": ("hook", "body", "cta"),
    "landing_page": ("headline", "subhead", "proof", "objection", "cta"),
    "lifecycle_email": ("subject", "preheader", "body", "cta"),
    "content_schedule": ("sequence_logic", "days"),
    "seo": ("primary_intent", "title", "outline", "internal_links"),
    "geo": ("question", "direct_answer", "evidence_needed", "entity_statement"),
    "advertising": ("audience", "creative_route", "copy", "test_design"),
    "analytics": ("primary_metric", "leading_signals", "stop_rules", "decision_rule"),
    "employee_agent": ("graph", "loop", "harness", "approval_points"),
    "cross_device_memory": ("remember", "retrieve", "conflict_rule", "privacy_rule"),
}

FORBIDDEN_PATTERNS = (
    re.compile(r"\bguarantee(?:d|s)?\b", re.I),
    re.compile(r"\btop[- ]?1\b", re.I),
    re.compile(r"\b4A[- ]?(?:grade|quality|level)?\b", re.I),
    re.compile(r"\b(?:increased?|improved?|lifted?|reduced?)\s+\d+(?:\.\d+)?%", re.I),
    re.compile(r"\b(?:revenue|roi|conversion)\s+(?:increased?|improved?|lifted?)\b", re.I),
)


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


def extract_json_object(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw.strip():
        raise LastMileChallengerError("model output is empty")
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    decoder = json.JSONDecoder()
    starts = [index for index, char in enumerate(text) if char == "{"]
    for start in starts:
        try:
            value, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise LastMileChallengerError("model output contains no JSON object")


def challenger_failures(value: object) -> tuple[str, ...]:
    failures: list[str] = []
    if not isinstance(value, dict):
        return ("challenger must be an object",)
    if set(value) != set(LANE_FIELDS):
        missing = sorted(set(LANE_FIELDS) - set(value))
        extra = sorted(set(value) - set(LANE_FIELDS))
        failures.append(f"top-level lane mismatch: missing={missing}, extra={extra}")
    for lane, fields in LANE_FIELDS.items():
        payload = value.get(lane)
        if not isinstance(payload, dict):
            failures.append(f"{lane} must be an object")
            continue
        missing_fields = [field for field in fields if field not in payload]
        if missing_fields:
            failures.append(f"{lane} is missing {missing_fields}")
        if not any(
            isinstance(item, str) and item.strip()
            for item in payload.values()
        ):
            failures.append(f"{lane} has no non-empty prose")
        serialized = canonical_json(payload)
        if len(serialized) < 80:
            failures.append(f"{lane} is too shallow")
        if len(serialized) > 8_000:
            failures.append(f"{lane} exceeds the bounded artifact size")
    serialized = canonical_json(value)
    for pattern in FORBIDDEN_PATTERNS:
        if pattern.search(serialized):
            failures.append(f"unsupported outcome or status claim: {pattern.pattern}")
    for token in (
        "intended audience",
        "owner context not supplied",
        "this decision may occur in",
        "before choosing review",
        "to address needs reliable evidence",
        "lorem ipsum",
    ):
        if token in serialized.casefold():
            failures.append(f"placeholder or known copy defect: {token}")
    return tuple(failures)


def compile_receipt(
    *,
    model_id: str,
    model_revision: str,
    model_manifest_sha256: str,
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    accepted: dict[str, Any] | None = None
    sealed_attempts: list[dict[str, Any]] = []
    for index, attempt in enumerate(attempts, start=1):
        raw = str(attempt.get("raw_output", ""))
        try:
            candidate = extract_json_object(raw)
            failures = challenger_failures(candidate)
        except LastMileChallengerError as error:
            candidate = None
            failures = (str(error),)
        sealed_attempts.append(
            {
                "attempt": index,
                "source": str(attempt.get("source", "generation")),
                "elapsed_seconds": round(float(attempt.get("elapsed_seconds", 0.0)), 6),
                "generated_token_count": int(attempt.get("generated_token_count", 0)),
                "raw_output_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                "contract_passed": not failures,
                "failures": list(failures),
            }
        )
        if not failures and candidate is not None and accepted is None:
            accepted = candidate
    core: dict[str, Any] = {
        "schema": "ProofLaunchGTMLastMileChallengerReceiptV1",
        "status": "generated_validated_unreviewed" if accepted else "rejected_by_harness",
        "execution": {
            "provider": "mlx_local",
            "device_family": "Apple Metal",
            "model_id": model_id,
            "model_revision": model_revision,
            "model_manifest_sha256": model_manifest_sha256,
            "network_download_performed": False,
            "cloud_api_calls": 0,
            "training_observed": False,
            "radeon_local_inference_observed": False,
        },
        "attempts": sealed_attempts,
        "accepted": accepted is not None,
        "accepted_candidate": accepted,
        "lane_count": len(LANE_FIELDS) if accepted else 0,
        "human_review_completed": False,
        "winner_selected": False,
        "automatic_release_authority": False,
        "four_a_claim_eligible": False,
        "top1_claim_eligible": False,
        "truth_boundary": (
            "This receipt proves bounded offline local challenger generation and deterministic "
            "contract validation only. It is not a human preference verdict, training, Radeon "
            "execution, publication, business lift, 4A parity or Top-1 evidence."
        ),
    }
    core["content_sha256"] = digest(core)
    return core


def validate_receipt(value: object) -> None:
    if not isinstance(value, dict) or value.get("schema") != "ProofLaunchGTMLastMileChallengerReceiptV1":
        raise LastMileChallengerError("challenger receipt schema is invalid")
    unsigned = dict(value)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != digest(unsigned):
        raise LastMileChallengerError("challenger receipt digest is invalid")
    execution = value.get("execution")
    if not isinstance(execution, dict):
        raise LastMileChallengerError("challenger execution is missing")
    for field in ("network_download_performed", "training_observed", "radeon_local_inference_observed"):
        if execution.get(field) is not False:
            raise LastMileChallengerError(f"challenger boundary upgraded: {field}")
    if execution.get("cloud_api_calls") != 0:
        raise LastMileChallengerError("challenger boundary upgraded: cloud_api_calls")
    for field in ("human_review_completed", "winner_selected", "automatic_release_authority", "four_a_claim_eligible", "top1_claim_eligible"):
        if value.get(field) is not False:
            raise LastMileChallengerError(f"challenger authority upgraded: {field}")
    if value.get("accepted") is True:
        failures = challenger_failures(value.get("accepted_candidate"))
        if failures:
            raise LastMileChallengerError("accepted candidate no longer passes: " + "; ".join(failures))
