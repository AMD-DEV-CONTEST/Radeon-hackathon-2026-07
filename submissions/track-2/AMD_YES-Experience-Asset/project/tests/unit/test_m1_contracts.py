from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.experience_asset.domain.enums import SourceKind
from app.experience_asset.domain.m1 import (
    M1BriefEditRequestV1,
    M1IngestRequestV1,
    M1QuestionActionV1,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CHECKPOINT_PATH = (
    REPOSITORY_ROOT
    / "contracts"
    / "checkpoints"
    / "e2-m1-contract-fixtures-v1.json"
)


def test_contract_checkpoint_references_frozen_files_and_public_fixtures() -> None:
    checkpoint = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))

    assert checkpoint["status"] == "READY_FOR_QUALITY_OWNER_CONFIRMATION"
    assert checkpoint["scope"]["milestone"] == "M1"
    assert checkpoint["scope"]["retrieval_phase"] == "CURRENT_SOURCE"
    assert checkpoint["migrations"]["required"] is False
    assert len(checkpoint["api"]) == 8

    for relative_path in checkpoint["canonical_schemas"]:
        assert (REPOSITORY_ROOT / relative_path).is_file(), relative_path

    fixture_ids = {fixture["id"] for fixture in checkpoint["fixtures"]}
    assert fixture_ids == {
        "chair_public_complete",
        "chair_incomplete",
        "chair_conflicting",
        "chair_correction",
        "chair_resume",
    }
    for fixture_id in fixture_ids:
        assert (REPOSITORY_ROOT / "qa" / "fixtures" / f"{fixture_id}.md").is_file()
        assert (
            REPOSITORY_ROOT / "qa" / "expected" / f"{fixture_id}.expected.json"
        ).is_file()

    assert {
        "Canonical state",
        "Persistence and resume",
        "Evidence discipline",
        "Retrieval phase integrity",
        "Runtime permission",
        "Local inference",
        "Failure behavior",
        "Observability",
    } == set(checkpoint["quality_mapping"]["l2"])


def test_text_file_ingest_requires_txt_file_name() -> None:
    with pytest.raises(ValidationError, match=r"original \.txt file name"):
        M1IngestRequestV1(
            source_kind=SourceKind.TXT_FILE,
            text="A public test experience.",
            display_label="fixture",
            original_file_name="fixture.md",
        )


def test_markdown_file_ingest_accepts_md_file_name() -> None:
    request = M1IngestRequestV1(
        source_kind=SourceKind.MD_FILE,
        text="# A public test experience",
        display_label="fixture",
        original_file_name="fixture.md",
    )
    assert request.source_kind is SourceKind.MD_FILE


def test_adapted_fixture_requires_provenance() -> None:
    with pytest.raises(ValidationError, match="adapted provenance"):
        M1IngestRequestV1(
            source_kind=SourceKind.ADAPTED_PUBLIC_FIXTURE,
            text="An anonymized and paraphrased test case.",
            display_label="adapted fixture",
        )


def test_edit_requires_a_changed_field() -> None:
    with pytest.raises(ValidationError, match="at least one changed field"):
        M1BriefEditRequestV1(expected_version_id=uuid4())


def test_question_answer_requires_answer_text() -> None:
    with pytest.raises(ValidationError, match="ANSWER requires"):
        M1QuestionActionV1(
            expected_version_id=uuid4(),
            action="ANSWER",
        )


def test_skip_cannot_smuggle_answer_text() -> None:
    with pytest.raises(ValidationError, match="must not include answer"):
        M1QuestionActionV1(
            expected_version_id=uuid4(),
            action="SKIP",
            answer="Do not treat this as an answer.",
        )


def test_ingest_rejects_whitespace_only_source() -> None:
    with pytest.raises(ValidationError, match="non-whitespace"):
        M1IngestRequestV1(
            source_kind="PASTED_TEXT",
            text="   \n ",
            display_label="empty",
        )
