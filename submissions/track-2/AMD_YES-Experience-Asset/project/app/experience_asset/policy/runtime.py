"""Deterministic Runtime policy for model-visible E1 tool proposals."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import ValidationError

from app.experience_asset.domain.enums import PolicyOutcome, RetrievalScope
from app.experience_asset.domain.models import (
    AgentRunStateV1,
    PolicyDecision,
    RuntimeToolCallProposal,
)
from app.experience_asset.tools.contracts import MODEL_VISIBLE_TOOL_CONTRACTS

MODEL_VISIBLE_TOOLS = frozenset(MODEL_VISIBLE_TOOL_CONTRACTS)


def _validation_reason_codes(error: ValidationError) -> set[str]:
    """Return stable public reasons without persisting rejected argument values."""

    reasons = {"INVALID_TOOL_ARGUMENTS"}
    fields = {str(item["loc"][0]) for item in error.errors() if item["loc"]}
    if "asset_id" in fields:
        reasons.add("INVALID_ASSET_ID")
    if "query" in fields:
        reasons.add("INVALID_QUERY")
    if "top_k" in fields:
        reasons.add("INVALID_TOP_K")
    if "scope" in fields:
        reasons.add("INVALID_RETRIEVAL_SCOPE")
    if "relation_bindings" in fields:
        reasons.add("INVALID_RELATION_BINDINGS")
    return reasons


class RuntimePolicy:
    version = "runtime-policy-v2"

    def evaluate(
        self,
        *,
        state: AgentRunStateV1,
        proposal: RuntimeToolCallProposal,
    ) -> PolicyDecision:
        reasons: set[str] = set()
        contract = MODEL_VISIBLE_TOOL_CONTRACTS.get(proposal.name)
        if contract is None:
            reasons.add("TOOL_NOT_ALLOWLISTED")
            parsed = None
        else:
            if not contract.executable_in_e1_a:
                reasons.add("TOOL_NOT_EXECUTABLE_IN_E1_A")
            try:
                parsed = contract.arguments_model.model_validate(proposal.arguments)
            except ValidationError as error:
                parsed = None
                reasons.update(_validation_reason_codes(error))

        if not state.permission_snapshot.get(f"tool:{proposal.name}", False):
            reasons.add("PERMISSION_NOT_GRANTED")

        if proposal.base_version_id != state.base_version_id:
            reasons.add("STALE_PROPOSAL_BASE_VERSION")

        if parsed is not None:
            if parsed.asset_id != state.asset_id:
                reasons.add("CURRENT_ASSET_SCOPE_MISMATCH")
            if parsed.current_version_id != state.base_version_id:
                reasons.add("CURRENT_VERSION_SCOPE_MISMATCH")
            parsed_scope = getattr(parsed, "scope", None)
            if parsed_scope is not None and state.retrieval_scope is not RetrievalScope(
                parsed_scope
            ):
                reasons.add("RUN_STATE_RETRIEVAL_SCOPE_MISMATCH")

        if proposal.name in {
            "discover_related_experience_candidates",
            "read_confirmed_related_evidence",
        }:
            self._evaluate_cross_asset_binding(
                state=state,
                proposal=proposal,
                parsed=parsed,
                reasons=reasons,
            )

        if proposal.name == "read_confirmed_related_evidence" and parsed is not None:
            # A confirmed relation has its own identifier and names the candidate
            # it came from, so the staleness check runs over source candidates
            # rather than relation IDs. Comparing relation IDs against candidate
            # IDs would reject every valid confirmation, since the two are
            # distinct identifier spaces.
            if not set(state.confirmed_relation_source_candidate_ids).issubset(
                set(state.relation_candidate_ids)
            ):
                reasons.add("STALE_RELATION_CONFIRMATION")
            requested_bindings = {
                (binding.relation_id, binding.related_asset_id)
                for binding in parsed.relation_bindings
            }
            confirmed_bindings = {
                (binding.relation_id, binding.related_asset_id)
                for binding in state.confirmed_relation_bindings
            }
            if not requested_bindings.issubset(confirmed_bindings):
                reasons.add("RELATION_ASSET_BINDING_NOT_CONFIRMED")

        outcome = PolicyOutcome.DENY if reasons else PolicyOutcome.ALLOW
        return PolicyDecision(
            decision_id=uuid4(),
            run_id=state.run_id,
            proposal_id=proposal.proposal_id,
            outcome=outcome,
            reason_codes=sorted(reasons) if reasons else ["ALLOWLIST_AND_SCOPE_VALID"],
            policy_version=self.version,
            decided_at=datetime.now(UTC),
        )

    @staticmethod
    def _evaluate_cross_asset_binding(
        *,
        state: AgentRunStateV1,
        proposal: RuntimeToolCallProposal,
        parsed: object | None,
        reasons: set[str],
    ) -> None:
        if (
            state.knowledge_card_version_id is None
            or state.knowledge_card_hash is None
        ):
            reasons.add("KNOWLEDGE_CARD_NOT_READY")
            return
        if state.knowledge_card_version_id != state.base_version_id:
            reasons.add("STALE_KNOWLEDGE_CARD")
        if (
            proposal.knowledge_card_version_id
            != state.knowledge_card_version_id
            or proposal.knowledge_card_hash != state.knowledge_card_hash
        ):
            reasons.add("PROPOSAL_KNOWLEDGE_CARD_BINDING_MISMATCH")
        if parsed is not None and (
            parsed.knowledge_card_version_id
            != state.knowledge_card_version_id
            or parsed.knowledge_card_hash != state.knowledge_card_hash
        ):
            reasons.add("ARGUMENT_KNOWLEDGE_CARD_BINDING_MISMATCH")
