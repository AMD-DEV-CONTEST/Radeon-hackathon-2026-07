from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_factory.models.reasoning import RUNTIME_REASONING_INTENSITY_MAX


TipStatus = Literal["answering", "completed", "failed"]
TipMessageRole = Literal["user", "assistant"]


def utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_tip_id() -> str:
    return uuid4().hex


class TipMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(default_factory=lambda: uuid4().hex)
    role: TipMessageRole
    content: str
    created_at: str = Field(default_factory=utc_now_text)


class TipRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tip_id: str = Field(default_factory=new_tip_id)
    scope_type: str
    scope_id: str
    source_message_id: str
    source_role: str
    source_content: str
    selected_text: str
    selection_start: int | None = Field(default=None, ge=0)
    selection_end: int | None = Field(default=None, ge=0)
    agent_package_id: str | None = None
    model_profile_id: str | None = None
    reasoning_intensity: int | None = Field(default=None, ge=0, le=RUNTIME_REASONING_INTENSITY_MAX)
    status: TipStatus = "answering"
    error: str | None = None
    messages: list[TipMessage] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = Field(default_factory=utc_now_text)

    @field_validator(
        "scope_type",
        "scope_id",
        "source_message_id",
        "source_role",
        "source_content",
        "selected_text",
    )
    @classmethod
    def required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("value must not be empty")
        return text


class TipCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_type: str
    scope_id: str
    source_message_id: str
    source_role: str
    source_content: str
    selected_text: str
    question: str
    selection_start: int | None = Field(default=None, ge=0)
    selection_end: int | None = Field(default=None, ge=0)
    agent_package_id: str | None = None
    model_profile_id: str | None = None
    reasoning_intensity: int | None = Field(default=None, ge=0, le=RUNTIME_REASONING_INTENSITY_MAX)

    @field_validator(
        "scope_type",
        "scope_id",
        "source_message_id",
        "source_role",
        "source_content",
        "selected_text",
        "question",
    )
    @classmethod
    def required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("value must not be empty")
        return text


class TipFollowUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str

    @field_validator("question")
    @classmethod
    def required_question(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("question must not be empty")
        return text
