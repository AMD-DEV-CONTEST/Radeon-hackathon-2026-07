"""Records for CLAUDE_PRE_APPLY_CONFIRMATION_PANEL_LOCK_001.

CLAUDE-AUTH-015 deferred risk: no final 'this will write files'
confirmation panel before the source-apply path commits.

The pre-apply confirmation panel is a backend-defined view-model
that the frontend renders. It must surface, at minimum, every
field the apply gate binds to, and must distinguish the five
authority-relevant UI states.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

PRE_APPLY_CONFIRMATION_PANEL_STATUS_TOKENS = (
    "PRE_APPLY_CONFIRMATION_PANEL_PASSED",
    "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_MISSING_HASH",
    "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_MISSING_VERIFIER",
    "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_AUTHORITY_AMBIGUITY",
    "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_MISSING_SNAPSHOT",
    "PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_TRAINING_OPENED",
)


# Five UI states. Each name is a distinct *strict* meaning.
PRE_APPLY_UI_STATES = (
    "PRE_APPLY_UI_PREVIEW",  # show only — no execution
    "PRE_APPLY_UI_DRY_RUN",  # ran a temp-verifier, no real write
    "PRE_APPLY_UI_APPROVED",  # operator approved; no write yet
    "PRE_APPLY_UI_SOURCE_MUTATION_AUTHORIZED",  # apply gate green-lit
    "PRE_APPLY_UI_SOURCE_MUTATION_APPLIED",  # post-fact: wrote happened
)


@dataclass(frozen=True)
class PreApplyConfirmationPanelViewModel:
    """The exact set of fields the frontend MUST show before the
    operator can press the apply button. Empty fields are NOT
    allowed for any required field; the panel record blocks if a
    required field is missing."""

    ui_state: str
    files_affected: tuple[str, ...]
    canonical_patch_body_hash: str
    diff_hash: str
    verifier_status: str
    rollback_snapshot_ref: str
    source_mutation_consequence_text: str
    training_eligibility_text: str
    source_mutation_authorized: bool = False
    training_eligible: bool = False

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["files_affected"] = list(self.files_affected)
        return d


@dataclass(frozen=True)
class PreApplyConfirmationPanelRecord:
    decision: str
    panel: PreApplyConfirmationPanelViewModel | None
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        if self.panel is not None:
            d["panel"] = self.panel.to_dict()
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_passed(self) -> bool:
        return self.decision == "PRE_APPLY_CONFIRMATION_PANEL_PASSED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("PRE_APPLY_CONFIRMATION_PANEL_BLOCKED_")


__all__ = [
    "PRE_APPLY_CONFIRMATION_PANEL_STATUS_TOKENS",
    "PRE_APPLY_UI_STATES",
    "PreApplyConfirmationPanelRecord",
    "PreApplyConfirmationPanelViewModel",
]
