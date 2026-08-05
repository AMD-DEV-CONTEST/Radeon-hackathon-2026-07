"""Records for CLAUDE_IDE_HYGIENE_FINAL_STATE_LOCK_001.

Finale of DETERMINEX_CLAUDE_IDE_AUTHORITY_AND_CLAIMS_HYGIENE_SERIES.
Captures the per-dimension closure of the eight prior rungs plus
the aggregate invariants:

  * source_mutation_authorized stays False
  * training_eligible stays False
  * release_ready: False (public_release_scrub_required)
  * demo_ready: True iff the demo script is locked and passes
  * Forge/mobile remain planned/research_track
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

CLAUDE_IDE_HYGIENE_FINAL_STATE_STATUS_TOKENS = (
    "CLAUDE_IDE_HYGIENE_FINAL_STATE_PASSED",
    "CLAUDE_IDE_HYGIENE_FINAL_STATE_BLOCKED_MISSING_RUNG",
    "CLAUDE_IDE_HYGIENE_FINAL_STATE_BLOCKED_DIMENSION_NOT_CLOSED",
    "CLAUDE_IDE_HYGIENE_FINAL_STATE_BLOCKED_AGGREGATE_INVARIANT_VIOLATED",
)


@dataclass(frozen=True)
class ClaudeIdeHygieneFinalStateRecord:
    decision: str
    ready_authorized_language_closed: bool
    operator_identity_bounding_closed: bool
    approval_replay_staleness_closed: bool
    pre_apply_confirmation_closed: bool
    config_root_allowlist_closed: bool
    frontend_authority_visuals_closed: bool
    public_claims_ledger_closed: bool
    demo_script_closed: bool
    source_mutation_authorized: bool
    training_eligible: bool
    release_ready: bool
    demo_ready: bool
    forge_status: str
    mobile_console_status: str
    deferred_findings: tuple[str, ...] = field(default_factory=tuple)
    next_recommended_rung: str = ""
    rungs_inspected: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["deferred_findings"] = list(self.deferred_findings)
        d["rungs_inspected"] = list(self.rungs_inspected)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_passed(self) -> bool:
        return self.decision == "CLAUDE_IDE_HYGIENE_FINAL_STATE_PASSED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("CLAUDE_IDE_HYGIENE_FINAL_STATE_BLOCKED_")


__all__ = [
    "CLAUDE_IDE_HYGIENE_FINAL_STATE_STATUS_TOKENS",
    "ClaudeIdeHygieneFinalStateRecord",
]
