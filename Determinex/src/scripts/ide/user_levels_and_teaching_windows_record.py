"""Records for DETERMINEX_UNIFIED_USER_LEVELS_AND_TEACHING_WINDOWS_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

USER_LEVELS_TEACHING_WINDOWS_STATUS_TOKENS = (
    "USER_LEVELS_TEACHING_WINDOWS_WRITTEN",
    "USER_LEVELS_TEACHING_WINDOWS_VALIDATED",
    "USER_LEVELS_BLOCKED_PROOF_HIDDEN",
    "USER_LEVELS_BLOCKED_AUTHORITY_BYPASS",
)


USER_LEVELS = (
    "beginner_no_experience",
    "learner",
    "vibe_coder",
    "junior_developer",
    "professional_developer",
    "maintainer",
    "security_conscious_operator",
    "power_user",
)


@dataclass(frozen=True)
class UserLevelProfile:
    level: str
    default_explanations: str
    level_of_detail: str
    warnings_caveats: tuple[str, ...]
    ui_complexity: str  # "minimal" / "moderate" / "full"
    teaching_windows: tuple[str, ...]
    suggested_next_action: str
    what_not_to_hide: tuple[str, ...]
    what_not_to_over_explain: tuple[str, ...]
    proof_status_visible: bool
    authority_gates_active: bool
    teaching_window_explains_blocked_reason: bool

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        for f in (
            "warnings_caveats",
            "teaching_windows",
            "what_not_to_hide",
            "what_not_to_over_explain",
        ):
            d[f] = list(d[f])
        return d


@dataclass(frozen=True)
class UserLevelsAndTeachingWindowsRecord:
    decision: str
    levels: tuple[UserLevelProfile, ...]
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["levels"] = [l.to_dict() for l in self.levels]
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_written(self) -> bool:
        return self.decision in (
            "USER_LEVELS_TEACHING_WINDOWS_WRITTEN",
            "USER_LEVELS_TEACHING_WINDOWS_VALIDATED",
        )

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("USER_LEVELS_BLOCKED_")


__all__ = [
    "USER_LEVELS_TEACHING_WINDOWS_STATUS_TOKENS",
    "USER_LEVELS",
    "UserLevelProfile",
    "UserLevelsAndTeachingWindowsRecord",
]
