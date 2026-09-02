"""Records for DETERMINEX_REACT_IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_LOCK_001.

Read-only binding to the Codex-side Idea Lab verified Python CLI
splash demo evidence. Exposes a deterministic, JSON-serializable
status the React Idea Lab panel may display.

Hard rules: the record may surface scoped per-fixture status,
tests/smoke pass, evidence ref, claim boundary, training False —
and MUST NOT broaden that into all-app / all-language /
production-ready / training-enabled / source-mutation-authorized
/ no-followup / release-ready claims.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_STATUS_TOKENS = (
    "REACT_IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_PASSED",
    "REACT_IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_AWAITING_EVIDENCE",
    "REACT_IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_BROAD_CLAIM",
    "REACT_IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
)


# Phrases that, if present in the rendered binding, indicate a
# forbidden broadening of the scoped demo claim. Surfacing any of
# these from the binding is a refusal.
FORBIDDEN_BROAD_CLAIM_PHRASES = (
    "all apps",
    "any language",
    "all codebases",
    "production-ready arbitrary",
    "training enabled",
    "source_mutation_authorized: true",
    "no-followup support",
    "release_ready: true",
)


@dataclass(frozen=True)
class IdeaLabVerifiedDemoStatus:
    """The render-safe view-model the React panel consumes."""

    decision: str
    demo_title: str
    target_surface: str
    target_app_class: str
    target_language: str
    beginner_idea: str
    tests_passed: bool
    smoke_passed: bool
    verified_working_local_app: bool
    evidence_ref: str
    claim_boundary: tuple[str, ...]
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["claim_boundary"] = list(self.claim_boundary)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_passed(self) -> bool:
        return self.decision == "REACT_IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_PASSED"

    @property
    def is_awaiting(self) -> bool:
        return self.decision == "REACT_IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_AWAITING_EVIDENCE"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("REACT_IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_")


__all__ = [
    "IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_STATUS_TOKENS",
    "FORBIDDEN_BROAD_CLAIM_PHRASES",
    "IdeaLabVerifiedDemoStatus",
]
