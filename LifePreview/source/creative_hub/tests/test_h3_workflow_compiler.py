from __future__ import annotations

import json
import math
from uuid import UUID, uuid4

import pytest
from atomic_runtime import CapabilityRegistry
from shared_contracts import AtomicArtifactRef
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from creative_hub.dag_execution import DurableDagScheduler
from creative_hub.db import OrchestrationBase
from creative_hub.db.canonical import canonical_json_digest
from creative_hub.db.repositories import WorkflowRepository
from creative_hub.h3_atomic_runtime import build_plugin
from creative_hub.h3_workflow_compiler import (
    H3_BASE_INPUT_ROLE_ORDER,
    H3_HISTORICAL_INPUT_ROLE_ORDER,
    H3_SUBMISSION_COMPILER_REVISION,
    compile_h3_workflow_submission,
)
from creative_hub.qc_policy import EvaluatorPin, FactoryQCPolicyPayload
from creative_hub.workflow_catalog import h3_shidu_workflow_definition
from creative_hub.workflow_catalog import WorkflowMaterializer
from drama.atomic_plugin import build_plugin as build_drama_plugin


PROJECT_ID = UUID("10000000-0000-4000-8000-000000000001")


def _ref(
    role: str,
    *,
    mime: str = "application/json",
    project_id: UUID = PROJECT_ID,
    digest: str | None = None,
    artifact_id: UUID | None = None,
) -> AtomicArtifactRef:
    return AtomicArtifactRef(
        artifact_id=artifact_id or uuid4(),
        project_id=project_id,
        content_digest=digest or (f"{len(role) % 10}" * 64),
        mime_type=mime,
        byte_size=4_096,
        logical_role=role,
    )


def _input_refs(
    mode: str = "historical_image_grounded",
) -> tuple[AtomicArtifactRef, ...]:
    base = (
        _ref("h3.project.authority"),
        _ref("h3.trial-script.authority"),
        _ref("h3.evidence-pack.authority"),
        _ref("h3.visual-identity-resolution.authority"),
    )
    if mode == "script_synthesized":
        return base
    return (*base, _ref("character.source.image", mime="image/png"))


def _policy_authority() -> dict[str, object]:
    policy = FactoryQCPolicyPayload(stages={})
    final = policy.stages["final"].model_copy(
        update={
            "evaluator_pin": EvaluatorPin(
                prompt_revision_id=UUID(
                    "20000000-0000-4000-8000-000000000001"
                ),
                prompt_digest="1" * 64,
                rubric_digest="2" * 64,
                operation_spec_digest="3" * 64,
                implementation_digest="4" * 64,
            )
        }
    )
    policy = policy.model_copy(
        update={"stages": {**policy.stages, "final": final}}
    )
    authority_revision_id = UUID(
        "30000000-0000-4000-8000-000000000001"
    )
    payload: dict[str, object] = {
        "schema_version": "factory.shidu-h3-policy-authority.v1",
        "authority_revision_id": str(authority_revision_id),
        "factory_qc_policy": policy.model_dump(mode="json"),
    }
    payload["authority_digest"] = canonical_json_digest(payload)
    payload["authority_revision_id"] = authority_revision_id
    return payload


def _compile(**overrides: object):
    arguments: dict[str, object] = {
        "project_id": PROJECT_ID,
        "input_artifact_refs": _input_refs(),
        "requested_sequence_duration_seconds": 3.0,
        "sequence_count": 1,
        "visual_identity_mode": "historical_image_grounded",
        "visual_identity_resolution_id": UUID(
            "40000000-0000-4000-8000-000000000001"
        ),
        "visual_identity_resolution_digest": "5" * 64,
        "policy_authority": _policy_authority(),
    }
    arguments.update(overrides)
    return compile_h3_workflow_submission(**arguments)


def test_compiler_returns_materializer_ready_h3_authorities() -> None:
    compiled = _compile()

    assert compiled.definition == h3_shidu_workflow_definition(
        sequence_count=1
    )
    assert compiled.definition.workflow_key == "factory.shidu-h3.v1"
    assert compiled.definition_digest == canonical_json_digest(
        compiled.definition.as_payload()
    )
    assert tuple(ref.logical_role for ref in compiled.input_artifact_refs) == (
        H3_HISTORICAL_INPUT_ROLE_ORDER
    )
    assert compiled.input_payload["input_artifact_refs"] == [
        ref.model_dump(mode="json") for ref in compiled.input_artifact_refs
    ]
    assert compiled.input_payload["structured_inputs"] == {
        "submission_schema_version": "factory.shidu-h3-submission.v1",
        "compiler_revision": H3_SUBMISSION_COMPILER_REVISION,
        "workflow_key": "factory.shidu-h3.v1",
        "requested_sequence_duration_seconds": 3.0,
        "sequence_frame_count": 73,
        "sequence_duration_seconds": 73 / 24,
        "sequence_count": 1,
        "visual_identity_mode": "historical_image_grounded",
        "visual_identity_resolution_id": (
            "40000000-0000-4000-8000-000000000001"
        ),
        "visual_identity_resolution_digest": "5" * 64,
        "native_audio": True,
        "subtitles": False,
        "input_authority_digest": compiled.input_authority_digest,
        "policy_authority_digest": _policy_authority()["authority_digest"],
        "input_role_order": list(H3_HISTORICAL_INPUT_ROLE_ORDER),
        "input_artifact_refs": [
            ref.model_dump(mode="json")
            for ref in compiled.input_artifact_refs
        ],
    }
    assert compiled.input_payload["compiled_definition_digest"] == (
        compiled.definition_digest
    )
    assert compiled.input_payload["compiled_run_identity"] == (
        compiled.run_identity
    )


def test_policy_snapshot_reuses_final_gate_format_and_forbids_legacy_audio() -> None:
    compiled = _compile()
    snapshot = compiled.policy_snapshot

    assert snapshot["schema_version"] == "factory.shidu-h3-policy.v1"
    assert snapshot["compiler_revision"] == H3_SUBMISSION_COMPILER_REVISION
    assert snapshot["input_authority"] == {
        "digest": compiled.input_authority_digest,
        "role_order": list(H3_HISTORICAL_INPUT_ROLE_ORDER),
        "artifact_refs": [
            ref.model_dump(mode="json")
            for ref in compiled.input_artifact_refs
        ],
    }
    assert snapshot["sequence_authority"] == {
        "requested_duration_seconds": 3.0,
        "frame_count": 73,
        "duration_seconds": 73 / 24,
        "sequence_count": 1,
        "native_audio": True,
        "subtitles": False,
        "generation_mode": "ref2va",
        "model_family": "minimax-h3",
        "model_revision": "h3-amd-local-v1",
        "visual_identity_mode": "historical_image_grounded",
        "visual_identity_resolution_id": (
            "40000000-0000-4000-8000-000000000001"
        ),
        "visual_identity_resolution_digest": "5" * 64,
    }
    assert snapshot["selection_policy"] == {
        "revision": "h3.selection.v1",
        "max_generation_attempts": 2,
        "repair_budget": 1,
        "deliver_best_with_qc_exception": True,
    }
    assert len(snapshot["gate_policies"]) == 1
    final = snapshot["gate_policies"][0]
    assert final["gate_key"] == "final-gate"
    assert final["stage"] == "final"
    assert final["review_mode"] == "OFF"
    assert final["exhaustion_policy"] == "BLOCK"
    assert final["machine_qc_required"] is True
    assert final["evaluator"]["strict_frozen"] is True
    assert snapshot["delivery_requirements"] == {
        "machine_qc": True,
        "human_approval": False,
        "exact_artifact_lineage": True,
        "audio_source": "h3_native",
        "subtitles": False,
    }
    rendered = json.dumps(snapshot, sort_keys=True).casefold()
    assert "voice" not in rendered
    assert "tts" not in rendered
    assert "subtitle.generate" not in rendered
    assert "subtitle_authority" not in rendered


def test_script_synthesized_compilation_requires_resolution_without_source() -> None:
    compiled = _compile(
        visual_identity_mode="script_synthesized",
        input_artifact_refs=_input_refs("script_synthesized"),
    )

    assert tuple(ref.logical_role for ref in compiled.input_artifact_refs) == (
        H3_BASE_INPUT_ROLE_ORDER
    )
    assert compiled.input_payload["structured_inputs"][
        "visual_identity_mode"
    ] == "script_synthesized"
    assert "character.source.image" not in {
        ref.logical_role for ref in compiled.input_artifact_refs
    }


def test_today_three_second_target_uses_legal_h3_frame_grid() -> None:
    compiled = _compile(requested_sequence_duration_seconds=3.0)
    structured = compiled.input_payload["structured_inputs"]
    sequence = compiled.policy_snapshot["sequence_authority"]

    assert structured["sequence_frame_count"] == 73
    assert structured["sequence_frame_count"] % 17 == 5
    assert structured["sequence_duration_seconds"] == pytest.approx(73 / 24)
    assert sequence["frame_count"] == 73
    assert sequence["duration_seconds"] == pytest.approx(73 / 24)
    assert sequence["native_audio"] is True
    assert sequence["subtitles"] is False


def test_visual_identity_mode_rejects_source_presence_or_absence_mismatch() -> None:
    with pytest.raises(ValueError, match="source|role|mode"):
        _compile(
            visual_identity_mode="historical_image_grounded",
            input_artifact_refs=_input_refs("script_synthesized"),
        )
    with pytest.raises(ValueError, match="source|role|mode"):
        _compile(
            visual_identity_mode="script_synthesized",
            input_artifact_refs=_input_refs("historical_image_grounded"),
        )
    with pytest.raises((TypeError, ValueError), match="visual identity mode"):
        _compile(visual_identity_mode="searched_historical")


def test_visual_resolution_authority_cannot_be_replaced_by_source_image() -> None:
    refs = _input_refs()
    source_only = (*refs[:3], refs[-1])

    with pytest.raises(
        ValueError,
        match="resolution|role|visual identity",
    ):
        _compile(input_artifact_refs=source_only)
    with pytest.raises(ValueError, match="visual identity|role"):
        _compile(
            visual_identity_mode="script_synthesized",
            input_artifact_refs=refs[:3],
        )


def test_visual_resolution_identity_and_digest_are_strict_and_bound() -> None:
    baseline = _compile()
    changed_id = _compile(visual_identity_resolution_id=uuid4())
    changed_digest = _compile(visual_identity_resolution_digest="6" * 64)
    synthesized = _compile(
        visual_identity_mode="script_synthesized",
        input_artifact_refs=_input_refs("script_synthesized"),
    )

    assert baseline.run_identity != changed_id.run_identity
    assert baseline.run_identity != changed_digest.run_identity
    assert baseline.run_identity != synthesized.run_identity
    with pytest.raises((TypeError, ValueError), match="resolution"):
        _compile(
            visual_identity_resolution_id=(
                "40000000-0000-4000-8000-000000000001"
            )
        )
    with pytest.raises((TypeError, ValueError), match="resolution.*digest"):
        _compile(visual_identity_resolution_digest="bad")


def test_sequence_count_is_bound_into_definition_payload_policy_and_identity() -> None:
    one = _compile(sequence_count=1)
    three = _compile(sequence_count=3)

    assert one.run_identity != three.run_identity
    assert three.input_payload["structured_inputs"]["sequence_count"] == 3
    assert three.policy_snapshot["sequence_authority"]["sequence_count"] == 3
    assert [
        node.key
        for node in three.definition.nodes
        if node.op_type == "h3.sequence.execute"
    ] == [
        "sequence.001.execute",
        "sequence.002.execute",
        "sequence.003.execute",
    ]


def test_compiler_output_materializes_without_payload_translation() -> None:
    compiled = _compile()
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        execution_options={"schema_translate_map": {"orchestration": None}},
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    OrchestrationBase.metadata.create_all(engine)
    registry = CapabilityRegistry()
    registry.register_plugins_and_freeze((build_drama_plugin(), build_plugin()))
    try:
        with Session(engine, expire_on_commit=False) as session, session.begin():
            WorkflowRepository(session).create_project(
                project_key="h3-compiler-materialize",
                title="H3 compiler materialization fixture",
                config={},
                project_id=PROJECT_ID,
            )
            materialized = WorkflowMaterializer(
                session=session,
                scheduler=DurableDagScheduler(session, budget_guard=None),
                capability_registry=registry,
            ).materialize(
                project_id=PROJECT_ID,
                definition=compiled.definition,
                command_idempotency_key="h3-compiler-materialize:1",
                input_payload=compiled.input_payload,
                policy_snapshot=compiled.policy_snapshot,
                created_by_actor="test.owner",
            )

            assert materialized.run.input_digest == canonical_json_digest(
                compiled.input_payload
            )
            assert materialized.run.policy_digest == compiled.policy_digest
            assert tuple(materialized.operations) == tuple(
                node.key for node in compiled.definition.nodes
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "duration",
    [True, "3", 2.999, 15.001, math.nan, math.inf, -math.inf],
)
def test_compiler_rejects_non_strict_or_out_of_range_sequence_duration(
    duration: object,
) -> None:
    with pytest.raises((TypeError, ValueError), match="duration"):
        _compile(requested_sequence_duration_seconds=duration)


@pytest.mark.parametrize("sequence_count", [True, "1", 0, 13])
def test_compiler_rejects_non_strict_or_out_of_range_sequence_count(
    sequence_count: object,
) -> None:
    with pytest.raises((TypeError, ValueError), match="sequence_count"):
        _compile(sequence_count=sequence_count)


def test_compiler_rejects_wrong_role_order_and_non_unique_source() -> None:
    refs = _input_refs()
    with pytest.raises(ValueError, match="order|role"):
        _compile(input_artifact_refs=(refs[1], refs[0], *refs[2:]))
    with pytest.raises(ValueError, match="role|source"):
        _compile(
            input_artifact_refs=(
                *refs[:3],
                refs[3].model_copy(
                    update={"logical_role": "h3.reference-source"}
                ),
                refs[4],
            )
        )
    with pytest.raises(ValueError, match="identity|duplicate"):
        _compile(
            input_artifact_refs=(
                refs[0],
                refs[1].model_copy(update={"artifact_id": refs[0].artifact_id}),
                *refs[2:],
            )
        )


def test_compiler_rejects_foreign_unfrozen_or_wrong_mime_artifacts() -> None:
    refs = _input_refs()
    with pytest.raises(ValueError, match="project"):
        _compile(
            input_artifact_refs=(
                refs[0].model_copy(update={"project_id": uuid4()}),
                *refs[1:],
            )
        )
    with pytest.raises((TypeError, ValueError), match="ArtifactRef|reference"):
        _compile(
            input_artifact_refs=(
                refs[0].model_dump(mode="json"),
                *refs[1:],
            )
        )
    with pytest.raises(ValueError, match="MIME|mime"):
        _compile(
            input_artifact_refs=(
                refs[0].model_copy(update={"mime_type": "image/png"}),
                *refs[1:],
            )
        )
    with pytest.raises(ValueError, match="ArtifactRef|reference"):
        _compile(
            input_artifact_refs=(
                refs[0].model_copy(update={"content_digest": "bad"}),
                *refs[1:],
            )
        )


def test_policy_authority_digest_and_schema_fail_closed() -> None:
    stale = _policy_authority()
    stale["authority_revision_id"] = uuid4()
    with pytest.raises(ValueError, match="policy.*authority"):
        _compile(policy_authority=stale)

    extra = _policy_authority()
    extra["voice_authority"] = {"provider": "legacy-tts"}
    with pytest.raises(ValueError, match="policy|extra|authority"):
        _compile(policy_authority=extra)


def test_policy_authority_requires_frozen_final_evaluator() -> None:
    authority = _policy_authority()
    policy = FactoryQCPolicyPayload(stages={})
    authority["factory_qc_policy"] = policy.model_dump(mode="json")
    identity = {
        key: value
        for key, value in authority.items()
        if key != "authority_digest"
    }
    identity["authority_revision_id"] = str(
        identity["authority_revision_id"]
    )
    authority["authority_digest"] = canonical_json_digest(identity)

    with pytest.raises(ValueError, match="policy authority"):
        _compile(policy_authority=authority)


def test_tampered_artifact_or_duration_changes_compilation_identity() -> None:
    baseline = _compile()
    refs = _input_refs()
    changed_ref = refs[0].model_copy(update={"content_digest": "9" * 64})
    changed_input = _compile(input_artifact_refs=(changed_ref, *refs[1:]))
    changed_duration = _compile(requested_sequence_duration_seconds=6.0)

    assert baseline.input_authority_digest != changed_input.input_authority_digest
    assert baseline.run_identity != changed_input.run_identity
    assert baseline.run_identity != changed_duration.run_identity


def test_compiler_signature_rejects_voice_tts_and_subtitle_authorities() -> None:
    with pytest.raises(TypeError):
        _compile(voice_authority={"provider": "legacy"})
    with pytest.raises(TypeError):
        _compile(tts_policy={"enabled": True})
    with pytest.raises(TypeError):
        _compile(subtitle_authority={"enabled": True})
