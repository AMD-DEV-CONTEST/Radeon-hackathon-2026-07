"""Records for DETERMINEX_UNIFIED_PRODUCT_UX_FINAL_STATE_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

UNIFIED_PRODUCT_UX_FINAL_STATE_STATUS_TOKENS = (
    "UNIFIED_PRODUCT_UX_FINAL_STATE_PASSED",
    "UNIFIED_PRODUCT_UX_FINAL_STATE_BLOCKED_MISSING_RUNG",
    "UNIFIED_PRODUCT_UX_FINAL_STATE_BLOCKED_DIMENSION_NOT_CLOSED",
)


@dataclass(frozen=True)
class UnifiedProductUxFinalStateRecord:
    decision: str
    navigation_model_closed: bool
    idea_lab_workflow_closed: bool
    repo_clinic_workflow_closed: bool
    maintenance_bay_workflow_closed: bool
    learning_studio_workflow_closed: bool
    proof_operator_center_viewmodel_closed: bool
    user_levels_teaching_windows_closed: bool
    splash_demo_spec_closed: bool
    source_mutation_authorized: bool
    training_eligible: bool
    release_ready: bool
    unsupported_claims_blocked: bool
    rungs_inspected: tuple[str, ...] = field(default_factory=tuple)
    next_recommended_rung: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["rungs_inspected"] = list(self.rungs_inspected)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_passed(self) -> bool:
        return self.decision == "UNIFIED_PRODUCT_UX_FINAL_STATE_PASSED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("UNIFIED_PRODUCT_UX_FINAL_STATE_BLOCKED_")


__all__ = [
    "UNIFIED_PRODUCT_UX_FINAL_STATE_STATUS_TOKENS",
    "UnifiedProductUxFinalStateRecord",
]
