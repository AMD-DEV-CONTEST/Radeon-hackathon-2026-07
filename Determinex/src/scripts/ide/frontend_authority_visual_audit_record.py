"""Records for CLAUDE_FRONTEND_AUTHORITY_VISUAL_AUDIT_LOCK_001.

CLAUDE-AUTH-012 deferred risk: frontend invoke client refuses
backend-set source_mutation_authorized=true only after a roundtrip,
and panels mix authority signals.

The frontend authority visual audit defines a backend view-model
that classifies UI sections and their authority-relevant
properties. The audit refuses any layout that:

  * mixes diagnosis with source-mutation status
  * mixes operator queue with approval grants
  * displays a success ('green') state for any authority signal
    without an accompanying 'does NOT authorize' caption
  * lacks a visible 'blocked' section when the underlying state
    is blocked
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

FRONTEND_AUTHORITY_VISUAL_AUDIT_STATUS_TOKENS = (
    "FRONTEND_AUTHORITY_VISUAL_AUDIT_PASSED",
    "FRONTEND_AUTHORITY_VISUAL_AUDIT_BLOCKED_AMBIGUOUS_STATE",
    "FRONTEND_AUTHORITY_VISUAL_AUDIT_BLOCKED_MISSING_NEGATIVE_AUTHORITY",
    "FRONTEND_AUTHORITY_VISUAL_AUDIT_BLOCKED_SECTION_MERGE",
    "FRONTEND_AUTHORITY_VISUAL_AUDIT_BLOCKED_BLOCKED_STATE_HIDDEN",
)


# Eight distinct visual sections the frontend must separate.
FRONTEND_VISUAL_SECTIONS = (
    "diagnosis",
    "patch_preview",
    "verifier_result",
    "approval_request",
    "source_mutation_status",
    "rollback_status",
    "evidence_status",
    "training_eligibility_status",
)

# Sections that MUST display a "does not authorize X" caption
# whenever a "success" / green state is shown.
SECTIONS_REQUIRING_NEGATIVE_AUTHORITY_CAPTION = frozenset(
    {
        "diagnosis",
        "patch_preview",
        "verifier_result",
        "approval_request",
        "evidence_status",
        "training_eligibility_status",
    }
)


@dataclass(frozen=True)
class SectionState:
    """Description of one visual section."""

    section: str
    visible: bool
    is_success_state: bool
    negative_authority_caption: str  # e.g. "approval ≠ source mutation"
    is_blocked_state: bool
    blocked_text: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FrontendAuthorityVisualAuditRecord:
    decision: str
    sections: tuple[SectionState, ...]
    ambiguities: tuple[str, ...]
    section_merges: tuple[str, ...]
    blocked_state_hidden: tuple[str, ...]
    missing_negative_authority: tuple[str, ...]
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["sections"] = [s.to_dict() for s in self.sections]
        d["ambiguities"] = list(self.ambiguities)
        d["section_merges"] = list(self.section_merges)
        d["blocked_state_hidden"] = list(self.blocked_state_hidden)
        d["missing_negative_authority"] = list(self.missing_negative_authority)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_passed(self) -> bool:
        return self.decision == "FRONTEND_AUTHORITY_VISUAL_AUDIT_PASSED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("FRONTEND_AUTHORITY_VISUAL_AUDIT_BLOCKED_")


__all__ = [
    "FRONTEND_AUTHORITY_VISUAL_AUDIT_STATUS_TOKENS",
    "FRONTEND_VISUAL_SECTIONS",
    "SECTIONS_REQUIRING_NEGATIVE_AUTHORITY_CAPTION",
    "SectionState",
    "FrontendAuthorityVisualAuditRecord",
]
