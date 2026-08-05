"""Records for CORPUS_ELIGIBILITY_REPAIR_TRACE_GUARD_LOCK_001.

The eligibility guard makes the apparatus's *training-corpus* boundary
explicit. A VerifiedRepairTrace is *evidence* — it lives in
``assurance/evidence/``, it is signed and indexed, and a future audit
can replay it. But a training *corpus row* is a different artifact: it
is the input to model fine-tuning. The guard says, by reason, why a
trace produced by the current campaign is NOT yet admissible as a
training row.

At this rung, every trace is BLOCKED. A future rung may admit live
traces, but only after defeating every blocked reason.
"""

from __future__ import annotations

import enum
import json
from dataclasses import asdict, dataclass, field

CORPUS_ELIGIBILITY_STATUS_TOKENS = (
    "CORPUS_ELIGIBILITY_BLOCKED",
    "CORPUS_ELIGIBILITY_EVIDENCE_ONLY",
    "BLOCKED_MOCKED_MODEL_OUTPUT",
    "BLOCKED_TEMP_WORKSPACE_ONLY",
    "BLOCKED_SOURCE_NOT_APPROVED",
    "BLOCKED_VERIFIER_FAILED",
    "BLOCKED_UNSUPPORTED_REPO",
    "BLOCKED_NO_LIVE_MODEL_CALL",
    "BLOCKED_HUMAN_APPROVAL_REQUIRED",
    "BLOCKED_POLICY",
)


class CorpusEligibilityBlockReason(str, enum.Enum):
    MOCKED_MODEL_OUTPUT = "BLOCKED_MOCKED_MODEL_OUTPUT"
    TEMP_WORKSPACE_ONLY = "BLOCKED_TEMP_WORKSPACE_ONLY"
    SOURCE_NOT_APPROVED = "BLOCKED_SOURCE_NOT_APPROVED"
    VERIFIER_FAILED = "BLOCKED_VERIFIER_FAILED"
    UNSUPPORTED_REPO = "BLOCKED_UNSUPPORTED_REPO"
    NO_LIVE_MODEL_CALL = "BLOCKED_NO_LIVE_MODEL_CALL"
    HUMAN_APPROVAL_REQUIRED = "BLOCKED_HUMAN_APPROVAL_REQUIRED"
    POLICY = "BLOCKED_POLICY"


@dataclass(frozen=True)
class CorpusEligibilityDecision:
    """Immutable eligibility decision for a single repair trace.

    ``decision`` is one of:
      * ``CORPUS_ELIGIBILITY_BLOCKED`` — at least one blocked_reasons entry
      * ``CORPUS_ELIGIBILITY_EVIDENCE_ONLY`` — synonym for blocked, used
        when the apparatus wants to emphasize that the trace IS valid
        evidence — just not training data.

    ``training_eligible`` is False on every decision produced by this
    rung. A future rung may admit traces; until then, eligibility is
    purely a policy declaration.
    """

    decision: str
    blocked_reasons: tuple[str, ...]
    trace_id: str
    workspace: str
    training_eligible: bool = False
    evidence_recorded: bool = True
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["blocked_reasons"] = list(self.blocked_reasons)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_blocked(self) -> bool:
        return self.decision in (
            "CORPUS_ELIGIBILITY_BLOCKED",
            "CORPUS_ELIGIBILITY_EVIDENCE_ONLY",
        )
