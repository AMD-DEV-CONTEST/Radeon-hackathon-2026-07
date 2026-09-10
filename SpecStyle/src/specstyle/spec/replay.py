"""SPEC-005 same-input and new-batch replay assessment, contracts section 14.5.

Pure functions with no mutation, backend access, or network access.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError
from specstyle.spec.models import StyleSpec, StyleSpecV1, StyleSpecV11

ReplayStatus = Literal["EXACT", "COMPATIBLE", "REJECTED"]
ReplayMode = Literal["same_input", "new_batch"]


@dataclass(frozen=True, slots=True)
class ReplayAssessment:
    status: ReplayStatus
    mode: ReplayMode
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SameInputReplayRequest:
    source_spec: StyleSpec
    compiled_spec_hash: Sha256
    input_asset_hash: Sha256
    style_reference_hashes: tuple[Sha256, ...]
    model_pins_fingerprint: Sha256
    seed: int
    parameter_fingerprint: Sha256
    environment_fingerprint: Sha256
    candidate_compiled_spec_hash: Sha256
    candidate_input_asset_hash: Sha256
    candidate_style_reference_hashes: tuple[Sha256, ...]
    candidate_model_pins_fingerprint: Sha256
    candidate_seed: int
    candidate_parameter_fingerprint: Sha256
    candidate_environment_fingerprint: Sha256


@dataclass(frozen=True, slots=True)
class NewBatchReplayRequest:
    source_spec: StyleSpec
    compiled_graph_fingerprint: Sha256
    model_pins_fingerprint: Sha256
    seed_policy: Literal["per_asset_deterministic"]
    candidate_compiled_graph_fingerprint: Sha256
    candidate_model_pins_fingerprint: Sha256
    candidate_seed_policy: Literal["per_asset_deterministic"]
    candidate_input_asset_hashes: tuple[Sha256, ...]


def _is_sha(value: object) -> bool:
    return type(value) is Sha256 and type(value.value) is str


def _is_seed(value: object) -> bool:
    return type(value) is int and not isinstance(value, bool)


def _sha_tuple(value: object) -> bool:
    return type(value) is tuple and all(_is_sha(item) for item in value)


def _environment_policy(spec: StyleSpec) -> Literal["advisory", "strict"]:
    if type(spec) is StyleSpecV11:
        return spec.replay_contract.environment_policy
    if type(spec) is StyleSpecV1:
        return "advisory"
    raise DomainError("invalid replay request") from None


def assess_same_input_replay(req: SameInputReplayRequest, /) -> ReplayAssessment:
    if type(req) is not SameInputReplayRequest:
        raise DomainError("invalid replay request") from None
    if type(req.source_spec) not in (StyleSpecV1, StyleSpecV11):
        raise DomainError("invalid replay request") from None
    if not (
        _is_sha(req.compiled_spec_hash)
        and _is_sha(req.input_asset_hash)
        and _sha_tuple(req.style_reference_hashes)
        and _is_sha(req.model_pins_fingerprint)
        and _is_seed(req.seed)
        and _is_sha(req.parameter_fingerprint)
        and _is_sha(req.environment_fingerprint)
        and _is_sha(req.candidate_compiled_spec_hash)
        and _is_sha(req.candidate_input_asset_hash)
        and _sha_tuple(req.candidate_style_reference_hashes)
        and _is_sha(req.candidate_model_pins_fingerprint)
        and _is_seed(req.candidate_seed)
        and _is_sha(req.candidate_parameter_fingerprint)
        and _is_sha(req.candidate_environment_fingerprint)
    ):
        raise DomainError("invalid replay request") from None

    reasons: list[str] = []
    if req.compiled_spec_hash != req.candidate_compiled_spec_hash:
        reasons.append("compiled_spec_hash_mismatch")
    if req.input_asset_hash != req.candidate_input_asset_hash:
        reasons.append("input_asset_hash_mismatch")
    if req.style_reference_hashes != req.candidate_style_reference_hashes:
        reasons.append("style_reference_hashes_mismatch")
    if req.model_pins_fingerprint != req.candidate_model_pins_fingerprint:
        reasons.append("model_pins_mismatch")
    if req.seed != req.candidate_seed:
        reasons.append("seed_mismatch")
    if req.parameter_fingerprint != req.candidate_parameter_fingerprint:
        reasons.append("parameter_fingerprint_mismatch")

    env_equal = req.environment_fingerprint == req.candidate_environment_fingerprint
    policy = _environment_policy(req.source_spec)
    if not env_equal:
        if policy == "strict":
            reasons.append("environment_fingerprint_mismatch")
        else:
            # Record environment differences as advisory reasons, not rejection alone.
            pass

    if reasons:
        return ReplayAssessment("REJECTED", "same_input", tuple(reasons))
    if not env_equal and policy == "advisory":
        return ReplayAssessment(
            "COMPATIBLE", "same_input", ("environment_fingerprint_differs",)
        )
    return ReplayAssessment("EXACT", "same_input", ())


def assess_new_batch_replay(req: NewBatchReplayRequest, /) -> ReplayAssessment:
    if type(req) is not NewBatchReplayRequest:
        raise DomainError("invalid replay request") from None
    if type(req.source_spec) not in (StyleSpecV1, StyleSpecV11):
        raise DomainError("invalid replay request") from None
    if not (
        _is_sha(req.compiled_graph_fingerprint)
        and _is_sha(req.model_pins_fingerprint)
        and req.seed_policy == "per_asset_deterministic"
        and _is_sha(req.candidate_compiled_graph_fingerprint)
        and _is_sha(req.candidate_model_pins_fingerprint)
        and req.candidate_seed_policy == "per_asset_deterministic"
        and _sha_tuple(req.candidate_input_asset_hashes)
    ):
        raise DomainError("invalid replay request") from None

    reasons: list[str] = []
    if not req.candidate_input_asset_hashes:
        reasons.append("empty_candidate_inputs")
    if req.compiled_graph_fingerprint != req.candidate_compiled_graph_fingerprint:
        reasons.append("compiled_graph_mismatch")
    if req.model_pins_fingerprint != req.candidate_model_pins_fingerprint:
        reasons.append("model_pins_mismatch")
    if req.seed_policy != req.candidate_seed_policy:
        reasons.append("seed_policy_mismatch")

    if reasons:
        return ReplayAssessment("REJECTED", "new_batch", tuple(reasons))
    return ReplayAssessment("COMPATIBLE", "new_batch", ())
