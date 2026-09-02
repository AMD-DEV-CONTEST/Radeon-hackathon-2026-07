"""Minimal, model-neutral contracts for skill-guided analysis."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Iterable, Protocol

if TYPE_CHECKING:
    from .models import Event

_SKILL_ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{0,99}")
_EVENT_TYPE_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,99}")
_ASSET_TYPE_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,99}")


class SkillStatus(StrEnum):
    """Minimal lifecycle state for deterministic resolution."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    """One bounded declarative skill definition without executable hooks."""

    skill_id: str
    version: str
    status: SkillStatus
    analysis_instructions: str
    supported_event_types: tuple[str, ...] = ()
    supported_asset_types: tuple[str, ...] = ()
    escalation_rules: tuple[str, ...] = ()
    knowledge_query_hints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.skill_id, str)
            or _SKILL_ID_PATTERN.fullmatch(self.skill_id) is None
        ):
            raise ValueError("skill_id is invalid")
        self._require_text(self.version, "version", 100)
        self._require_text(
            self.analysis_instructions,
            "analysis_instructions",
            4_000,
        )
        try:
            status = SkillStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise ValueError("skill status is invalid") from exc
        event_types = self._normalize_identifiers(
            self.supported_event_types,
            "supported_event_types",
            _EVENT_TYPE_PATTERN,
        )
        asset_types = self._normalize_identifiers(
            self.supported_asset_types,
            "supported_asset_types",
            _ASSET_TYPE_PATTERN,
        )
        escalation_rules = self._normalize_text_collection(
            self.escalation_rules,
            "escalation_rules",
            maximum_items=20,
            maximum_length=500,
        )
        knowledge_query_hints = self._normalize_text_collection(
            self.knowledge_query_hints,
            "knowledge_query_hints",
            maximum_items=30,
            maximum_length=100,
        )
        object.__setattr__(self, "status", status)
        object.__setattr__(
            self,
            "supported_event_types",
            event_types,
        )
        object.__setattr__(
            self,
            "supported_asset_types",
            asset_types,
        )
        object.__setattr__(self, "escalation_rules", escalation_rules)
        object.__setattr__(
            self,
            "knowledge_query_hints",
            knowledge_query_hints,
        )

    def to_context(self, *, resolution_reason: str) -> SkillContext:
        """Project this definition into the bounded analysis contract."""

        if self.status is not SkillStatus.ACTIVE:
            raise ValueError("only an active skill can create SkillContext")
        return SkillContext(
            skill_id=self.skill_id,
            skill_version=self.version,
            analysis_instructions=self.analysis_instructions,
            escalation_rules=self.escalation_rules,
            knowledge_query_hints=self.knowledge_query_hints,
            resolution_reason=resolution_reason,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON-safe representation."""

        return {
            "skill_id": self.skill_id,
            "version": self.version,
            "status": self.status.value,
            "analysis_instructions": self.analysis_instructions,
            "supported_event_types": list(self.supported_event_types),
            "supported_asset_types": list(self.supported_asset_types),
            "escalation_rules": list(self.escalation_rules),
            "knowledge_query_hints": list(self.knowledge_query_hints),
        }

    @staticmethod
    def _require_text(value: object, field_name: str, maximum: int) -> None:
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or len(value) > maximum
            or "\x00" in value
        ):
            raise ValueError(
                f"{field_name} must be a trimmed non-empty string "
                f"of at most {maximum} characters"
            )

    @staticmethod
    def _normalize_identifiers(
        values: Iterable[str],
        field_name: str,
        pattern: re.Pattern[str],
    ) -> tuple[str, ...]:
        if isinstance(values, (str, bytes)):
            raise ValueError(f"{field_name} must be a collection")
        normalized: set[str] = set()
        for value in values:
            if not isinstance(value, str) or pattern.fullmatch(value) is None:
                raise ValueError(f"{field_name} contains an invalid value")
            normalized.add(value)
            if len(normalized) > 50:
                raise ValueError(f"{field_name} exceeds 50 values")
        return tuple(sorted(normalized))

    @staticmethod
    def _normalize_text_collection(
        values: Iterable[str],
        field_name: str,
        *,
        maximum_items: int,
        maximum_length: int,
    ) -> tuple[str, ...]:
        if isinstance(values, (str, bytes)):
            raise ValueError(f"{field_name} must be a collection")
        normalized: set[str] = set()
        for value in values:
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or len(value) > maximum_length
                or "\x00" in value
            ):
                raise ValueError(f"{field_name} contains an invalid value")
            normalized.add(value)
            if len(normalized) > maximum_items:
                raise ValueError(
                    f"{field_name} exceeds {maximum_items} values"
                )
        return tuple(sorted(normalized))


@dataclass(frozen=True, slots=True)
class SkillContext:
    """Bounded skill guidance passed explicitly to analysis providers."""

    skill_id: str
    skill_version: str
    analysis_instructions: str
    escalation_rules: tuple[str, ...]
    knowledge_query_hints: tuple[str, ...]
    resolution_reason: str

    def __post_init__(self) -> None:
        definition = SkillDefinition(
            skill_id=self.skill_id,
            version=self.skill_version,
            status=SkillStatus.ACTIVE,
            analysis_instructions=self.analysis_instructions,
            escalation_rules=self.escalation_rules,
            knowledge_query_hints=self.knowledge_query_hints,
        )
        SkillDefinition._require_text(
            self.resolution_reason,
            "resolution_reason",
            500,
        )
        object.__setattr__(
            self,
            "escalation_rules",
            definition.escalation_rules,
        )
        object.__setattr__(
            self,
            "knowledge_query_hints",
            definition.knowledge_query_hints,
        )

    def to_prompt_payload(self) -> dict[str, Any]:
        """Return only the explicit bounded model-input fields."""

        return {
            "skill_id": self.skill_id,
            "skill_version": self.skill_version,
            "analysis_instructions": self.analysis_instructions,
            "escalation_rules": list(self.escalation_rules),
            "knowledge_query_hints": list(self.knowledge_query_hints),
        }

    def audit_metadata(self) -> dict[str, str]:
        """Return stable identity and deterministic resolution evidence."""

        return {
            "skill_id": self.skill_id,
            "skill_version": self.skill_version,
            "skill_resolution": self.resolution_reason,
        }


class SkillResolver(Protocol):
    """Replaceable deterministic Event-to-SkillContext boundary."""

    def resolve(self, event: Event) -> SkillContext:
        """Return exactly one eligible context or fail explicitly."""

        ...
