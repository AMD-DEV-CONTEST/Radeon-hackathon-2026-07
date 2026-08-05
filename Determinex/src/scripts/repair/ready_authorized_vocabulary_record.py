"""Records for CLAUDE_AUTH_005_READY_AUTHORIZED_LANGUAGE_LOCK_001.

The Claude IDE / repair / frontend lane uses a wide vocabulary of
status tokens (READY, ADMITTED, ACCEPTED, ...). Without a strict
classifier, an operator (or another agent reading the surface)
might equate READY with AUTHORIZED.

This module declares the exhaustive 8-class vocabulary the
classifier must map tokens into. None of those classes are
synonyms — in particular ``capability_available`` (READY)
is NOT ``execution_authorized``, ``source_mutation_authorized``,
or ``training_eligible``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

# The 8 disjoint classes the campaign requires.
AUTHORITY_VOCABULARY_CLASSES = (
    "capability_available",
    "evidence_present",
    "request_pending",
    "admission_present",
    "approval_present",
    "execution_authorized",
    "source_mutation_authorized",
    "training_eligible",
)


# Class precedence — used only for the "does this class imply
# authorization?" guardrail in the lock test. capability_available
# is the WEAKEST signal. source_mutation_authorized and
# training_eligible are the STRONGEST and most dangerous: a token
# may only be classified there if it represents a successful
# completion of the specific gate, never a precondition.
CLASSES_THAT_IMPLY_AUTHORIZATION = frozenset(
    {
        "execution_authorized",
        "source_mutation_authorized",
        "training_eligible",
    }
)


READY_AUTHORIZED_LANGUAGE_STATUS_TOKENS = (
    "READY_AUTHORIZED_LANGUAGE_PASSED",
    "READY_AUTHORIZED_LANGUAGE_BLOCKED_AMBIGUOUS_LABEL",
    "READY_AUTHORIZED_LANGUAGE_BLOCKED_UI_AUTHORITY_CONFUSION",
)


@dataclass(frozen=True)
class TokenClassification:
    """How a single status token classifies into the 8-class
    vocabulary."""

    token: str
    surface: str  # "backend", "frontend", or "shared"
    vocabulary_class: str
    rationale: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ReadyAuthorizedLanguageRecord:
    decision: str
    tokens_classified: tuple[TokenClassification, ...]
    ambiguous_labels: tuple[str, ...]
    ui_authority_confusions: tuple[str, ...]
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["tokens_classified"] = [c.to_dict() for c in self.tokens_classified]
        d["ambiguous_labels"] = list(self.ambiguous_labels)
        d["ui_authority_confusions"] = list(self.ui_authority_confusions)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_passed(self) -> bool:
        return self.decision == "READY_AUTHORIZED_LANGUAGE_PASSED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("READY_AUTHORIZED_LANGUAGE_BLOCKED_")


__all__ = [
    "AUTHORITY_VOCABULARY_CLASSES",
    "CLASSES_THAT_IMPLY_AUTHORIZATION",
    "READY_AUTHORIZED_LANGUAGE_STATUS_TOKENS",
    "TokenClassification",
    "ReadyAuthorizedLanguageRecord",
]
