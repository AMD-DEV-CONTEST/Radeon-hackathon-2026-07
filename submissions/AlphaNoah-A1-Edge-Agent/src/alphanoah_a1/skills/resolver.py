"""Deterministic in-memory Skill resolution."""

from __future__ import annotations

from collections.abc import Iterable

from ..exceptions import SkillConflictError, SkillNotFoundError
from ..models import Event
from ..skill import (
    SkillContext,
    SkillDefinition,
    SkillStatus,
)


class DeterministicSkillResolver:
    """Resolve exactly one active Skill by stable Event fields."""

    def __init__(self, definitions: Iterable[SkillDefinition]):
        if isinstance(definitions, (str, bytes)):
            raise TypeError("definitions must contain SkillDefinition objects")
        validated: list[SkillDefinition] = []
        identities: set[tuple[str, str]] = set()
        for definition in definitions:
            if not isinstance(definition, SkillDefinition):
                raise TypeError(
                    "definitions must contain SkillDefinition objects"
                )
            identity = (definition.skill_id, definition.version)
            if identity in identities:
                raise ValueError(
                    "duplicate Skill definition: "
                    + f"{definition.skill_id}@{definition.version}"
                )
            if (
                not definition.supported_event_types
                and not definition.supported_asset_types
            ):
                raise ValueError(
                    "generic fallback Skills are not enabled"
                )
            identities.add(identity)
            validated.append(definition)
        self.definitions = tuple(
            sorted(
                validated,
                key=lambda item: (item.skill_id, item.version),
            )
        )

    def resolve(self, event: Event) -> SkillContext:
        """Return one highest-specificity active Skill or fail explicitly."""

        if not isinstance(event, Event):
            raise TypeError("SkillResolver requires an Event")
        candidates: list[tuple[int, tuple[str, ...], SkillDefinition]] = []
        deprecated_matches: list[SkillDefinition] = []
        for definition in self.definitions:
            match = self._match(definition, event)
            if match is None:
                continue
            specificity, matched_fields = match
            if definition.status is SkillStatus.DEPRECATED:
                deprecated_matches.append(definition)
                continue
            candidates.append((specificity, matched_fields, definition))

        if not candidates:
            if deprecated_matches:
                identifiers = ", ".join(
                    f"{item.skill_id}@{item.version}"
                    for item in deprecated_matches
                )
                raise SkillNotFoundError(
                    "Only deprecated Skills matched this Event: "
                    + identifiers,
                    code="skill_deprecated_only",
                )
            raise SkillNotFoundError(
                "No active Skill matches this Event.",
                code="skill_not_found",
            )

        highest_specificity = max(item[0] for item in candidates)
        highest = [
            item for item in candidates if item[0] == highest_specificity
        ]
        if len(highest) != 1:
            identifiers = ", ".join(
                f"{item[2].skill_id}@{item[2].version}"
                for item in highest
            )
            raise SkillConflictError(
                "Multiple equally specific Skills match this Event: "
                + identifiers,
                code="skill_resolution_conflict",
            )

        specificity, matched_fields, definition = highest[0]
        reason = (
            "matched:"
            + ",".join(matched_fields)
            + f";specificity={specificity}"
        )
        return definition.to_context(resolution_reason=reason)

    @staticmethod
    def _match(
        definition: SkillDefinition,
        event: Event,
    ) -> tuple[int, tuple[str, ...]] | None:
        matched_fields: list[str] = []
        if definition.supported_event_types:
            if event.event_type not in definition.supported_event_types:
                return None
            matched_fields.append("event_type")

        asset_type_value = event.metadata.get("asset_type")
        asset_type = (
            asset_type_value.strip()
            if isinstance(asset_type_value, str)
            else ""
        )
        if definition.supported_asset_types:
            if asset_type not in definition.supported_asset_types:
                return None
            matched_fields.append("asset_type")

        return len(matched_fields), tuple(matched_fields)
