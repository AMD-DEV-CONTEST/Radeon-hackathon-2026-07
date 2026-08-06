"""Deterministic responsibility routing from reviewed local configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Self

from .models import Event


@dataclass(frozen=True, slots=True)
class ResponsibilityAssignment:
    """The owner selected by one deterministic directory rule."""

    owner_id: str
    owner_name: str
    match_type: str
    matched_key: str


class ResponsibilityDirectory:
    """Resolve Event context without using model output or mutable state."""

    UNASSIGNED = ResponsibilityAssignment(
        owner_id="UNASSIGNED",
        owner_name="Unassigned",
        match_type="unassigned",
        matched_key="",
    )
    _RULE_TYPES = ("asset_id", "location", "event_type")

    def __init__(
        self,
        *,
        asset_id: Mapping[str, Mapping[str, str]] | None = None,
        location: Mapping[str, Mapping[str, str]] | None = None,
        event_type: Mapping[str, Mapping[str, str]] | None = None,
    ) -> None:
        self._rules = {
            "asset_id": self._validate_rules("asset_id", asset_id or {}),
            "location": self._validate_rules("location", location or {}),
            "event_type": self._validate_rules(
                "event_type", event_type or {}
            ),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Build a directory from the bounded JSON configuration shape."""

        if not isinstance(data, Mapping):
            raise ValueError("responsibility directory must be an object")
        unknown = set(data) - set(cls._RULE_TYPES) - {"configuration_notice"}
        if unknown:
            raise ValueError(
                "unknown responsibility directory fields: "
                + ", ".join(sorted(str(key) for key in unknown))
            )
        notice = data.get("configuration_notice")
        if notice is not None and (
            not isinstance(notice, str) or not notice.strip()
        ):
            raise ValueError("configuration_notice must be a non-empty string")
        return cls(
            asset_id=data.get("asset_id"),
            location=data.get("location"),
            event_type=data.get("event_type"),
        )

    @classmethod
    def from_file(cls, path: str | Path) -> Self:
        """Load reviewed local routing rules; no remote lookup is performed."""

        directory_path = Path(path)
        try:
            payload = json.loads(directory_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"invalid responsibility directory: {directory_path.name}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise ValueError("responsibility directory must be an object")
        return cls.from_dict(payload)

    def resolve(self, event: Event) -> ResponsibilityAssignment:
        """Apply asset, location and event-type rules in fixed order."""

        for field_name, match_type in (
            ("asset_id", "asset"),
            ("location", "location"),
            ("event_type", "event_type"),
        ):
            key = getattr(event, field_name)
            if key and key in self._rules[field_name]:
                owner_id, owner_name = self._rules[field_name][key]
                return ResponsibilityAssignment(
                    owner_id=owner_id,
                    owner_name=owner_name,
                    match_type=match_type,
                    matched_key=key,
                )
        return self.UNASSIGNED

    @staticmethod
    def _validate_rules(
        rule_type: str,
        rules: Mapping[str, Mapping[str, str]],
    ) -> dict[str, tuple[str, str]]:
        if not isinstance(rules, Mapping):
            raise ValueError(f"{rule_type} rules must be an object")
        validated: dict[str, tuple[str, str]] = {}
        for key, owner in rules.items():
            if (
                not isinstance(key, str)
                or not key
                or key != key.strip()
            ):
                raise ValueError(
                    f"{rule_type} rule keys must be non-empty exact strings"
                )
            if not isinstance(owner, Mapping):
                raise ValueError(f"owner for {rule_type}:{key} must be an object")
            unknown = set(owner) - {"owner_id", "owner_name"}
            if unknown:
                raise ValueError(
                    f"owner for {rule_type}:{key} has unknown fields"
                )
            owner_id = owner.get("owner_id")
            owner_name = owner.get("owner_name")
            if not isinstance(owner_id, str) or not owner_id.strip():
                raise ValueError(f"owner_id for {rule_type}:{key} is required")
            if not isinstance(owner_name, str) or not owner_name.strip():
                raise ValueError(
                    f"owner_name for {rule_type}:{key} is required"
                )
            validated[key] = (owner_id.strip(), owner_name.strip())
        return validated
