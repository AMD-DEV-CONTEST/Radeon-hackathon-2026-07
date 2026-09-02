from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from shared_contracts import (
    H3AttemptQCEvidenceV1,
    H3QCDefectEvidenceV1,
    h3_contract_digest,
)


SEQUENCE_ID = UUID("10000000-0000-4000-8000-000000000001")
EVALUATION_ID = UUID("10000000-0000-4000-8000-000000000002")
EVIDENCE_PACK_ID = UUID("10000000-0000-4000-8000-000000000003")
PROJECT_ID = UUID("10000000-0000-4000-8000-000000000004")
WORKFLOW_RUN_ID = UUID("10000000-0000-4000-8000-000000000005")
ARTIFACT_ID = UUID("10000000-0000-4000-8000-000000000006")
OPERATION_RUN_ID = UUID("10000000-0000-4000-8000-000000000007")
OPERATION_ATTEMPT_ID = UUID("10000000-0000-4000-8000-000000000008")
POLICY_SNAPSHOT_ID = UUID("10000000-0000-4000-8000-000000000009")
PROMPT_REVISION_ID = UUID("10000000-0000-4000-8000-000000000010")
NOW = datetime(2026, 8, 6, tzinfo=timezone.utc)


def _payload(*, exception_codes: tuple[str, ...] = ()) -> dict[str, object]:
    defects = [
        {
            "defect_code": code,
            "severity": "MAJOR",
            "message": "检测到需要受限修复的音画问题。",
            "time_range_ms": [100, 900],
            "evidence_refs": ["asr.window.001", "visual.frame.012"],
            "recommended_repair_action": "仅修复命中的音画约束。",
        }
        for code in exception_codes
    ]
    identity: dict[str, object] = {
        "evaluation_id": str(EVALUATION_ID),
        "project_id": str(PROJECT_ID),
        "workflow_run_id": str(WORKFLOW_RUN_ID),
        "stage": "clip",
        "gate_key": "h3.sequence.001.attempt.0",
        "sequence_id": str(SEQUENCE_ID),
        "attempt_ordinal": 0,
        "artifact_id": str(ARTIFACT_ID),
        "artifact_digest": "a" * 64,
        "artifact_operation_run_id": str(OPERATION_RUN_ID),
        "artifact_operation_attempt_id": str(OPERATION_ATTEMPT_ID),
        "qc_policy_revision": "h3.audiovisual-qc.v1",
        "policy_snapshot_id": str(POLICY_SNAPSHOT_ID),
        "policy_snapshot_digest": "1" * 64,
        "evidence_pack_id": str(EVIDENCE_PACK_ID),
        "evidence_pack_digest": "b" * 64,
        "prompt_key": "h3.audiovisual-qc",
        "prompt_text": "按固定 H3 音画规则检查候选片段并返回结构化证据。",
        "prompt_revision_id": str(PROMPT_REVISION_ID),
        "prompt_digest": "2" * 64,
        "rubric_revision_id": "h3.audiovisual-qc-rubric.v1",
        "rubric_digest": "c" * 64,
        "evaluator_name": "zhipu/glm-4.6v+local",
        "evaluator_version": "h3-audiovisual-qc.v1",
        "evaluator_bundle_digest": "3" * 64,
        "implementation_digest": "d" * 64,
        "candidate": {
            "sequence_id": str(SEQUENCE_ID),
            "attempt_ordinal": 0,
            "media_integrity": 0.96,
            "identity_and_semantics": 0.92,
            "technical_quality": 0.9,
            "aesthetic_quality": 0.88,
            "exception_codes": list(exception_codes),
        },
        "defects": defects,
        "confidence": 0.94,
        "evaluated_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    identity["evidence_digest"] = h3_contract_digest(identity)
    return identity


@pytest.mark.parametrize("exception_codes", [(), ("H3_ASR_MISMATCH",)])
def test_h3_attempt_qc_evidence_is_canonical_and_frozen(
    exception_codes: tuple[str, ...],
) -> None:
    evidence = H3AttemptQCEvidenceV1.model_validate(
        _payload(exception_codes=exception_codes)
    )

    assert evidence.candidate.sequence_id == SEQUENCE_ID
    assert evidence.candidate.attempt_ordinal == 0
    assert evidence.project_id == PROJECT_ID
    assert evidence.artifact_id == ARTIFACT_ID
    assert evidence.policy_snapshot_id == POLICY_SNAPSHOT_ID
    assert evidence.prompt_revision_id == PROMPT_REVISION_ID
    assert tuple(item.defect_code for item in evidence.defects) == exception_codes
    assert H3AttemptQCEvidenceV1.model_validate_json(
        evidence.model_dump_json()
    ) == evidence
    with pytest.raises(ValidationError):
        evidence.confidence = 0.1  # type: ignore[misc]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update({"sequence_id": str(UUID(int=9))}),
        lambda value: value.update({"attempt_ordinal": 1}),
        lambda value: value["candidate"].update({"artifact_digest": "e" * 64}),
        lambda value: value["candidate"].update({"attempt_ordinal": 1}),
        lambda value: value["defects"][0].update(
            {"defect_code": "H3_DIFFERENT_FAILURE"}
        ),
        lambda value: value.update({"evidence_digest": "f" * 64}),
    ],
)
def test_h3_attempt_qc_evidence_rejects_mismatched_or_tampered_authority(
    mutate,
) -> None:
    payload = deepcopy(_payload(exception_codes=("H3_ASR_MISMATCH",)))
    mutate(payload)

    with pytest.raises(ValidationError):
        H3AttemptQCEvidenceV1.model_validate(payload)


def test_h3_attempt_qc_evidence_requires_exact_defect_set() -> None:
    missing = _payload(exception_codes=("H3_ASR_MISMATCH",))
    missing["defects"] = []
    missing["evidence_digest"] = h3_contract_digest(
        {key: value for key, value in missing.items() if key != "evidence_digest"}
    )
    with pytest.raises(ValidationError, match="defect"):
        H3AttemptQCEvidenceV1.model_validate(missing)

    unexpected = _payload()
    unexpected["defects"] = [
        H3QCDefectEvidenceV1(
            defect_code="H3_UNEXPECTED",
            severity="MAJOR",
            message="不应存在的失败项。",
            evidence_refs=("visual.frame.001",),
            recommended_repair_action="不应触发修复。",
        ).model_dump(mode="json")
    ]
    unexpected["evidence_digest"] = h3_contract_digest(
        {
            key: value
            for key, value in unexpected.items()
            if key != "evidence_digest"
        }
    )
    with pytest.raises(ValidationError, match="defect"):
        H3AttemptQCEvidenceV1.model_validate(unexpected)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("qc_policy_revision", "h3.audiovisual-qc.latest"),
        ("prompt_key", "h3.unpinned-qc"),
        ("rubric_revision_id", "h3.audiovisual-qc-rubric.latest"),
        ("evaluator_name", "untrusted/model"),
        ("evaluator_version", "latest"),
    ],
)
def test_h3_attempt_qc_evidence_pins_policy_prompt_rubric_and_evaluator(
    field: str,
    value: str,
) -> None:
    payload = _payload()
    payload[field] = value
    payload["evidence_digest"] = h3_contract_digest(
        {key: item for key, item in payload.items() if key != "evidence_digest"}
    )

    with pytest.raises(ValidationError):
        H3AttemptQCEvidenceV1.model_validate(payload)


def test_h3_attempt_qc_evidence_rejects_extra_fields() -> None:
    payload = _payload()
    payload["physical_path"] = "/workspace/private/candidate.mp4"
    with pytest.raises(ValidationError):
        H3AttemptQCEvidenceV1.model_validate(payload)


@pytest.mark.parametrize(
    "field",
    [
        "project_id",
        "workflow_run_id",
        "stage",
        "gate_key",
        "artifact_id",
        "artifact_operation_run_id",
        "artifact_operation_attempt_id",
        "policy_snapshot_id",
        "policy_snapshot_digest",
        "prompt_revision_id",
        "prompt_digest",
        "evaluator_bundle_digest",
    ],
)
def test_h3_attempt_qc_evidence_requires_durable_binding_authority(
    field: str,
) -> None:
    payload = _payload()
    payload.pop(field)
    payload["evidence_digest"] = h3_contract_digest(
        {key: item for key, item in payload.items() if key != "evidence_digest"}
    )

    with pytest.raises(ValidationError):
        H3AttemptQCEvidenceV1.model_validate(payload)


def test_h3_qc_defect_time_range_has_safe_h3_clip_upper_bound() -> None:
    payload = _payload(exception_codes=("H3_ASR_MISMATCH",))
    payload["defects"][0]["time_range_ms"] = [0, 16_001]
    payload["evidence_digest"] = h3_contract_digest(
        {key: item for key, item in payload.items() if key != "evidence_digest"}
    )

    with pytest.raises(ValidationError, match="16000|less than or equal"):
        H3AttemptQCEvidenceV1.model_validate(payload)
