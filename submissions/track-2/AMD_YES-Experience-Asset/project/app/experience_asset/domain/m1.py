"""M1 Experience Brief request, artifact, workspace, and action contracts."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from .enums import (
    QuestionState,
    SourceAuthorship,
    SourceKind,
    TerminalState,
)
from .models import (
    AgentRunStateV1,
    ContractModel,
    ExperienceAssetV1,
    NonEmptyText,
    ProgressEventV1,
    QuestionRecord,
)

M1SourceKind = Literal[
    SourceKind.CONVERSATION,
    SourceKind.PASTED_TEXT,
    SourceKind.TXT_FILE,
    SourceKind.MD_FILE,
    SourceKind.ADAPTED_PUBLIC_FIXTURE,
]


class M1IngestRequestV1(ContractModel):
    """One bounded text source submitted to start an Experience Asset."""

    source_kind: M1SourceKind
    text: str = Field(min_length=1, max_length=200_000)
    display_label: NonEmptyText
    original_file_name: str | None = None
    authorship: SourceAuthorship = SourceAuthorship.USER_AUTHORED
    source_url: str | None = None
    adapted_provenance_notice: str | None = None
    goal_hint: str = Field(default="", max_length=2_000)

    @model_validator(mode="after")
    def file_and_provenance_contracts_hold(self) -> M1IngestRequestV1:
        if not self.text.strip():
            raise ValueError("M1 source text must contain non-whitespace content")
        if self.source_kind is SourceKind.TXT_FILE and not (
            self.original_file_name and self.original_file_name.lower().endswith(".txt")
        ):
            raise ValueError("TXT_FILE requires an original .txt file name")
        if self.source_kind is SourceKind.MD_FILE and not (
            self.original_file_name and self.original_file_name.lower().endswith(".md")
        ):
            raise ValueError("MD_FILE requires an original .md file name")
        if self.source_kind is SourceKind.ADAPTED_PUBLIC_FIXTURE and not (
            self.source_url and self.adapted_provenance_notice
        ):
            raise ValueError(
                "ADAPTED_PUBLIC_FIXTURE requires source_url and adapted provenance notice"
            )
        return self


class ExperienceBriefV1(ContractModel):
    """Typed payload stored inside the canonical M1 artifact envelope."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    context: str = Field(default="", max_length=20_000)
    goal: str = Field(default="", max_length=5_000)
    constraints: list[str] = Field(default_factory=list, max_length=30)
    user_intent: str = Field(default="", max_length=5_000)
    source_boundary: NonEmptyText
    source_ids: list[UUID] = Field(min_length=1)
    statement_ids: list[UUID] = Field(default_factory=list)
    confirmed_statement_count: int = Field(ge=0)
    unresolved_question_count: int = Field(ge=0)


class M1BriefEditRequestV1(ContractModel):
    expected_version_id: UUID
    context: str | None = Field(default=None, max_length=20_000)
    goal: str | None = Field(default=None, max_length=5_000)
    constraints: list[str] | None = Field(default=None, max_length=30)
    user_intent: str | None = Field(default=None, max_length=5_000)
    change_reason: str = Field(default="Autosave M1 Experience Brief edit.", min_length=1)

    @model_validator(mode="after")
    def at_least_one_field_changes(self) -> M1BriefEditRequestV1:
        if all(
            value is None
            for value in (self.context, self.goal, self.constraints, self.user_intent)
        ):
            raise ValueError("M1 brief edit requires at least one changed field")
        return self


class M1QuestionActionV1(ContractModel):
    expected_version_id: UUID
    action: Literal["ANSWER", "SKIP", "DEFER"]
    answer: str | None = Field(default=None, max_length=20_000)

    @model_validator(mode="after")
    def answer_matches_action(self) -> M1QuestionActionV1:
        if self.action == "ANSWER" and not self.answer:
            raise ValueError("ANSWER requires non-empty answer text")
        if self.action != "ANSWER" and self.answer is not None:
            raise ValueError("SKIP and DEFER must not include answer text")
        return self


class M1ConfirmRequestV1(ContractModel):
    expected_version_id: UUID
    complete_with_gaps: bool = False


class M1VersionActionRequestV1(ContractModel):
    expected_version_id: UUID


class M1AgentRunRequestV1(ContractModel):
    expected_version_id: UUID
    user_goal: str = Field(min_length=1, max_length=2_000)
    allow_current_source_search: bool


class M1ProgressV1(ContractModel):
    """Truthful M1 progress without a fabricated percentage or ETA."""

    artifact_state: str
    confirmed_statement_count: int = Field(ge=0)
    unresolved_question_count: int = Field(ge=0)
    saved_version_id: UUID
    autosave_state: Literal["SAVED"] = "SAVED"
    last_saved_at: AwareDatetime


class M1WorkspaceV1(ContractModel):
    asset: ExperienceAssetV1
    brief: ExperienceBriefV1
    questions: list[QuestionRecord] = Field(max_length=3)
    progress: M1ProgressV1
    progress_event: ProgressEventV1
    terminal_state: TerminalState
    latest_agent_run: AgentRunStateV1 | None = None
    allowed_actions: list[
        Literal[
            "EDIT",
            "ANSWER",
            "SKIP",
            "DEFER",
            "PAUSE",
            "RESUME",
            "CONFIRM",
            "RUN_AGENT_CURRENT",
        ]
    ]

    @model_validator(mode="after")
    def visible_questions_are_actionable(self) -> M1WorkspaceV1:
        if any(
            question.state not in {QuestionState.OPEN, QuestionState.DEFERRED}
            for question in self.questions
        ):
            raise ValueError("workspace may expose only open or deferred questions")
        if len(self.questions) > 3:
            raise ValueError("M1 workspace may expose at most three questions")
        return self
