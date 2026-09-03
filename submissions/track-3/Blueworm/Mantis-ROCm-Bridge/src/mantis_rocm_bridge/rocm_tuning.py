"""Pure validation and promotion logic for bounded ROCm microbenchmarks."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import ContractError


def _finite_number(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{context} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ContractError(f"{context} must be finite")
    return result


def latency_summary(samples: Sequence[Any]) -> dict[str, float]:
    """Return deterministic linearly interpolated p50/p95/p99 milliseconds."""

    if not isinstance(samples, (list, tuple)) or not samples:
        raise ContractError("latency samples must be a non-empty list")
    ordered = sorted(
        _finite_number(value, "latency sample") for value in samples
    )
    if any(value <= 0.0 for value in ordered):
        raise ContractError("latency samples must be positive")

    def percentile(fraction: float) -> float:
        position = (len(ordered) - 1) * fraction
        lower = int(math.floor(position))
        upper = int(math.ceil(position))
        if lower == upper:
            return ordered[lower]
        weight = position - lower
        return ordered[lower] * (1.0 - weight) + ordered[upper] * weight

    return {
        "p50_ms": percentile(0.50),
        "p95_ms": percentile(0.95),
        "p99_ms": percentile(0.99),
    }


def validate_tuning_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the compiler-owned subset of a tuning plan."""

    if not isinstance(plan, Mapping):
        raise ContractError("tuning plan must be an object")
    if (
        plan.get("schema_version") != 1
        or plan.get("kind") != "rocm_act_shape_tuning_plan"
    ):
        raise ContractError("unsupported tuning plan")
    morphology = plan.get("morphology")
    model = plan.get("benchmark_model")
    protocol = plan.get("protocol")
    thresholds = plan.get("admission_thresholds")
    profiles = plan.get("profiles")
    if not all(
        isinstance(value, Mapping)
        for value in (morphology, model, protocol, thresholds)
    ):
        raise ContractError("tuning plan sections must be objects")
    for key in (
        "policy_state_dimension",
        "policy_action_dimension",
        "act_chunk_size",
    ):
        value = morphology.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ContractError(f"morphology.{key} must be a positive integer")
    for key in ("d_model", "nhead", "encoder_layers", "sequence_length", "batch_size"):
        value = model.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ContractError(f"benchmark_model.{key} must be a positive integer")
    if model["d_model"] % model["nhead"] != 0:
        raise ContractError("benchmark d_model must be divisible by nhead")
    for key in ("warmup_iterations", "measured_iterations"):
        value = protocol.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ContractError(f"protocol.{key} must be a positive integer")
    if not isinstance(profiles, list) or len(profiles) < 2:
        raise ContractError("tuning plan requires a baseline and a candidate")
    profile_ids: list[str] = []
    baseline_count = 0
    for index, profile in enumerate(profiles):
        if not isinstance(profile, Mapping):
            raise ContractError(f"profiles[{index}] must be an object")
        profile_id = profile.get("profile_id")
        if not isinstance(profile_id, str) or not profile_id:
            raise ContractError(f"profiles[{index}].profile_id is invalid")
        profile_ids.append(profile_id)
        if profile.get("precision") not in ("float32", "bfloat16", "float16"):
            raise ContractError(f"profiles[{index}].precision is unsupported")
        if profile.get("role") == "baseline":
            baseline_count += 1
            if profile.get("precision") != "float32":
                raise ContractError("the baseline must use float32")
        elif profile.get("role") != "candidate":
            raise ContractError(f"profiles[{index}].role is unsupported")
    if len(profile_ids) != len(set(profile_ids)) or baseline_count != 1:
        raise ContractError("profile IDs must be unique with exactly one baseline")
    for key in (
        "cosine_similarity_minimum",
        "maximum_absolute_error",
        "minimum_inference_or_training_speedup_fraction",
    ):
        _finite_number(thresholds.get(key), f"admission_thresholds.{key}")
    if thresholds.get("finite_outputs_required") is not True:
        raise ContractError("finite outputs must be required")
    if plan.get("maximum_promotion_state") != "ROCM_TUNING_MEASURED":
        raise ContractError("tuning plan promotion ceiling disagrees")
    if plan.get("amd_deployable") is not False:
        raise ContractError("microbenchmark plan cannot predeclare AMD deployability")
    return dict(plan)


def strict_rocm_device_receipt(device: Mapping[str, Any]) -> bool:
    """Return whether a device receipt establishes the narrow ROCm identity."""

    if not isinstance(device, Mapping):
        return False
    name = str(device.get("device_name", "")).lower()
    hip = device.get("hip_version")
    return (
        device.get("strict_rocm") is True
        and device.get("torch_device") == "cuda:0"
        and isinstance(hip, str)
        and bool(hip)
        and device.get("device_count") == 1
        and ("amd" in name or "radeon" in name)
    )


def _measured_profile(profile: Mapping[str, Any], context: str) -> dict[str, Any]:
    if profile.get("status") != "measured":
        raise ContractError(f"{context} is not measured")
    inference = profile.get("inference")
    training = profile.get("training")
    if not isinstance(inference, Mapping) or not isinstance(training, Mapping):
        raise ContractError(f"{context} measurement sections are missing")
    inference_summary = latency_summary(inference.get("latency_ms_samples"))
    training_summary = latency_summary(training.get("latency_ms_samples"))
    for phase, value in (("inference", inference), ("training", training)):
        peak = value.get("peak_memory_bytes")
        if isinstance(peak, bool) or not isinstance(peak, int) or peak < 0:
            raise ContractError(f"{context}.{phase}.peak_memory_bytes is invalid")
    return {
        "inference": inference_summary,
        "training": training_summary,
        "output_finite": profile.get("output_finite") is True,
        "max_abs_error": _finite_number(
            profile.get("max_abs_error"), f"{context}.max_abs_error"
        ),
        "cosine_similarity": _finite_number(
            profile.get("cosine_similarity"), f"{context}.cosine_similarity"
        ),
    }


def evaluate_benchmark_receipt(
    plan: Mapping[str, Any], receipt: Mapping[str, Any]
) -> dict[str, Any]:
    """Evaluate a same-device benchmark without promoting ACT task quality."""

    validated_plan = validate_tuning_plan(plan)
    if not isinstance(receipt, Mapping):
        raise ContractError("benchmark receipt must be an object")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("kind") != "rocm_act_shape_benchmark_receipt"
    ):
        raise ContractError("unsupported benchmark receipt")
    execution_mode = receipt.get("execution_mode")
    if execution_mode not in ("rocm", "cpu_test_only"):
        raise ContractError("benchmark execution mode is invalid")
    strict_rocm = strict_rocm_device_receipt(receipt.get("device", {}))
    if execution_mode == "rocm" and not strict_rocm:
        raise ContractError("ROCm receipt does not establish a strict AMD device")
    if execution_mode == "cpu_test_only" and strict_rocm:
        raise ContractError("CPU test-only receipt cannot claim strict ROCm")

    profile_receipts = receipt.get("profiles")
    if not isinstance(profile_receipts, list):
        raise ContractError("benchmark receipt profiles must be a list")
    by_id: dict[str, Mapping[str, Any]] = {}
    for index, profile in enumerate(profile_receipts):
        if not isinstance(profile, Mapping):
            raise ContractError(f"receipt profiles[{index}] must be an object")
        profile_id = profile.get("profile_id")
        if not isinstance(profile_id, str) or profile_id in by_id:
            raise ContractError("receipt profile IDs are missing or duplicated")
        by_id[profile_id] = profile
    expected_ids = [profile["profile_id"] for profile in validated_plan["profiles"]]
    if set(by_id) != set(expected_ids):
        raise ContractError("receipt profile set disagrees with the tuning plan")

    baseline_plan = next(
        item for item in validated_plan["profiles"] if item["role"] == "baseline"
    )
    baseline = _measured_profile(
        by_id[baseline_plan["profile_id"]], "baseline"
    )
    thresholds = validated_plan["admission_thresholds"]
    decisions: list[dict[str, Any]] = []
    for candidate_plan in (
        item for item in validated_plan["profiles"] if item["role"] == "candidate"
    ):
        candidate_receipt = by_id[candidate_plan["profile_id"]]
        if candidate_receipt.get("status") == "unsupported":
            decisions.append(
                {
                    "profile_id": candidate_plan["profile_id"],
                    "status": "unsupported",
                    "admitted": False,
                    "reason": str(
                        candidate_receipt.get(
                            "reason", "precision profile is unsupported"
                        )
                    ),
                }
            )
            continue
        candidate = _measured_profile(
            candidate_receipt, f"candidate {candidate_plan['profile_id']}"
        )
        inference_speedup = (
            baseline["inference"]["p50_ms"] / candidate["inference"]["p50_ms"]
        ) - 1.0
        training_speedup = (
            baseline["training"]["p50_ms"] / candidate["training"]["p50_ms"]
        ) - 1.0
        finite_pass = candidate["output_finite"]
        cosine_pass = (
            candidate["cosine_similarity"]
            >= thresholds["cosine_similarity_minimum"]
        )
        error_pass = (
            candidate["max_abs_error"] <= thresholds["maximum_absolute_error"]
        )
        speed_pass = (
            max(inference_speedup, training_speedup)
            >= thresholds["minimum_inference_or_training_speedup_fraction"]
        )
        admitted = finite_pass and cosine_pass and error_pass and speed_pass
        decisions.append(
            {
                "profile_id": candidate_plan["profile_id"],
                "status": "measured",
                "admitted": admitted,
                "inference_speedup_fraction": inference_speedup,
                "training_speedup_fraction": training_speedup,
                "finite_pass": finite_pass,
                "cosine_pass": cosine_pass,
                "maximum_absolute_error_pass": error_pass,
                "speed_pass": speed_pass,
            }
        )

    admitted = [item for item in decisions if item["admitted"]]
    promoted = (
        max(
            admitted,
            key=lambda item: max(
                item["inference_speedup_fraction"],
                item["training_speedup_fraction"],
            ),
        )["profile_id"]
        if admitted
        else None
    )
    return {
        "schema_version": 1,
        "kind": "rocm_act_shape_tuning_decision",
        "current_state": (
            "ROCM_TUNING_MEASURED" if strict_rocm else "CPU_TEST_ONLY"
        ),
        "strict_rocm_device": strict_rocm,
        "microbenchmark_promotable": promoted is not None,
        "promoted_candidate_id": promoted,
        "candidate_decisions": decisions,
        "act_quality_promoted": False,
        "amd_deployable": False,
        "claim_boundary": (
            "This decision covers only a synthetic ACT-shape microbenchmark; "
            "dataset admission, checkpoint quality, task success, and end-to-end "
            "training remain unverified."
        ),
    }


def load_json_object(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"JSON root must be an object: {path}")
    return value


def write_json_exclusive(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
