from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence


class GTMStrategyChallengerError(ValueError):
    """A local strategy candidate or its evidence violated the frozen contract."""


CANDIDATE_SCHEMA = "ProofLaunchZeroBudgetStrategyCandidateV1"
RECEIPT_SCHEMA = "ProofLaunchLocalStrategyChallengerReceiptV1"
_TOP_LEVEL_FIELDS = frozenset(
    {
        "strategy",
        "primary_channel",
        "channel_rationale",
        "zero_budget_loop",
        "experiment",
        "human_gate",
        "unsupported_claims",
    }
)
_EXPERIMENT_FIELDS = frozenset(
    {
        "treatment",
        "comparable_baseline",
        "observation_window_days",
        "primary_metric",
        "decision_rule",
    }
)
_HUMAN_GATE_FIELDS = frozenset({"role", "decision", "artifact"})
_CHANNELS = frozenset({"LinkedIn", "community", "partner", "owned"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UNPROVEN_EFFECT = (
    re.compile(r"\bguarantee(?:d|s)?\b", re.IGNORECASE),
    re.compile(r"\b(?:increase|improve|boost|raise|grow|reduce|decrease|shorten)(?:d|s|ing)?\b", re.IGNORECASE),
    re.compile(r"\b(?:close rate|conversion|revenue|roi|return on investment)\b", re.IGNORECASE),
    re.compile(r"\b\d+(?:\.\d+)?%\b"),
    re.compile(r"保证|必然|提升(?:营收|转化|销量)|降低(?:成本|周期)"),
)
_EARNED_MARKERS = (
    "publish",
    "share",
    "community",
    "partner",
    "interview",
    "outreach",
    "reply",
    "referral",
    "co-create",
    "contribute",
    "comment",
    "engage",
    "participate",
    "roundtable",
)
_PROOF_OBJECT_MARKERS = (
    "evidence",
    "proof",
    "teardown",
    "benchmark",
    "diagnostic",
    "checklist",
    "template",
    "artifact",
    "worksheet",
)
_ASSIGNMENT_MARKERS = (
    "matched",
    "random",
    "split",
)
_SAME_WINDOW_MARKERS = ("holdout", "same-window", "same window")


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _bounded_string(
    value: object,
    field: str,
    *,
    minimum: int = 1,
    maximum: int = 800,
) -> tuple[str | None, str | None]:
    if not isinstance(value, str):
        return None, f"{field} must be a string"
    normalized = re.sub(r"\s+", " ", value.strip())
    if len(normalized) < minimum or len(normalized) > maximum or "\x00" in normalized:
        return None, f"{field} must contain {minimum}..{maximum} safe characters"
    return normalized, None


def _has_unproven_effect(value: str) -> bool:
    return any(pattern.search(value) for pattern in _UNPROVEN_EFFECT)


def strategy_candidate_failures(value: object) -> tuple[str, ...]:
    failures: list[str] = []
    if not isinstance(value, Mapping):
        return ("candidate must be an object",)
    if frozenset(value) != _TOP_LEVEL_FIELDS:
        failures.append("candidate top-level fields must match the frozen schema exactly")

    strategy, error = _bounded_string(
        value.get("strategy"), "strategy", minimum=80, maximum=600
    )
    if error:
        failures.append(error)
    rationale, error = _bounded_string(
        value.get("channel_rationale"),
        "channel_rationale",
        minimum=48,
        maximum=500,
    )
    if error:
        failures.append(error)
    if value.get("primary_channel") not in _CHANNELS:
        failures.append("primary_channel must use the frozen channel vocabulary")
    for field, text in (("strategy", strategy), ("channel_rationale", rationale)):
        if text is not None and _has_unproven_effect(text):
            failures.append(f"{field} contains an unproven effect claim")

    loop = value.get("zero_budget_loop")
    normalized_steps: list[str] = []
    if not isinstance(loop, list) or len(loop) != 4:
        failures.append("zero_budget_loop must contain exactly four steps")
    else:
        for index, raw in enumerate(loop):
            step, error = _bounded_string(
                raw, f"zero_budget_loop[{index}]", minimum=40, maximum=420
            )
            if error:
                failures.append(error)
                continue
            assert step is not None
            normalized_steps.append(step)
            if _has_unproven_effect(step):
                failures.append(
                    f"zero_budget_loop[{index}] contains an unproven effect claim"
                )
            if re.search(r"\b(?:paid|ad spend|boosted post|media buy)\b", step, re.I):
                failures.append(f"zero_budget_loop[{index}] requires paid distribution")
        combined = " ".join(normalized_steps).casefold()
        earned_count = sum(marker in combined for marker in _EARNED_MARKERS)
        if earned_count < 2:
            failures.append("zero_budget_loop lacks two concrete earned-distribution mechanisms")
        if not any(marker in combined for marker in _PROOF_OBJECT_MARKERS):
            failures.append("zero_budget_loop lacks a reusable evidence or decision artifact")
        if "qualified" not in combined or "conversation" not in combined:
            failures.append(
                "zero_budget_loop must record qualified conversations instead of vanity engagement alone"
            )

    experiment = value.get("experiment")
    if not isinstance(experiment, Mapping):
        failures.append("experiment must be an object")
    else:
        if frozenset(experiment) != _EXPERIMENT_FIELDS:
            failures.append("experiment fields must match the frozen schema exactly")
        treatment, error = _bounded_string(
            experiment.get("treatment"), "experiment.treatment", minimum=40
        )
        if error:
            failures.append(error)
        baseline, error = _bounded_string(
            experiment.get("comparable_baseline"),
            "experiment.comparable_baseline",
            minimum=40,
        )
        if error:
            failures.append(error)
        elif baseline is not None:
            baseline_lower = baseline.casefold()
            if not any(marker in baseline_lower for marker in _ASSIGNMENT_MARKERS) or not any(
                marker in baseline_lower for marker in _SAME_WINDOW_MARKERS
            ):
                failures.append(
                    "experiment.comparable_baseline must bind matched/randomized/split assignment to a same-window holdout"
                )
        window = experiment.get("observation_window_days")
        if type(window) is not int or not 7 <= window <= 30:
            failures.append("experiment.observation_window_days must be an integer from 7 to 30")
        if experiment.get("primary_metric") != "qualified_conversations":
            failures.append("experiment.primary_metric must be qualified_conversations")
        rule, error = _bounded_string(
            experiment.get("decision_rule"),
            "experiment.decision_rule",
            minimum=48,
        )
        if error:
            failures.append(error)
        elif rule is not None:
            rule_lower = rule.casefold()
            if "qualified" not in rule_lower or "conversation" not in rule_lower:
                failures.append("experiment.decision_rule must use the primary metric")
            if not re.search(r"\b[1-9][0-9]*\b", rule):
                failures.append(
                    "experiment.decision_rule must preregister a non-zero minimum sample threshold"
                )
        if treatment is not None and _has_unproven_effect(treatment):
            failures.append("experiment.treatment contains an unproven effect claim")

    human_gate = value.get("human_gate")
    if not isinstance(human_gate, Mapping):
        failures.append("human_gate must be an object")
    else:
        if frozenset(human_gate) != _HUMAN_GATE_FIELDS:
            failures.append("human_gate fields must match the frozen schema exactly")
        human_text: dict[str, str] = {}
        for field in ("role", "artifact"):
            text, error = _bounded_string(
                human_gate.get(field), f"human_gate.{field}", minimum=4, maximum=300
            )
            if error:
                failures.append(error)
            elif text is not None:
                human_text[field] = text
        if human_gate.get("decision") != "approve_or_reject":
            failures.append("human_gate.decision must be approve_or_reject")
        artifact = human_text.get("artifact", "").casefold()
        if "qualified" not in artifact or "conversation" not in artifact:
            failures.append("human_gate.artifact must include the qualified-conversation ledger")

    unsupported = value.get("unsupported_claims")
    if not isinstance(unsupported, list) or not 1 <= len(unsupported) <= 8:
        failures.append("unsupported_claims must contain 1..8 explicit rejected claims")
    else:
        for index, raw in enumerate(unsupported):
            _text, error = _bounded_string(
                raw, f"unsupported_claims[{index}]", minimum=12, maximum=300
            )
            if error:
                failures.append(error)
    return tuple(dict.fromkeys(failures))


def validate_strategy_candidate(value: object) -> dict[str, Any]:
    failures = strategy_candidate_failures(value)
    if failures:
        raise GTMStrategyChallengerError("; ".join(failures))
    assert isinstance(value, Mapping)
    candidate = {"schema": CANDIDATE_SCHEMA, **dict(value)}
    candidate["content_sha256"] = _digest(candidate)
    return candidate


def extract_strategy_candidate(raw_output: str) -> dict[str, Any]:
    if not isinstance(raw_output, str) or not raw_output.strip():
        raise GTMStrategyChallengerError("model output is empty")
    text = raw_output.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise GTMStrategyChallengerError("model output has no complete JSON object")
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError as error:
        raise GTMStrategyChallengerError("model output JSON is invalid") from error
    if not isinstance(value, dict):
        raise GTMStrategyChallengerError("model output JSON must be an object")
    return value


def compile_strategy_challenger_receipt(
    *,
    model_id: str,
    model_revision: str,
    model_manifest_sha256: str,
    device_family: str,
    attempts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not model_id or not model_revision or not _SHA256.fullmatch(model_manifest_sha256):
        raise GTMStrategyChallengerError("model identity is incomplete")
    if not 1 <= len(attempts) <= 2:
        raise GTMStrategyChallengerError("challenger permits one draft and one bounded repair")
    normalized_attempts: list[dict[str, Any]] = []
    accepted_candidate: dict[str, Any] | None = None
    for index, attempt in enumerate(attempts, start=1):
        if not isinstance(attempt, Mapping):
            raise GTMStrategyChallengerError("attempt must be an object")
        raw_output = str(attempt.get("raw_output", ""))
        try:
            parsed = extract_strategy_candidate(raw_output)
            failures = strategy_candidate_failures(parsed)
        except GTMStrategyChallengerError as error:
            parsed = None
            failures = (str(error),)
        accepted = not failures
        if accepted:
            accepted_candidate = validate_strategy_candidate(parsed)
        normalized_attempts.append(
            {
                "attempt": index,
                "kind": "draft" if index == 1 else "bounded_repair",
                "elapsed_seconds": round(float(attempt.get("elapsed_seconds", 0.0)), 6),
                "generated_token_count": int(attempt.get("generated_token_count", 0)),
                "source": str(attempt.get("source", "fresh_generation"))[:160],
                "raw_output_sha256": hashlib.sha256(raw_output.encode("utf-8")).hexdigest(),
                "json_complete": parsed is not None,
                "candidate_snapshot": parsed,
                "accepted": accepted,
                "failures": list(failures),
            }
        )
        if accepted and index != len(attempts):
            raise GTMStrategyChallengerError("execution continued after an accepted candidate")
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "execution": {
            "provider": "mlx_local",
            "device_family": device_family,
            "model_id": model_id,
            "model_revision": model_revision,
            "model_manifest_sha256": model_manifest_sha256,
            "network_download_performed": False,
            "cloud_api_calls": 0,
            "training_observed": False,
            "radeon_local_inference_observed": False,
        },
        "attempts": normalized_attempts,
        "accepted": accepted_candidate is not None,
        "accepted_candidate": accepted_candidate,
        "automatic_release_authority": False,
        "automatic_training_admission": False,
        "four_a_claim_eligible": False,
        "top1_claim_eligible": False,
        "causal_effect_claim_eligible": False,
        "truth_boundary": (
            "This receipt proves bounded offline local candidate generation and deterministic "
            "contract validation only. It is not training, Radeon execution, independent human "
            "preference, production effect, causal lift, revenue, 4A quality or Top-1 evidence."
        ),
    }
    receipt["content_sha256"] = _digest(receipt)
    return receipt


def validate_strategy_challenger_receipt(value: object) -> None:
    if not isinstance(value, Mapping) or value.get("schema") != RECEIPT_SCHEMA:
        raise GTMStrategyChallengerError("challenger receipt schema is invalid")
    unsigned = dict(value)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise GTMStrategyChallengerError("challenger receipt digest is invalid")
    execution = value.get("execution")
    if not isinstance(execution, Mapping):
        raise GTMStrategyChallengerError("challenger execution is missing")
    if any(
        execution.get(field) is not expected
        for field, expected in (
            ("network_download_performed", False),
            ("training_observed", False),
            ("radeon_local_inference_observed", False),
        )
    ) or execution.get("cloud_api_calls") != 0:
        raise GTMStrategyChallengerError("challenger execution boundary was upgraded")
    for field in (
        "automatic_release_authority",
        "automatic_training_admission",
        "four_a_claim_eligible",
        "top1_claim_eligible",
        "causal_effect_claim_eligible",
    ):
        if value.get(field) is not False:
            raise GTMStrategyChallengerError(f"{field} must remain false")
    candidate = value.get("accepted_candidate")
    if value.get("accepted") is True:
        if not isinstance(candidate, Mapping):
            raise GTMStrategyChallengerError("accepted receipt lacks a candidate")
        candidate_unsigned = dict(candidate)
        digest = candidate_unsigned.pop("content_sha256", None)
        if candidate_unsigned.pop("schema", None) != CANDIDATE_SCHEMA:
            raise GTMStrategyChallengerError("accepted candidate schema is invalid")
        validated = validate_strategy_candidate(candidate_unsigned)
        if digest != validated["content_sha256"]:
            raise GTMStrategyChallengerError("accepted candidate digest is invalid")
    elif candidate is not None:
        raise GTMStrategyChallengerError("rejected receipt cannot expose accepted candidate")
