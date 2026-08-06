from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.experience_asset.application import DurableFakeAgentLoop
from app.experience_asset.domain.enums import (
    PolicyOutcome,
    RetrievalScope,
    ToolExecutionStatus,
)
from app.experience_asset.domain.models import (
    AgentRunStateV1,
    ConfirmedRelationBinding,
    ExperienceAssetV1,
    RuntimeToolCallProposal,
)
from app.experience_asset.inference import FakeModelClient, StructuredProposal
from app.experience_asset.inference.models import ToolCallProposal
from app.experience_asset.persistence import SQLiteAssetRepository
from app.experience_asset.policy import MODEL_VISIBLE_TOOLS, RuntimePolicy
from app.experience_asset.retrieval import FakeScopedRetrievalRepository
from app.experience_asset.tools import FakeToolExecutor


def _proposal(
    *,
    state: AgentRunStateV1,
    name: str,
    arguments: dict,
    bind_card: bool = False,
) -> RuntimeToolCallProposal:
    return RuntimeToolCallProposal(
        proposal_id=uuid4(),
        name=name,
        arguments=arguments,
        base_version_id=state.base_version_id,
        knowledge_card_version_id=(
            state.knowledge_card_version_id if bind_card else None
        ),
        knowledge_card_hash=state.knowledge_card_hash if bind_card else None,
        proposed_at=datetime.now(UTC),
    )


def _card_ready_state(state: AgentRunStateV1) -> AgentRunStateV1:
    return state.model_copy(
        update={
            "knowledge_card_version_id": state.base_version_id,
            "knowledge_card_hash": "a" * 64,
        }
    )


def _valid_arguments(state: AgentRunStateV1, name: str) -> dict:
    common = {
        "asset_id": str(state.asset_id),
        "current_version_id": str(state.base_version_id),
    }
    if name == "search_current_experience":
        return {
            **common,
            "scope": "CURRENT_SOURCE",
            "query": "current evidence",
            "top_k": 3,
        }
    if name == "discover_related_experience_candidates":
        return {
            **common,
            "knowledge_card_version_id": str(state.knowledge_card_version_id),
            "knowledge_card_hash": state.knowledge_card_hash,
            "scope": "CROSS_ASSET_SUMMARY",
            "discovery_intent_version": "e5-discovery-intent/v1",
            "top_k": 3,
        }
    if name == "read_confirmed_related_evidence":
        return {
            **common,
            "knowledge_card_version_id": str(state.knowledge_card_version_id),
            "knowledge_card_hash": state.knowledge_card_hash,
            "scope": "CROSS_ASSET_DETAIL",
            "relation_bindings": [
                {
                    "relation_id": str(
                        state.confirmed_relation_bindings[0].relation_id
                    ),
                    "related_asset_id": str(
                        state.confirmed_relation_bindings[0].related_asset_id
                    ),
                }
            ],
            "top_k": 3,
        }
    if name == "read_source_spans":
        return {**common, "source_ids": [str(uuid4())], "max_spans": 5}
    if name == "inspect_evidence_gaps":
        return {**common, "milestone": "M1", "statement_ids": []}
    if name == "evaluate_route_readiness":
        return {**common, "routes": ["PRIVATE_SELF"]}
    if name == "render_private_preview":
        return {
            **common,
            "route_draft_id": str(uuid4()),
            "route_draft_hash": "b" * 64,
        }
    raise AssertionError(name)


@pytest.fixture
def runtime_state(tmp_path, public_ready_asset: ExperienceAssetV1) -> AgentRunStateV1:
    repository = SQLiteAssetRepository(tmp_path / "runtime-policy.sqlite3")
    repository.initialize()
    repository.create(public_ready_asset)
    model_proposal = StructuredProposal(
        summary="Propose bounded current-source grounding.",
        tool_call_proposals=[
            ToolCallProposal(
                name="search_current_experience",
                arguments={
                    "asset_id": str(public_ready_asset.asset_id),
                    "current_version_id": str(public_ready_asset.version_id),
                    "scope": "CURRENT_SOURCE",
                    "query": "synthetic current-source evidence",
                    "top_k": 3,
                },
            )
        ],
    )
    loop = DurableFakeAgentLoop(
        repository=repository,
        model_client=FakeModelClient(model_proposal),
        runtime_policy=RuntimePolicy(),
        tool_executor=FakeToolExecutor(FakeScopedRetrievalRepository()),
    )
    fake_agent_state = asyncio.run(
        loop.run_current_source_smoke(
            asset=public_ready_asset,
            user_goal="Build a bounded Runtime policy fixture.",
        )
    )
    relation_id = uuid4()
    related_asset_id = uuid4()
    return _card_ready_state(fake_agent_state).model_copy(
        update={
            "relation_candidate_ids": [relation_id],
            "confirmed_relation_ids": [relation_id],
            "confirmed_related_asset_ids": [related_asset_id],
            "confirmed_relation_bindings": [
                ConfirmedRelationBinding(
                    relation_id=relation_id,
                    related_asset_id=related_asset_id,
                )
            ],
        }
    )


@pytest.mark.parametrize(
    "name",
    [
        "search_current_experience",
        "discover_related_experience_candidates",
        "read_confirmed_related_evidence",
    ],
)
def test_each_e1_a_dispatcher_has_allow_deny_and_invalid_argument_paths(
    runtime_state: AgentRunStateV1,
    name: str,
) -> None:
    needs_card = name != "search_current_experience"
    arguments = _valid_arguments(runtime_state, name)
    proposal = _proposal(
        state=runtime_state,
        name=name,
        arguments=arguments,
        bind_card=needs_card,
    )
    allowed_state = runtime_state.model_copy(
        update={
            "permission_snapshot": {f"tool:{name}": True},
            "retrieval_scope": {
                "search_current_experience": RetrievalScope.CURRENT_SOURCE,
                "discover_related_experience_candidates": (
                    RetrievalScope.CROSS_ASSET_SUMMARY
                ),
                "read_confirmed_related_evidence": (
                    RetrievalScope.CROSS_ASSET_DETAIL
                ),
            }[name],
        }
    )
    allowed = RuntimePolicy().evaluate(state=allowed_state, proposal=proposal)
    assert allowed.outcome is PolicyOutcome.ALLOW
    execution = FakeToolExecutor(FakeScopedRetrievalRepository()).execute(
        state=allowed_state,
        proposal=proposal,
        decision=allowed,
    )
    assert execution.status is ToolExecutionStatus.SUCCEEDED

    denied_state = runtime_state.model_copy(update={"permission_snapshot": {}})
    denied = RuntimePolicy().evaluate(state=denied_state, proposal=proposal)
    assert denied.outcome is PolicyOutcome.DENY
    assert "PERMISSION_NOT_GRANTED" in denied.reason_codes

    invalid_arguments = dict(arguments)
    invalid_arguments.pop("current_version_id")
    invalid = RuntimePolicy().evaluate(
        state=allowed_state,
        proposal=_proposal(
            state=runtime_state,
            name=name,
            arguments=invalid_arguments,
            bind_card=needs_card,
        ),
    )
    assert invalid.outcome is PolicyOutcome.DENY
    assert "INVALID_TOOL_ARGUMENTS" in invalid.reason_codes


@pytest.mark.parametrize(
    "name",
    sorted(
        MODEL_VISIBLE_TOOLS
        - {
            "search_current_experience",
            "discover_related_experience_candidates",
            "read_confirmed_related_evidence",
        }
    ),
)
def test_deferred_model_visible_tools_fail_closed_without_dispatch(
    runtime_state: AgentRunStateV1,
    name: str,
) -> None:
    state = runtime_state.model_copy(
        update={"permission_snapshot": {f"tool:{name}": True}}
    )
    proposal = _proposal(
        state=state,
        name=name,
        arguments=_valid_arguments(state, name),
    )
    decision = RuntimePolicy().evaluate(state=state, proposal=proposal)
    assert decision.outcome is PolicyOutcome.DENY
    assert "TOOL_NOT_EXECUTABLE_IN_E1_A" in decision.reason_codes
    execution = FakeToolExecutor(FakeScopedRetrievalRepository()).execute(
        state=state,
        proposal=proposal,
        decision=decision,
    )
    assert execution.status is ToolExecutionStatus.DENIED

    invalid = RuntimePolicy().evaluate(
        state=state,
        proposal=_proposal(state=state, name=name, arguments={}),
    )
    assert invalid.outcome is PolicyOutcome.DENY
    assert "INVALID_TOOL_ARGUMENTS" in invalid.reason_codes


def test_stale_knowledge_card_and_proposal_bindings_are_denied(
    runtime_state: AgentRunStateV1,
) -> None:
    name = "discover_related_experience_candidates"
    stale_card_version = uuid4()
    stale_state = runtime_state.model_copy(
        update={
            "permission_snapshot": {f"tool:{name}": True},
            "knowledge_card_version_id": stale_card_version,
        }
    )
    stale_arguments = _valid_arguments(stale_state, name)
    stale_proposal = _proposal(
        state=stale_state,
        name=name,
        arguments=stale_arguments,
        bind_card=True,
    )
    stale = RuntimePolicy().evaluate(state=stale_state, proposal=stale_proposal)
    assert stale.outcome is PolicyOutcome.DENY
    assert "STALE_KNOWLEDGE_CARD" in stale.reason_codes

    current_state = runtime_state.model_copy(
        update={"permission_snapshot": {f"tool:{name}": True}}
    )
    mismatched = RuntimeToolCallProposal(
        proposal_id=uuid4(),
        name=name,
        arguments=_valid_arguments(current_state, name),
        base_version_id=current_state.base_version_id,
        knowledge_card_version_id=uuid4(),
        knowledge_card_hash="f" * 64,
        proposed_at=datetime.now(UTC),
    )
    decision = RuntimePolicy().evaluate(state=current_state, proposal=mismatched)
    assert decision.outcome is PolicyOutcome.DENY
    assert "PROPOSAL_KNOWLEDGE_CARD_BINDING_MISMATCH" in decision.reason_codes


def test_new_base_version_requires_readiness_and_relations_to_be_invalidated(
    runtime_state: AgentRunStateV1,
) -> None:
    payload = runtime_state.model_dump(mode="python")
    payload["base_version_id"] = uuid4()
    with pytest.raises(ValidationError, match="readiness is stale"):
        AgentRunStateV1.model_validate(payload)

    payload["knowledge_card_version_id"] = None
    payload["knowledge_card_hash"] = None
    with pytest.raises(
        ValidationError,
        match="relation candidates and confirmations require current card readiness",
    ):
        AgentRunStateV1.model_validate(payload)

    payload["relation_candidate_ids"] = []
    payload["confirmed_relation_ids"] = []
    payload["confirmed_related_asset_ids"] = []
    payload["confirmed_relation_bindings"] = []
    invalidated = AgentRunStateV1.model_validate(payload)
    assert invalidated.knowledge_card_version_id is None
    assert invalidated.relation_candidate_ids == []
    assert invalidated.confirmed_relation_ids == []
    assert invalidated.confirmed_related_asset_ids == []
    assert invalidated.confirmed_relation_bindings == []


def test_detail_requires_exact_relation_asset_pair_and_matching_run_scope(
    runtime_state: AgentRunStateV1,
) -> None:
    second_relation = uuid4()
    second_asset = uuid4()
    first_binding = runtime_state.confirmed_relation_bindings[0]
    state = runtime_state.model_copy(
        update={
            "permission_snapshot": {
                "tool:read_confirmed_related_evidence": True,
            },
            "retrieval_scope": RetrievalScope.CROSS_ASSET_DETAIL,
            "relation_candidate_ids": [
                first_binding.relation_id,
                second_relation,
            ],
            "confirmed_relation_ids": [
                first_binding.relation_id,
                second_relation,
            ],
            "confirmed_related_asset_ids": [
                first_binding.related_asset_id,
                second_asset,
            ],
            "confirmed_relation_bindings": [
                first_binding,
                ConfirmedRelationBinding(
                    relation_id=second_relation,
                    related_asset_id=second_asset,
                ),
            ],
        }
    )
    arguments = _valid_arguments(state, "read_confirmed_related_evidence")
    arguments["relation_bindings"] = [
        {
            "relation_id": str(first_binding.relation_id),
            "related_asset_id": str(second_asset),
        }
    ]
    proposal = _proposal(
        state=state,
        name="read_confirmed_related_evidence",
        arguments=arguments,
        bind_card=True,
    )
    mismatched_pair = RuntimePolicy().evaluate(state=state, proposal=proposal)
    assert mismatched_pair.outcome is PolicyOutcome.DENY
    assert (
        "RELATION_ASSET_BINDING_NOT_CONFIRMED"
        in mismatched_pair.reason_codes
    )

    wrong_scope = state.model_copy(
        update={"retrieval_scope": RetrievalScope.CURRENT_SOURCE}
    )
    scope_decision = RuntimePolicy().evaluate(
        state=wrong_scope,
        proposal=_proposal(
            state=wrong_scope,
            name="read_confirmed_related_evidence",
            arguments=_valid_arguments(wrong_scope, "read_confirmed_related_evidence"),
            bind_card=True,
        ),
    )
    assert scope_decision.outcome is PolicyOutcome.DENY
    assert "RUN_STATE_RETRIEVAL_SCOPE_MISMATCH" in scope_decision.reason_codes


def test_executor_defensively_fails_closed_for_forged_allow_decision(
    runtime_state: AgentRunStateV1,
) -> None:
    state = runtime_state.model_copy(
        update={"permission_snapshot": {"tool:search_current_experience": True}}
    )
    valid = _proposal(
        state=state,
        name="search_current_experience",
        arguments=_valid_arguments(state, "search_current_experience"),
    )
    forged_allow = RuntimePolicy().evaluate(state=state, proposal=valid)
    assert forged_allow.outcome is PolicyOutcome.ALLOW
    invalid = valid.model_copy(update={"arguments": {}})
    execution = FakeToolExecutor(FakeScopedRetrievalRepository()).execute(
        state=state,
        proposal=invalid,
        decision=forged_allow,
    )
    assert execution.status is ToolExecutionStatus.FAILED
    assert execution.error_class == "InvalidToolArgumentsAtExecution"
