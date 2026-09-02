"""Records for DETERMINEX_IDEA_LAB_WORKFLOW_LOCK_001.

Workflow for new-app creation. Build It is disabled until support
check passes; Working is disabled until build/test/smoke evidence
exists; unsupported features are visible; external setup is
caveated; training is never opened.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

IDEA_LAB_WORKFLOW_STATUS_TOKENS = (
    "IDEA_LAB_WORKFLOW_WRITTEN",
    "IDEA_LAB_WORKFLOW_BLOCKED_UNSUPPORTED_CLAIM",
    "IDEA_LAB_WORKFLOW_BLOCKED_FALSE_SUCCESS",
    "IDEA_LAB_WORKFLOW_BLOCKED_MISSING_SUPPORT_CHECK",
)


IDEA_LAB_STATES = (
    "IDEA_CAPTURED",
    "SPEC_WRITTEN",
    "SUPPORT_CHECK_REQUIRED",
    "UNSUPPORTED_REQUEST",
    "BLUEPRINT_READY",
    "SCAFFOLD_READY",
    "GENERATED_UNVERIFIED",
    "TESTS_PASSED",
    "SMOKE_PASSED",
    "VERIFIED_WORKING_LOCAL_APP",
    "HONEST_FAILURE",
)


# Required ordered flow steps.
IDEA_LAB_FLOW_STEPS = (
    "idea_intake",
    "structured_spec",
    "beginner_summary",
    "support_matrix_check",
    "blueprint",
    "scaffold_request",
    "acceptance_tests",
    "implementation_plan",
    "build_test_verifier",
    "smoke_plan",
    "bounded_repair_plan",
    "final_report",
    "evidence",
    "training_remains_blocked",
)


@dataclass(frozen=True)
class IdeaLabWorkflowRecord:
    decision: str
    flow_steps: tuple[str, ...]
    states: tuple[str, ...]
    build_it_enabled: bool
    working_label_enabled: bool
    unsupported_features_visible: bool
    external_caveats_visible: bool
    support_check_passed: bool
    build_verifier_passed: bool
    tests_passed: bool
    smoke_passed: bool
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["flow_steps"] = list(self.flow_steps)
        d["states"] = list(self.states)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_written(self) -> bool:
        return self.decision == "IDEA_LAB_WORKFLOW_WRITTEN"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("IDEA_LAB_WORKFLOW_BLOCKED_")


__all__ = [
    "IDEA_LAB_WORKFLOW_STATUS_TOKENS",
    "IDEA_LAB_STATES",
    "IDEA_LAB_FLOW_STEPS",
    "IdeaLabWorkflowRecord",
]
