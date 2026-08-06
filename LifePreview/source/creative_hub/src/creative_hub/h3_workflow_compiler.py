"""Strict compiler for durable Shidu H3 workflow submissions.

This module does not load mutable database state or perform artifact I/O.  It
accepts only already-frozen artifact references and a digest-bound QC policy
authority, then produces the complete immutable payload required by
``WorkflowMaterializer.materialize``.
"""

from __future__ import annotations

from dataclasses import dataclass
import hmac
import math
from collections.abc import Mapping
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from shared_contracts import AtomicArtifactRef

from .db.canonical import canonical_json_digest
from .qc_policy import FactoryQCPolicyPayload, compiled_gate_policy
from .workflow_catalog import (
    WorkflowDefinition,
    h3_shidu_workflow_definition,
)


H3_SUBMISSION_COMPILER_REVISION = "shidu-h3-workflow-compiler.v1"
H3_BASE_INPUT_ROLE_ORDER = (
    "h3.project.authority",
    "h3.trial-script.authority",
    "h3.evidence-pack.authority",
    "h3.visual-identity-resolution.authority",
)
H3_HISTORICAL_INPUT_ROLE_ORDER = (
    *H3_BASE_INPUT_ROLE_ORDER,
    "character.source.image",
)

_H3_WORKFLOW_KEY = "factory.shidu-h3.v1"
_SUBMISSION_SCHEMA_VERSION = "factory.shidu-h3-submission.v1"
_POLICY_SCHEMA_VERSION = "factory.shidu-h3-policy.v1"
_POLICY_AUTHORITY_SCHEMA_VERSION = (
    "factory.shidu-h3-policy-authority.v1"
)
_JSON_ROLES = frozenset(H3_BASE_INPUT_ROLE_ORDER)
_SOURCE_ROLE = H3_HISTORICAL_INPUT_ROLE_ORDER[-1]
_SOURCE_MIME_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp"}
)
_FORBIDDEN_OPERATION_TYPES = frozenset(
    {
        "speech.synthesize",
        "subtitle.generate",
        "audio.mix",
    }
)


class H3SubmissionPolicyAuthority(BaseModel):
    """Persisted, digest-bound authority from which final QC is compiled."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[
        "factory.shidu-h3-policy-authority.v1"
    ] = _POLICY_AUTHORITY_SCHEMA_VERSION
    authority_revision_id: UUID
    factory_qc_policy: FactoryQCPolicyPayload
    authority_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def digest_is_current(self) -> H3SubmissionPolicyAuthority:
        identity = self.model_dump(
            mode="json",
            exclude={"authority_digest"},
        )
        actual = canonical_json_digest(identity)
        if not hmac.compare_digest(actual, self.authority_digest):
            raise ValueError("H3 policy authority digest mismatch")
        if self.factory_qc_policy.stages["final"].evaluator_pin is None:
            raise ValueError("H3 final evaluator authority must be frozen")
        return self


@dataclass(frozen=True, slots=True)
class CompiledH3WorkflowSubmission:
    """Canonical definition, inputs, policy, and identity for materialization."""

    definition: WorkflowDefinition
    definition_digest: str
    input_artifact_refs: tuple[AtomicArtifactRef, ...]
    input_authority_digest: str
    input_payload: dict[str, Any]
    policy_snapshot: dict[str, Any]
    policy_digest: str
    run_identity: str


def _strict_project_id(value: object) -> UUID:
    if not isinstance(value, UUID):
        raise TypeError("project_id must be a UUID")
    return value


def _strict_duration(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("requested sequence duration must be numeric")
    duration = float(value)
    if not math.isfinite(duration) or not 3.0 <= duration <= 15.0:
        raise ValueError(
            "requested sequence duration must be from 3 to 15 seconds"
        )
    return duration


def _h3_frame_authority(requested_duration_seconds: float) -> tuple[int, float]:
    required_frames = math.ceil(requested_duration_seconds * 24 - 1e-12)
    frame_count = required_frames + ((5 - required_frames) % 17)
    return frame_count, frame_count / 24


def _strict_sequence_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("sequence_count must be an integer")
    if not 1 <= value <= 12:
        raise ValueError("sequence_count must be from 1 to 12")
    return value


def _strict_refs(
    *,
    project_id: UUID,
    visual_identity_mode: str,
    value: object,
) -> tuple[AtomicArtifactRef, ...]:
    if not isinstance(value, tuple):
        raise TypeError("input ArtifactRef references must be a tuple")
    expected_roles = (
        H3_HISTORICAL_INPUT_ROLE_ORDER
        if visual_identity_mode == "historical_image_grounded"
        else H3_BASE_INPUT_ROLE_ORDER
    )
    if len(value) != len(expected_roles):
        raise ValueError(
            "input ArtifactRef references do not match visual identity mode"
        )

    refs: list[AtomicArtifactRef] = []
    for raw in value:
        if not isinstance(raw, AtomicArtifactRef):
            raise TypeError("input ArtifactRef reference type is invalid")
        try:
            # ``model_copy`` does not validate updates.  Round-trip every
            # object so callers cannot smuggle a stale or malformed instance.
            ref = AtomicArtifactRef.model_validate(
                raw.model_dump(mode="python"),
                strict=True,
            )
        except ValueError as exc:
            raise ValueError("input ArtifactRef reference is invalid") from exc
        refs.append(ref)

    roles = tuple(ref.logical_role for ref in refs)
    if roles != expected_roles:
        raise ValueError(
            "input ArtifactRef role order must match the H3 canonical order"
        )
    if any(ref.project_id != project_id for ref in refs):
        raise ValueError("input ArtifactRef project identity mismatch")
    artifact_ids = tuple(ref.artifact_id for ref in refs)
    if len(artifact_ids) != len(set(artifact_ids)):
        raise ValueError("input ArtifactRef artifact identity is duplicated")
    if any(
        ref.mime_type != "application/json"
        for ref in refs
        if ref.logical_role in _JSON_ROLES
    ):
        raise ValueError("H3 JSON authority ArtifactRef MIME type is invalid")
    if visual_identity_mode == "historical_image_grounded":
        source = refs[-1]
        if (
            source.logical_role != _SOURCE_ROLE
            or source.mime_type not in _SOURCE_MIME_TYPES
        ):
            raise ValueError(
                "H3 reference source ArtifactRef MIME type is invalid"
            )
    return tuple(refs)


def _strict_visual_identity_mode(value: object) -> str:
    if value not in {
        "historical_image_grounded",
        "script_synthesized",
    }:
        raise ValueError("visual identity mode is invalid")
    return str(value)


def _strict_resolution_id(value: object) -> UUID:
    if not isinstance(value, UUID):
        raise TypeError("visual identity resolution id must be a UUID")
    return value


def _strict_resolution_digest(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(
            "visual identity resolution digest must be a sha256 digest"
        )
    return value


def _strict_policy_authority(
    value: object,
) -> H3SubmissionPolicyAuthority:
    if isinstance(value, H3SubmissionPolicyAuthority):
        raw: object = value.model_dump(mode="python")
    elif isinstance(value, Mapping):
        raw = dict(value)
    else:
        raise TypeError("H3 policy authority must be a frozen object")
    try:
        return H3SubmissionPolicyAuthority.model_validate(raw)
    except ValueError as exc:
        raise ValueError("H3 policy authority is invalid") from exc


def _validate_definition(
    definition: WorkflowDefinition,
    *,
    sequence_count: int,
) -> None:
    if definition.workflow_key != _H3_WORKFLOW_KEY:
        raise ValueError("H3 workflow definition key is invalid")
    if {node.op_type for node in definition.nodes} & _FORBIDDEN_OPERATION_TYPES:
        raise ValueError("H3 workflow contains legacy audio or subtitle authority")

    execute = tuple(
        node
        for node in definition.nodes
        if node.op_type == "h3.sequence.execute"
    )
    if len(execute) != sequence_count:
        raise ValueError("H3 workflow sequence_count binding is invalid")
    for ordinal, node in enumerate(execute, start=1):
        inputs = dict(node.structured_inputs)
        if (
            node.key != f"sequence.{ordinal:03d}.execute"
            or inputs.get("sequence_ordinal") != ordinal
            or inputs.get("native_audio") is not True
            or inputs.get("subtitles") is not False
            or inputs.get("mode") != "ref2va"
            or inputs.get("model_family") != "minimax-h3"
            or inputs.get("model_revision") != "h3-amd-local-v1"
            or inputs.get("max_generation_attempts") != 2
            or inputs.get("repair_budget") != 1
        ):
            raise ValueError("H3 workflow sequence authority is invalid")

    by_key = {node.key: node for node in definition.nodes}
    assemble = by_key.get("assemble")
    if assemble is None or dict(assemble.structured_inputs) != {
        "video_codec": "h264",
        "audio_codec": "aac",
        "audio_source": "h3_native",
        "subtitles": False,
    }:
        raise ValueError("H3 assembly media authority is invalid")
    final_gate = by_key.get("final-gate")
    delivery = by_key.get("delivery")
    if (
        final_gate is None
        or final_gate.op_type != "qc.gate.final"
        or final_gate.depends_on != ("assemble",)
        or delivery is None
        or delivery.op_type != "delivery.publish"
        or delivery.depends_on != ("final-gate",)
    ):
        raise ValueError("H3 final QC and delivery barriers are invalid")


def compile_h3_workflow_submission(
    *,
    project_id: UUID,
    input_artifact_refs: tuple[AtomicArtifactRef, ...],
    requested_sequence_duration_seconds: float,
    sequence_count: int,
    visual_identity_mode: Literal[
        "historical_image_grounded",
        "script_synthesized",
    ],
    visual_identity_resolution_id: UUID,
    visual_identity_resolution_digest: str,
    policy_authority: H3SubmissionPolicyAuthority | Mapping[str, Any],
) -> CompiledH3WorkflowSubmission:
    """Compile one immutable H3 workflow submission without legacy audio.

    ``requested_sequence_duration_seconds`` is the duration authority for each
    serial H3 sequence.  A one-sequence submission is today's approximately
    three-second vertical slice after upward 17n+5/24fps grid snapping; larger
    ``sequence_count`` values reuse the same strict
    per-sequence bound for later serial assembly.
    """

    project = _strict_project_id(project_id)
    duration = _strict_duration(requested_sequence_duration_seconds)
    frame_count, rendered_duration = _h3_frame_authority(duration)
    count = _strict_sequence_count(sequence_count)
    identity_mode = _strict_visual_identity_mode(visual_identity_mode)
    resolution_id = _strict_resolution_id(visual_identity_resolution_id)
    resolution_digest = _strict_resolution_digest(
        visual_identity_resolution_digest
    )
    refs = _strict_refs(
        project_id=project,
        visual_identity_mode=identity_mode,
        value=input_artifact_refs,
    )
    authority = _strict_policy_authority(policy_authority)

    definition = h3_shidu_workflow_definition(sequence_count=count)
    _validate_definition(definition, sequence_count=count)
    definition_digest = canonical_json_digest(definition.as_payload())

    ref_payloads = [ref.model_dump(mode="json") for ref in refs]
    input_authority_digest = canonical_json_digest(
        {
            "schema_version": "factory.shidu-h3-input-authority.v1",
            "project_id": str(project),
            "role_order": [ref.logical_role for ref in refs],
            "visual_identity_mode": identity_mode,
            "visual_identity_resolution_id": str(resolution_id),
            "visual_identity_resolution_digest": resolution_digest,
            "artifact_refs": ref_payloads,
        }
    )

    final_policy = authority.factory_qc_policy.stages["final"].model_copy(
        update={"review_mode": "OFF", "exhaustion_policy": "BLOCK"}
    )
    final_gate_policy = compiled_gate_policy(
        stage="final",
        gate_key="final-gate",
        policy=final_policy,
        review_phase="machine",
    )
    sequence_authority = {
        "requested_duration_seconds": duration,
        "frame_count": frame_count,
        "duration_seconds": rendered_duration,
        "sequence_count": count,
        "native_audio": True,
        "subtitles": False,
        "generation_mode": "ref2va",
        "model_family": "minimax-h3",
        "model_revision": "h3-amd-local-v1",
        "visual_identity_mode": identity_mode,
        "visual_identity_resolution_id": str(resolution_id),
        "visual_identity_resolution_digest": resolution_digest,
    }
    policy_snapshot: dict[str, Any] = {
        "schema_version": _POLICY_SCHEMA_VERSION,
        "compiler_revision": H3_SUBMISSION_COMPILER_REVISION,
        "workflow_key": _H3_WORKFLOW_KEY,
        "definition_digest": definition_digest,
        "input_authority_digest": input_authority_digest,
        "input_authority": {
            "digest": input_authority_digest,
            "role_order": [ref.logical_role for ref in refs],
            "artifact_refs": ref_payloads,
        },
        "policy_authority": authority.model_dump(mode="json"),
        "sequence_authority": sequence_authority,
        "selection_policy": {
            "revision": "h3.selection.v1",
            "max_generation_attempts": 2,
            "repair_budget": 1,
            "deliver_best_with_qc_exception": True,
        },
        "gate_policies": [final_gate_policy],
        "delivery_requirements": {
            "machine_qc": True,
            "human_approval": False,
            "exact_artifact_lineage": True,
            "audio_source": "h3_native",
            "subtitles": False,
        },
    }
    policy_digest = canonical_json_digest(policy_snapshot)
    run_identity = canonical_json_digest(
        {
            "compiler_revision": H3_SUBMISSION_COMPILER_REVISION,
            "project_id": str(project),
            "workflow_key": _H3_WORKFLOW_KEY,
            "definition_digest": definition_digest,
            "input_authority_digest": input_authority_digest,
            "policy_authority_digest": authority.authority_digest,
            "policy_digest": policy_digest,
            "requested_sequence_duration_seconds": duration,
            "sequence_frame_count": frame_count,
            "sequence_duration_seconds": rendered_duration,
            "sequence_count": count,
            "visual_identity_mode": identity_mode,
            "visual_identity_resolution_id": str(resolution_id),
            "visual_identity_resolution_digest": resolution_digest,
        }
    )
    structured_inputs = {
        "submission_schema_version": _SUBMISSION_SCHEMA_VERSION,
        "compiler_revision": H3_SUBMISSION_COMPILER_REVISION,
        "workflow_key": _H3_WORKFLOW_KEY,
        "requested_sequence_duration_seconds": duration,
        "sequence_frame_count": frame_count,
        "sequence_duration_seconds": rendered_duration,
        "sequence_count": count,
        "visual_identity_mode": identity_mode,
        "visual_identity_resolution_id": str(resolution_id),
        "visual_identity_resolution_digest": resolution_digest,
        "native_audio": True,
        "subtitles": False,
        "input_authority_digest": input_authority_digest,
        "policy_authority_digest": authority.authority_digest,
        "input_role_order": [ref.logical_role for ref in refs],
        "input_artifact_refs": ref_payloads,
    }
    input_payload: dict[str, Any] = {
        "schema_version": _SUBMISSION_SCHEMA_VERSION,
        "input_artifact_refs": ref_payloads,
        "structured_inputs": structured_inputs,
        "compiled_definition_digest": definition_digest,
        "compiled_run_identity": run_identity,
    }
    return CompiledH3WorkflowSubmission(
        definition=definition,
        definition_digest=definition_digest,
        input_artifact_refs=refs,
        input_authority_digest=input_authority_digest,
        input_payload=input_payload,
        policy_snapshot=policy_snapshot,
        policy_digest=policy_digest,
        run_identity=run_identity,
    )


__all__ = (
    "CompiledH3WorkflowSubmission",
    "H3_BASE_INPUT_ROLE_ORDER",
    "H3_HISTORICAL_INPUT_ROLE_ORDER",
    "H3_SUBMISSION_COMPILER_REVISION",
    "H3SubmissionPolicyAuthority",
    "compile_h3_workflow_submission",
)
