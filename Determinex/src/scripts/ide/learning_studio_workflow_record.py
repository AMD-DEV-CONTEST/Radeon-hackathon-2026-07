"""Records for DETERMINEX_LEARNING_STUDIO_WORKFLOW_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

LEARNING_STUDIO_WORKFLOW_STATUS_TOKENS = (
    "LEARNING_STUDIO_WORKFLOW_WRITTEN",
    "LEARNING_STUDIO_NON_AUTHORIZING_PASSED",
    "LEARNING_STUDIO_BLOCKED_MUTATION_CONFUSION",
    "LEARNING_STUDIO_BLOCKED_FALSE_SUCCESS",
)


LEARNING_MODES = (
    "explain_this_repo",
    "explain_this_file",
    "explain_this_error",
    "explain_this_test_failure",
    "teach_me_the_concept",
    "compare_possible_fixes",
    "walk_me_through_the_patch",
    "show_beginner_vs_professional_version",
    "generate_learning_checklist",
)


@dataclass(frozen=True)
class LearningStudioOutput:
    mode: str
    text: str
    suggests_fix: bool = False
    suggests_new_project: bool = False
    routes_to: str = ""  # "repo_clinic", "idea_lab", or "" for none
    claims_repair_success: bool = False
    claims_authorized_apply: bool = False


@dataclass(frozen=True)
class LearningStudioWorkflowRecord:
    decision: str
    modes_supported: tuple[str, ...]
    output: LearningStudioOutput | None
    non_authorizing: bool
    routes_to_gated_workflow_when_needed: bool
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["modes_supported"] = list(self.modes_supported)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_written(self) -> bool:
        return self.decision in (
            "LEARNING_STUDIO_WORKFLOW_WRITTEN",
            "LEARNING_STUDIO_NON_AUTHORIZING_PASSED",
        )

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("LEARNING_STUDIO_BLOCKED_")


__all__ = [
    "LEARNING_STUDIO_WORKFLOW_STATUS_TOKENS",
    "LEARNING_MODES",
    "LearningStudioOutput",
    "LearningStudioWorkflowRecord",
]
