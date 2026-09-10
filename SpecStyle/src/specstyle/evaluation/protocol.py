"""Frozen preregistration contract for formal five-arm evaluation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final

from specstyle.calibration.evidence_io import (
    _count,
    _exact,
    _float,
    _load_canonical,
    _sha,
    _text,
    canonical_json,
    evidence_sha256,
)
from specstyle.errors import DomainError
from specstyle.production.context_config import (
    require_validated_production_threshold,
)

FORMAL_ARMS: Final[tuple[str, ...]] = (
    "A_single_pass",
    "B_random_retry",
    "C_verifier_best_of_k",
    "D_directed_no_guardrail",
    "E_full_specstyle",
)

_PROTOCOL_KEYS = {
    "schema_version",
    "study_id",
    "evidence_class",
    "dataset_manifest_sha256",
    "generation_materials_sha256s",
    "input_ids",
    "initial_request_sha256s",
    "bindings",
    "arms",
    "budget",
    "seed_schedules",
    "strategies",
    "blind",
    "statistics",
    "missingness_rule",
}
_BINDING_KEYS = {
    "compiler_sha256",
    "final_qa_contract_sha256",
    "model_supply_sha256",
    "preprocessor_sha256",
    "production_context_sha256",
    "runtime_sha256",
    "threshold_profile_sha256",
}
_STRATEGY_KEYS = {
    "a_strategy_contract_sha256",
    "b_strategy_contract_sha256",
    "c_strategy_contract_sha256",
    "c_tie_break",
    "c_utility_sha256",
    "d_guardrail_mode",
    "d_strategy_contract_sha256",
    "e_guardrail_mode",
    "e_strategy_contract_sha256",
}
_STATISTIC_KEYS = {
    "bootstrap_resamples",
    "bootstrap_seed",
    "confidence_level",
    "method",
    "minimum_effect",
    "multiple_comparison",
    "noninferiority_margin",
    "sample_size",
}
_SEALED_KEYS = {
    "schema_version",
    "protocol_sha256",
    "production_approval_sha256",
    "production_context_sha256",
    "repo_sha",
    "sealed_at",
    "threshold_profile_sha256",
    "trust_level",
}


def _timestamp(value: object, name: str) -> str:
    text = _text(value, name)
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise DomainError(f"invalid {name}") from None
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != text:
        raise DomainError(f"invalid {name}")
    return text


def _input_ids(value: object) -> tuple[str, ...]:
    if type(value) is not list or not value:
        raise DomainError("invalid evaluation protocol")
    identifiers = tuple(_text(item, "evaluation input id") for item in value)
    if len(set(identifiers)) != len(identifiers):
        raise DomainError("invalid evaluation protocol")
    return identifiers


def _validate_bindings(value: object) -> None:
    bindings = _exact(value, _BINDING_KEYS, "evaluation protocol bindings")
    for name in sorted(_BINDING_KEYS):
        _sha(bindings[name], name)


def _validate_strategies(value: object) -> None:
    strategies = _exact(value, _STRATEGY_KEYS, "evaluation strategies")
    for name in _STRATEGY_KEYS - {
        "c_tie_break",
        "d_guardrail_mode",
        "e_guardrail_mode",
    }:
        _sha(strategies[name], name)
    if (
        strategies["c_tie_break"] != "lowest_seed_index"
        or strategies["d_guardrail_mode"] != "DISABLED_EVALUATION_ONLY"
        or strategies["e_guardrail_mode"] != "ENFORCED"
    ):
        raise DomainError("invalid evaluation protocol")


def _validate_blind(value: object) -> None:
    blind = _exact(
        value,
        {
            "adjudication",
            "minimum_raters_per_artifact",
            "protocol_sha256",
            "randomization_protocol_sha256",
        },
        "evaluation blind protocol",
    )
    raters = _count(blind["minimum_raters_per_artifact"], "minimum raters", minimum=1)
    if blind["adjudication"] != "majority_boolean" or raters % 2 == 0:
        raise DomainError("invalid evaluation protocol")
    _sha(blind["protocol_sha256"], "blind protocol sha256")
    _sha(
        blind["randomization_protocol_sha256"],
        "blind randomization protocol sha256",
    )


def _validate_statistics(value: object, input_count: int) -> None:
    stats = _exact(value, _STATISTIC_KEYS, "evaluation statistics")
    confidence = _float(stats["confidence_level"], "confidence level")
    minimum_effect = _float(stats["minimum_effect"], "minimum effect")
    margin = _float(stats["noninferiority_margin"], "noninferiority margin")
    if (
        _count(stats["sample_size"], "sample size", minimum=1) != input_count
        or _count(stats["bootstrap_resamples"], "bootstrap resamples", minimum=1000)
        < 1000
        or _count(stats["bootstrap_seed"], "bootstrap seed") < 0
        or not 0.0 < confidence < 1.0
        or not 0.0 < minimum_effect <= 1.0
        or not 0.0 < margin < 1.0
        or stats["method"] != "paired_percentile_bootstrap_bonferroni"
        or stats["multiple_comparison"] != "bonferroni_six_one_sided"
    ):
        raise DomainError("invalid evaluation protocol")


def _validate_schedules(value: object, inputs: tuple[str, ...], budget: int) -> None:
    if type(value) is not dict or set(value) != set(inputs):
        raise DomainError("invalid evaluation protocol")
    for input_id in inputs:
        schedule = value[input_id]
        if (
            type(schedule) is not list
            or len(schedule) != budget
            or any(
                type(seed) is not int or isinstance(seed, bool) or not 0 <= seed < 2**63
                for seed in schedule
            )
            or len(set(schedule)) != len(schedule)
        ):
            raise DomainError("invalid evaluation protocol")


def _validate_initial_requests(value: object, inputs: tuple[str, ...]) -> None:
    if type(value) is not dict or set(value) != set(inputs):
        raise DomainError("invalid evaluation protocol")
    for input_id in inputs:
        _sha(value[input_id], "initial request sha256")


def _validate_protocol(document: dict[str, Any]) -> None:
    raw = _exact(document, _PROTOCOL_KEYS, "evaluation protocol")
    inputs = _input_ids(raw["input_ids"])
    budget = _exact(
        raw["budget"],
        {"a_generations", "max_generations_b_to_e"},
        "evaluation budget",
    )
    maximum = _count(budget["max_generations_b_to_e"], "generation budget", minimum=1)
    if (
        raw["schema_version"] != "specstyle.evaluation.five_arm_protocol.v1"
        or raw["evidence_class"] not in {"FORMAL", "TEST_ONLY"}
        or raw["arms"] != list(FORMAL_ARMS)
        or budget["a_generations"] != 1
        or raw["missingness_rule"]
        != "all_inputs_denominator_labels_required_for_artifacts"
    ):
        raise DomainError("invalid evaluation protocol")
    _text(raw["study_id"], "evaluation study id")
    _sha(raw["dataset_manifest_sha256"], "dataset manifest sha256")
    _validate_bindings(raw["bindings"])
    _validate_initial_requests(raw["generation_materials_sha256s"], inputs)
    _validate_initial_requests(raw["initial_request_sha256s"], inputs)
    _validate_schedules(raw["seed_schedules"], inputs, maximum)
    _validate_strategies(raw["strategies"])
    _validate_blind(raw["blind"])
    _validate_statistics(raw["statistics"], len(inputs))


def prepare_protocol(data: bytes, /) -> bytes:
    """Validate and preserve one canonical preregistration document."""
    try:
        document = _load_canonical(data)
        _validate_protocol(document)
    except (DomainError, KeyError, TypeError):
        raise DomainError("invalid evaluation protocol") from None
    return data


def load_protocol(data: bytes, /) -> dict[str, Any]:
    """Return a validated canonical protocol primitive."""
    prepare_protocol(data)
    return _load_canonical(data)


def load_sealed_protocol(data: bytes, /) -> dict[str, Any]:
    """Return a validated canonical seal primitive."""
    try:
        raw = _exact(_load_canonical(data), _SEALED_KEYS, "sealed protocol")
        if raw["schema_version"] != "specstyle.evaluation.sealed_protocol.v1":
            raise DomainError("invalid sealed evaluation protocol")
        for name in (
            "protocol_sha256",
            "production_approval_sha256",
            "production_context_sha256",
            "repo_sha",
            "threshold_profile_sha256",
        ):
            _sha(raw[name], name)
        if raw["trust_level"] != "LOCAL_PROCESS_ONLY":
            raise DomainError("invalid sealed evaluation protocol")
        _timestamp(raw["sealed_at"], "protocol seal time")
    except (DomainError, KeyError, TypeError):
        raise DomainError("invalid sealed evaluation protocol") from None
    return raw


def seal_protocol(
    protocol: bytes,
    production_context: object,
    /,
    *,
    sealed_at: str,
    repo_sha: str,
    production_context_sha256: str,
) -> bytes:
    """Seal a preregistration only behind the validated Production gate."""
    raw = load_protocol(protocol)
    require_validated_production_threshold(production_context)
    try:
        bindings = raw["bindings"]
        approval = production_context.l2_threshold_profile.production_binding.production_approval_sha256.value
        if (
            production_context.compiler_pin.sha256.value != bindings["compiler_sha256"]
            or production_context.l2_threshold_profile.pin.sha256.value
            != bindings["threshold_profile_sha256"]
            or production_context.l2_threshold_profile.production_binding.preprocessor_pin.sha256.value
            != bindings["preprocessor_sha256"]
            or _sha(production_context_sha256, "production context sha256")
            != bindings["production_context_sha256"]
        ):
            raise DomainError("PRODUCTION_THRESHOLD_NOT_VALIDATED")
        document = {
            "schema_version": "specstyle.evaluation.sealed_protocol.v1",
            "protocol_sha256": evidence_sha256(protocol).value,
            "production_approval_sha256": _sha(approval, "production approval sha256"),
            "production_context_sha256": bindings["production_context_sha256"],
            "repo_sha": _sha(repo_sha, "repository sha"),
            "sealed_at": _timestamp(sealed_at, "protocol seal time"),
            "threshold_profile_sha256": bindings["threshold_profile_sha256"],
            "trust_level": "LOCAL_PROCESS_ONLY",
        }
    except (AttributeError, DomainError, TypeError):
        raise DomainError("PRODUCTION_THRESHOLD_NOT_VALIDATED") from None
    sealed = canonical_json(document)
    load_sealed_protocol(sealed)
    return sealed
