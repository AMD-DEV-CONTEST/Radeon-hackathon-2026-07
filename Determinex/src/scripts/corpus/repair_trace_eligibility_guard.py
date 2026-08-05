"""Corpus eligibility guard for repair traces.

Pure decision function. Given a :class:`VerifiedRepairTrace` and an
optional :class:`ApprovalGateDecision`, returns a structured
:class:`CorpusEligibilityDecision` enumerating every reason the trace
is NOT admissible as a training corpus row.

At this rung, every trace is BLOCKED. The decision still carries a
specific reason list so a future rung (live model admission + live
operator approval) can attack the reasons one by one and admit only
traces that defeat all of them.

The guard performs no I/O. It does not write to the corpus.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from repair.human_approval_record import ApprovalGateDecision  # noqa: E402
from repair.verified_repair_trace_record import VerifiedRepairTrace  # noqa: E402

from .repair_trace_eligibility_record import (
    CORPUS_ELIGIBILITY_STATUS_TOKENS,
    CorpusEligibilityBlockReason,
    CorpusEligibilityDecision,
)


class RepairTraceEligibilityGuard:
    """Stateless guard. Same inputs → same decision."""

    # Policy flags. The current campaign keeps all four conservative.
    # Future rungs may flip individual ones (e.g. flip
    # ``mocked_outputs_are_corpus_eligible`` to True once a live model
    # admission policy is in place).
    DEFAULT_POLICY: dict[str, bool] = {
        "mocked_outputs_are_corpus_eligible": False,
        "temp_only_patches_are_corpus_eligible": False,
        "unapproved_source_traces_are_corpus_eligible": False,
        "failed_verifier_traces_are_corpus_eligible": False,
        "unsupported_repo_traces_are_corpus_eligible": False,
        "no_live_model_traces_are_corpus_eligible": False,
        "policy_default_allow": False,
    }

    def __init__(self, policy: dict[str, bool] | None = None) -> None:
        self._policy = {**self.DEFAULT_POLICY, **(policy or {})}

    @property
    def policy(self) -> dict[str, bool]:
        return dict(self._policy)

    def evaluate(
        self,
        trace: VerifiedRepairTrace,
        approval: ApprovalGateDecision | None = None,
    ) -> CorpusEligibilityDecision:
        reasons: list[str] = []
        notes: list[str] = []
        spr = trace.safe_patch_result or {}

        # UNSUPPORTED_REPO short-circuit.
        if trace.final_status == "TRACE_BLOCKED_UNSUPPORTED_REPO":
            if not self._policy["unsupported_repo_traces_are_corpus_eligible"]:
                reasons.append(CorpusEligibilityBlockReason.UNSUPPORTED_REPO.value)

        # MOCKED_MODEL_OUTPUT — the current pipeline routes through a mock.
        if not self._policy["mocked_outputs_are_corpus_eligible"]:
            reasons.append(CorpusEligibilityBlockReason.MOCKED_MODEL_OUTPUT.value)
        # NO_LIVE_MODEL_CALL — same root cause, separate dimension so the
        # future rung can satisfy them independently.
        if not self._policy["no_live_model_traces_are_corpus_eligible"]:
            reasons.append(CorpusEligibilityBlockReason.NO_LIVE_MODEL_CALL.value)

        # TEMP_WORKSPACE_ONLY — patch only ever applied to a temp copy.
        if not self._policy["temp_only_patches_are_corpus_eligible"]:
            reasons.append(CorpusEligibilityBlockReason.TEMP_WORKSPACE_ONLY.value)

        # VERIFIER_FAILED — only fires if the trace's safe-patch verifier
        # actually rejected.
        if spr.get("verifier_status") == "PATCH_VERIFIER_FAILED":
            if not self._policy["failed_verifier_traces_are_corpus_eligible"]:
                reasons.append(CorpusEligibilityBlockReason.VERIFIER_FAILED.value)

        # SOURCE_NOT_APPROVED — fires unless an ACCEPTED ApprovalGateDecision
        # was supplied. (Fixture acceptance still counts toward "approved"
        # in this policy, but a live policy in the future would distinguish.)
        if approval is None or not approval.is_accepted:
            if not self._policy["unapproved_source_traces_are_corpus_eligible"]:
                reasons.append(CorpusEligibilityBlockReason.SOURCE_NOT_APPROVED.value)

        # HUMAN_APPROVAL_REQUIRED — fires when *no* approval has been
        # generated yet (approval is None or REQUIRED).
        if approval is None or approval.decision == "SOURCE_MUTATION_APPROVAL_REQUIRED":
            reasons.append(CorpusEligibilityBlockReason.HUMAN_APPROVAL_REQUIRED.value)

        # Policy default — always present at this rung; a future rung
        # may flip ``policy_default_allow`` to True.
        if not self._policy["policy_default_allow"]:
            reasons.append(CorpusEligibilityBlockReason.POLICY.value)
            notes.append(
                "Default policy blocks corpus admission for every trace "
                "produced by the current campaign. This is intentional."
            )

        # Deduplicate while preserving order.
        seen: set[str] = set()
        deduped: list[str] = []
        for r in reasons:
            if r not in seen:
                deduped.append(r)
                seen.add(r)

        if not deduped:
            # Impossible at this rung, but kept for symmetry. If a future
            # rung clears every blocked reason, eligibility is opened.
            return CorpusEligibilityDecision(
                decision="CORPUS_ELIGIBILITY_EVIDENCE_ONLY",
                blocked_reasons=(),
                trace_id=trace.trace_id,
                workspace=trace.workspace,
                training_eligible=False,
                evidence_recorded=True,
                notes=(
                    "All policy flags allow; eligibility still requires a "
                    "future rung's positive admission step.",
                ),
            )

        return CorpusEligibilityDecision(
            decision="CORPUS_ELIGIBILITY_BLOCKED",
            blocked_reasons=tuple(deduped),
            trace_id=trace.trace_id,
            workspace=trace.workspace,
            training_eligible=False,
            evidence_recorded=True,
            notes=tuple(notes),
        )


__all__ = [
    "RepairTraceEligibilityGuard",
    "CorpusEligibilityDecision",
    "CorpusEligibilityBlockReason",
    "CORPUS_ELIGIBILITY_STATUS_TOKENS",
]
