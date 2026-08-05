"""Records for CLAUDE_PUBLIC_CLAIMS_LEDGER_LOCK_001.

The public claims ledger classifies every Claude/IDE-lane claim
into one of five disjoint classification states so the project's
public-facing language is claim-safe.

Classification states (disjoint):

  * implemented
  * implemented_but_gated_or_blocked
  * planned
  * research_track
  * not_claimed

Hard rules enforced by the lock:

  * No claim may say training works if only a negative guard /
    design exists. (Claims about training that aren't 'not_claimed'
    or 'planned' or 'research_track' are blocked.)
  * No claim may imply public release readiness if install / demo /
    repo scrub is incomplete.
  * No claim may imply benchmark execution from the Claude lane.
  * No claim may imply source mutation without explicit
    approval/verifier gates.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

PUBLIC_CLAIMS_LEDGER_STATUS_TOKENS = (
    "PUBLIC_CLAIMS_LEDGER_WRITTEN",
    "PUBLIC_CLAIMS_LEDGER_BLOCKED_OVERCLAIM",
    "PUBLIC_CLAIMS_LEDGER_BLOCKED_IMPLEMENTATION_AMBIGUITY",
)


# The five disjoint classification states.
PUBLIC_CLAIM_CLASSIFICATIONS = (
    "implemented",
    "implemented_but_gated_or_blocked",
    "planned",
    "research_track",
    "not_claimed",
)

# Classes that imply the claim is actively true today.
CLASSIFICATIONS_THAT_IMPLY_LIVE_CAPABILITY = frozenset(
    {
        "implemented",
    }
)


@dataclass(frozen=True)
class PublicClaim:
    key: str
    classification: str
    short: str  # one-line public-safe summary
    evidence_ref: str  # lock id or doc path
    blocks_or_gates: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["blocks_or_gates"] = list(self.blocks_or_gates)
        return d


@dataclass(frozen=True)
class PublicClaimsLedgerRecord:
    decision: str
    claims: tuple[PublicClaim, ...]
    overclaims: tuple[str, ...]
    implementation_ambiguities: tuple[str, ...]
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["claims"] = [c.to_dict() for c in self.claims]
        d["overclaims"] = list(self.overclaims)
        d["implementation_ambiguities"] = list(self.implementation_ambiguities)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_written(self) -> bool:
        return self.decision == "PUBLIC_CLAIMS_LEDGER_WRITTEN"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("PUBLIC_CLAIMS_LEDGER_BLOCKED_")


__all__ = [
    "PUBLIC_CLAIMS_LEDGER_STATUS_TOKENS",
    "PUBLIC_CLAIM_CLASSIFICATIONS",
    "CLASSIFICATIONS_THAT_IMPLY_LIVE_CAPABILITY",
    "PublicClaim",
    "PublicClaimsLedgerRecord",
]
