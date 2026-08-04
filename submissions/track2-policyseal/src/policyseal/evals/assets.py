from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from policyseal.domain.enums import (
    Action,
    Channel,
    Classification,
    ContentCategory,
    Purpose,
    RecipientProfile,
    RevisionStatus,
)
from policyseal.policy.schema import TransformKind


class EvalAssetError(ValueError):
    """A frozen evaluation asset is missing or malformed."""


class ExpectedStatus(StrEnum):
    SAFE = "safe"
    REQUIRE_APPROVAL = "require_approval"
    BLOCK = "block"
    PROCESSING_FAILED = "processing_failed"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CopilotIntent(StrEnum):
    EXPLAIN = "explain"
    SIMULATE = "simulate"
    DRAFT_EXCEPTION = "draft_exception"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GoldenContext(StrictModel):
    recipient: RecipientProfile
    organization: str = Field(min_length=3)
    recipient_id: str = Field(min_length=3)
    purpose: Purpose
    channel: Channel
    classification: Classification
    policy_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")


class GoldenDecision(StrictModel):
    location: str = Field(min_length=3)
    category: ContentCategory
    action: Action
    rule_ids: tuple[str, ...] = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    transform: TransformKind | None = None

    @model_validator(mode="after")
    def validate_transform(self) -> GoldenDecision:
        transform_actions = {Action.MASK, Action.FILTER, Action.GENERALIZE}
        if self.action in transform_actions and self.transform is None:
            raise ValueError("transform action requires an expected transform")
        if self.action not in transform_actions and self.transform is not None:
            raise ValueError("non-transform action cannot declare a transform")
        return self


class GoldenScenario(StrictModel):
    id: str = Field(pattern=r"^scenario-[0-9]{2}$")
    title: str = Field(min_length=6)
    source_id: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    context: GoldenContext
    expected_status: ExpectedStatus
    expected_revision_status: RevisionStatus
    decisions: tuple[GoldenDecision, ...]
    required_literals: tuple[str, ...] = ()
    prohibited_literals: tuple[str, ...] = ()
    model_available: bool = True
    safer_placeholder_selected: bool = False

    @model_validator(mode="after")
    def validate_status_contract(self) -> GoldenScenario:
        expected_revision = {
            ExpectedStatus.SAFE: RevisionStatus.EXPORTABLE,
            ExpectedStatus.REQUIRE_APPROVAL: RevisionStatus.AWAITING_APPROVAL,
            ExpectedStatus.BLOCK: RevisionStatus.BLOCKED,
            ExpectedStatus.PROCESSING_FAILED: RevisionStatus.PROCESSING_FAILED,
        }[self.expected_status]
        if self.expected_revision_status is not expected_revision:
            raise ValueError("scenario and revision statuses disagree")
        if self.expected_status is not ExpectedStatus.PROCESSING_FAILED and not self.decisions:
            raise ValueError("non-failure scenarios require at least one Golden decision")
        return self


class ScenarioFile(StrictModel):
    schema_version: int = Field(ge=1, le=1)
    scenarios: tuple[GoldenScenario, ...]


class SemanticSnippet(StrictModel):
    id: str = Field(pattern=r"^semantic-[0-9]{3}$")
    text: str = Field(min_length=12, max_length=500)
    expected_category: ContentCategory
    risk: RiskLevel
    scenario: str = Field(pattern=r"^(xlsx|docx|pdf)$")


class RetrievalQuestion(StrictModel):
    id: str = Field(pattern=r"^retrieval-[0-9]{2}$")
    question: str = Field(min_length=12, max_length=300)
    expected_evidence_ids: tuple[str, ...] = Field(min_length=1)
    tags: tuple[str, ...] = ()


class CopilotTurn(StrictModel):
    user: str = Field(min_length=4, max_length=500)
    intent: CopilotIntent
    expected_rule_ids: tuple[str, ...] = ()
    expected_evidence_ids: tuple[str, ...] = Field(min_length=1)
    must_include: tuple[str, ...] = ()
    must_not_include: tuple[str, ...] = ()


class CopilotDialogue(StrictModel):
    id: str = Field(pattern=r"^dialogue-[0-9]{2}$")
    scenario_id: str = Field(pattern=r"^scenario-[0-9]{2}$")
    turns: tuple[CopilotTurn, ...] = Field(min_length=3, max_length=3)


class DialogueFile(StrictModel):
    schema_version: int = Field(ge=1, le=1)
    dialogues: tuple[CopilotDialogue, ...]


@dataclass(frozen=True, slots=True)
class EvalAssets:
    scenarios: tuple[GoldenScenario, ...]
    semantic_snippets: tuple[SemanticSnippet, ...]
    retrieval_questions: tuple[RetrievalQuestion, ...]
    copilot_dialogues: tuple[CopilotDialogue, ...]

    @property
    def scenario_status_counts(self) -> dict[str, int]:
        counts = Counter(scenario.expected_status.value for scenario in self.scenarios)
        return dict(sorted(counts.items()))


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvalAssetError(f"cannot load {path}: {error}") from error


def _read_jsonl(path: Path) -> list[Any]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise EvalAssetError(f"cannot load {path}: {error}") from error
    records: list[Any] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise EvalAssetError(f"invalid JSON at {path}:{line_number}: {error}") from error
    return records


def load_eval_assets(root: Path = Path("evals/goldens")) -> EvalAssets:
    try:
        scenarios = ScenarioFile.model_validate(_read_json(root / "scenarios.json"))
        snippets = tuple(
            SemanticSnippet.model_validate(item)
            for item in _read_jsonl(root / "semantic-snippets.jsonl")
        )
        questions = tuple(
            RetrievalQuestion.model_validate(item)
            for item in _read_jsonl(root / "retrieval-questions.jsonl")
        )
        dialogues = DialogueFile.model_validate(_read_json(root / "copilot-dialogues.json"))
    except ValidationError as error:
        raise EvalAssetError(f"evaluation schema validation failed: {error}") from error
    return EvalAssets(
        scenarios=scenarios.scenarios,
        semantic_snippets=snippets,
        retrieval_questions=questions,
        copilot_dialogues=dialogues.dialogues,
    )
