"""Bounded fake execution used to prove proposal/policy/execution separation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import ValidationError

from app.experience_asset.domain.enums import (
    PolicyOutcome,
    RetrievalScope,
    ToolExecutionStatus,
)
from app.experience_asset.domain.models import (
    AgentRunStateV1,
    PolicyDecision,
    RuntimeToolCallProposal,
    ToolExecutionRecord,
)
from app.experience_asset.retrieval import RetrievalRequest, ScopedRetrievalRepository

from .contracts import (
    E1_A_EXECUTABLE_TOOLS,
    ConfirmedRelatedEvidenceArguments,
    CurrentExperienceSearchArguments,
    RelatedCandidateDiscoveryArguments,
)


class BoundedToolExecutor:
    """Execute only Runtime-approved bounded retrieval tools."""

    def __init__(self, retrieval: ScopedRetrievalRepository) -> None:
        self.retrieval = retrieval

    def execute(
        self,
        *,
        state: AgentRunStateV1,
        proposal: RuntimeToolCallProposal,
        decision: PolicyDecision,
    ) -> ToolExecutionRecord:
        started = datetime.now(UTC)
        argument_hash = hashlib.sha256(
            json.dumps(proposal.arguments, sort_keys=True).encode()
        ).hexdigest()
        if decision.outcome is not PolicyOutcome.ALLOW:
            return ToolExecutionRecord(
                execution_id=uuid4(),
                run_id=state.run_id,
                proposal_id=proposal.proposal_id,
                policy_decision_id=decision.decision_id,
                tool_name=proposal.name,
                sanitized_argument_hash=argument_hash,
                status=ToolExecutionStatus.DENIED,
                error_class="PolicyDenied",
                started_at=started,
                finished_at=datetime.now(UTC),
            )
        if proposal.name not in E1_A_EXECUTABLE_TOOLS:
            return ToolExecutionRecord(
                execution_id=uuid4(),
                run_id=state.run_id,
                proposal_id=proposal.proposal_id,
                policy_decision_id=decision.decision_id,
                tool_name=proposal.name,
                sanitized_argument_hash=argument_hash,
                status=ToolExecutionStatus.FAILED,
                error_class="MissingE1AToolDispatcher",
                started_at=started,
                finished_at=datetime.now(UTC),
            )

        try:
            request = self._build_retrieval_request(
                state=state,
                proposal=proposal,
            )
        except (ValidationError, ValueError, AssertionError):
            return ToolExecutionRecord(
                execution_id=uuid4(),
                run_id=state.run_id,
                proposal_id=proposal.proposal_id,
                policy_decision_id=decision.decision_id,
                tool_name=proposal.name,
                sanitized_argument_hash=argument_hash,
                status=ToolExecutionStatus.FAILED,
                error_class="InvalidToolArgumentsAtExecution",
                started_at=started,
                finished_at=datetime.now(UTC),
            )
        result = self.retrieval.search(request)
        refs = [hit.provenance_ref for hit in result.hits]
        if result.no_match:
            refs.append(f"no-match:{request.retrieval_id}")
        return ToolExecutionRecord(
            execution_id=uuid4(),
            run_id=state.run_id,
            proposal_id=proposal.proposal_id,
            policy_decision_id=decision.decision_id,
            tool_name=proposal.name,
            sanitized_argument_hash=argument_hash,
            status=ToolExecutionStatus.SUCCEEDED,
            observation_refs=refs,
            started_at=started,
            finished_at=datetime.now(UTC),
        )

    @staticmethod
    def _build_retrieval_request(
        *,
        state: AgentRunStateV1,
        proposal: RuntimeToolCallProposal,
    ) -> RetrievalRequest:
        query: str | None = None
        discovery_intent_version: str | None = None
        if proposal.name == "search_current_experience":
            arguments = CurrentExperienceSearchArguments.model_validate(
                proposal.arguments
            )
            query = arguments.query
            related_asset_ids = []
        elif proposal.name == "discover_related_experience_candidates":
            arguments = RelatedCandidateDiscoveryArguments.model_validate(
                proposal.arguments
            )
            discovery_intent_version = arguments.discovery_intent_version
            related_asset_ids = []
        elif proposal.name == "read_confirmed_related_evidence":
            arguments = ConfirmedRelatedEvidenceArguments.model_validate(
                proposal.arguments
            )
            related_asset_ids = [
                binding.related_asset_id for binding in arguments.relation_bindings
            ]
        else:
            raise AssertionError("policy allowed a tool without an E1-A dispatcher")

        return RetrievalRequest(
            retrieval_id=uuid4(),
            scope=RetrievalScope(arguments.scope),
            current_asset_id=state.asset_id,
            current_version_id=state.base_version_id,
            query=query,
            discovery_intent_version=discovery_intent_version,
            top_k=arguments.top_k,
            related_asset_ids=related_asset_ids,
        )


class FakeToolExecutor(BoundedToolExecutor):
    """Backward-compatible E1 fixture name for the bounded executor."""
