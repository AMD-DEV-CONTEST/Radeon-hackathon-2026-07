from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.experience_asset.application import DurableFakeAgentLoop
from app.experience_asset.domain.enums import (
    PolicyOutcome,
    RetrievalScope,
    TerminalState,
    ToolExecutionStatus,
)
from app.experience_asset.domain.models import PolicyDecision, RuntimeToolCallProposal
from app.experience_asset.inference import (
    FakeModelClient,
    LocalVLLMClient,
    StructuredProposal,
)
from app.experience_asset.inference.models import (
    InvalidModelOutput,
    ModelTimedOut,
    ModelUnavailable,
    ToolCallProposal,
)
from app.experience_asset.persistence import SQLiteAssetRepository
from app.experience_asset.policy import RuntimePolicy
from app.experience_asset.retrieval import FakeScopedRetrievalRepository
from app.experience_asset.tools import FakeToolExecutor


def build_loop(repository, asset, *, allow_tool: bool):
    proposal = StructuredProposal(
        summary="Propose bounded current-source grounding.",
        tool_call_proposals=[
            ToolCallProposal(
                name="search_current_experience",
                arguments={
                    "asset_id": str(asset.asset_id),
                    "current_version_id": str(asset.version_id),
                    "scope": "CURRENT_SOURCE",
                    "query": "synthetic current-source evidence",
                    "top_k": 3,
                },
            )
        ],
    )
    loop = DurableFakeAgentLoop(
        repository=repository,
        model_client=FakeModelClient(proposal),
        runtime_policy=RuntimePolicy(),
        tool_executor=FakeToolExecutor(FakeScopedRetrievalRepository()),
    )
    return asyncio.run(
        loop.run_current_source_smoke(
            asset=asset,
            user_goal="Prove the durable E1-A2 lifecycle.",
            allow_tool=allow_tool,
        )
    )


def test_fake_loop_persists_complete_lifecycle_and_resumes(
    tmp_path,
    public_ready_asset,
) -> None:
    database = tmp_path / "asset.sqlite3"
    repository = SQLiteAssetRepository(database)
    repository.initialize()
    repository.create(public_ready_asset)
    state = build_loop(repository, public_ready_asset, allow_tool=True)

    assert state.terminal_state is TerminalState.SUCCEEDED
    assert state.policy_decisions[0].outcome is PolicyOutcome.ALLOW
    assert state.tool_executions[0].status is ToolExecutionStatus.SUCCEEDED
    assert state.verification_report is not None
    assert repository.list_run_checkpoint_phases(state.run_id) == [
        "PLANNED",
        "PROPOSED",
        "POLICY_DECIDED",
        "TOOL_RECORDED",
        "VERIFIED_TERMINAL",
    ]

    restarted = SQLiteAssetRepository(database)
    restarted.initialize()
    assert restarted.get_latest_run_checkpoint(state.run_id) == state
    assert restarted.get_current(public_ready_asset.asset_id) == public_ready_asset


def test_policy_denial_is_visible_terminal_and_has_no_tool_effect(
    tmp_path,
    public_ready_asset,
) -> None:
    repository = SQLiteAssetRepository(tmp_path / "asset.sqlite3")
    repository.initialize()
    repository.create(public_ready_asset)
    state = build_loop(repository, public_ready_asset, allow_tool=False)

    assert state.terminal_state is TerminalState.POLICY_BLOCKED
    assert state.policy_decisions[0].outcome is PolicyOutcome.DENY
    assert "PERMISSION_NOT_GRANTED" in state.policy_decisions[0].reason_codes
    assert state.tool_executions[0].status is ToolExecutionStatus.DENIED
    assert state.tool_executions[0].observation_refs == []
    assert state.verification_report is not None
    assert "VISIBLE_POLICY_DENIAL" in state.verification_report.finding_codes


@pytest.mark.parametrize(
    ("error", "expected_terminal", "expected_finding"),
    [
        (
            ModelUnavailable("synthetic unavailable"),
            TerminalState.MODEL_UNAVAILABLE,
            "LOCAL_MODEL_UNAVAILABLE",
        ),
        (
            ModelTimedOut("synthetic timeout"),
            TerminalState.TIMED_OUT,
            "LOCAL_MODEL_TIMED_OUT",
        ),
        (
            InvalidModelOutput("synthetic invalid output"),
            TerminalState.INVALID_MODEL_OUTPUT,
            "INVALID_LOCAL_MODEL_OUTPUT",
        ),
    ],
)
def test_model_failures_become_durable_terminal_results_after_restart(
    tmp_path,
    public_ready_asset,
    error,
    expected_terminal,
    expected_finding,
) -> None:
    class FailingModelClient:
        model_id = "synthetic-failing-local-model"
        base_url = "http://127.0.0.1:8000"

        async def generate(self, request):
            raise error

    database = tmp_path / f"{expected_terminal.value.lower()}.sqlite3"
    repository = SQLiteAssetRepository(database)
    repository.initialize()
    repository.create(public_ready_asset)
    loop = DurableFakeAgentLoop(
        repository=repository,
        model_client=FailingModelClient(),
        runtime_policy=RuntimePolicy(),
        tool_executor=FakeToolExecutor(FakeScopedRetrievalRepository()),
    )

    state = asyncio.run(
        loop.run_current_source_smoke(
            asset=public_ready_asset,
            user_goal="Prove local-model failures terminate durably.",
        )
    )

    assert state.terminal_state is expected_terminal
    assert state.model_calls_used == 1
    assert state.tool_proposals == []
    assert state.tool_executions == []
    assert state.verification_report is not None
    assert expected_finding in state.verification_report.finding_codes
    assert repository.list_run_checkpoint_phases(state.run_id) == [
        "PLANNED",
        "MODEL_FAILURE_TERMINAL",
    ]

    restarted = SQLiteAssetRepository(database)
    restarted.initialize()
    assert restarted.get_latest_run_checkpoint(state.run_id) == state
    terminal_result = restarted.get_terminal_result(state.run_id)
    assert terminal_result is not None
    assert terminal_result.state is expected_terminal
    assert terminal_result.last_durable_version_id == public_ready_asset.version_id
    assert terminal_result.retryable is True
    assert terminal_result.internal_error_class == type(error).__name__
    assert terminal_result.model_call_count == 1
    assert restarted.get_current(public_ready_asset.asset_id) == public_ready_asset


def test_missing_required_tool_call_is_durable_invalid_output(
    tmp_path,
    public_ready_asset,
) -> None:
    database = tmp_path / "missing-tool.sqlite3"
    repository = SQLiteAssetRepository(database)
    repository.initialize()
    repository.create(public_ready_asset)
    loop = DurableFakeAgentLoop(
        repository=repository,
        model_client=FakeModelClient(
            StructuredProposal(
                summary="Synthetic proposal without the required tool call.",
            )
        ),
        runtime_policy=RuntimePolicy(),
        tool_executor=FakeToolExecutor(FakeScopedRetrievalRepository()),
    )

    state = asyncio.run(
        loop.run_current_source_smoke(
            asset=public_ready_asset,
            user_goal="Prove a missing tool proposal terminates durably.",
        )
    )

    assert state.terminal_state is TerminalState.INVALID_MODEL_OUTPUT
    assert state.verification_report is not None
    assert (
        "INVALID_LOCAL_MODEL_OUTPUT"
        in state.verification_report.finding_codes
    )
    restarted = SQLiteAssetRepository(database)
    restarted.initialize()
    assert restarted.get_latest_run_checkpoint(state.run_id) == state
    terminal_result = restarted.get_terminal_result(state.run_id)
    assert terminal_result is not None
    assert terminal_result.state is TerminalState.INVALID_MODEL_OUTPUT
    assert terminal_result.internal_error_class == "MissingRequiredToolCall"
    assert restarted.get_current(public_ready_asset.asset_id) == public_ready_asset


def test_malformed_vllm_shape_becomes_durable_invalid_output_after_restart(
    tmp_path,
    public_ready_asset,
) -> None:
    class MalformedVLLMResponseClient(LocalVLLMClient):
        async def generate(self, request):
            return self.parse_response(
                {"choices": [{"message": []}]},
                elapsed_ms=1,
            )

    database = tmp_path / "malformed-vllm-shape.sqlite3"
    repository = SQLiteAssetRepository(database)
    repository.initialize()
    repository.create(public_ready_asset)
    loop = DurableFakeAgentLoop(
        repository=repository,
        model_client=MalformedVLLMResponseClient(
            base_url="http://127.0.0.1:8000/v1",
            model_id="Qwen/Qwen2.5-14B-Instruct",
        ),
        runtime_policy=RuntimePolicy(),
        tool_executor=FakeToolExecutor(FakeScopedRetrievalRepository()),
    )

    state = asyncio.run(
        loop.run_current_source_smoke(
            asset=public_ready_asset,
            user_goal="Prove malformed vLLM response shapes terminate durably.",
        )
    )

    assert state.terminal_state is TerminalState.INVALID_MODEL_OUTPUT
    assert repository.list_run_checkpoint_phases(state.run_id) == [
        "PLANNED",
        "MODEL_FAILURE_TERMINAL",
    ]
    restarted = SQLiteAssetRepository(database)
    restarted.initialize()
    assert restarted.get_latest_run_checkpoint(state.run_id) == state
    terminal_result = restarted.get_terminal_result(state.run_id)
    assert terminal_result is not None
    assert terminal_result.state is TerminalState.INVALID_MODEL_OUTPUT
    assert terminal_result.internal_error_class == "InvalidModelOutput"
    assert restarted.get_current(public_ready_asset.asset_id) == public_ready_asset


def test_cross_asset_search_is_denied_before_knowledge_card_readiness(
    tmp_path,
    public_ready_asset,
) -> None:
    repository = SQLiteAssetRepository(tmp_path / "asset.sqlite3")
    repository.initialize()
    repository.create(public_ready_asset)
    state = build_loop(repository, public_ready_asset, allow_tool=True)
    state = state.model_copy(
        update={
            "permission_snapshot": {
                "tool:discover_related_experience_candidates": True,
            },
            "knowledge_card_version_id": None,
            "knowledge_card_hash": None,
        }
    )
    proposal = RuntimeToolCallProposal(
        proposal_id=uuid4(),
        name="discover_related_experience_candidates",
        arguments={
            "asset_id": str(public_ready_asset.asset_id),
            "current_version_id": str(public_ready_asset.version_id),
            "knowledge_card_version_id": str(public_ready_asset.version_id),
            "knowledge_card_hash": "a" * 64,
            "scope": "CROSS_ASSET_SUMMARY",
            "discovery_intent_version": "e5-discovery-intent/v1",
        },
        base_version_id=public_ready_asset.version_id,
        knowledge_card_version_id=public_ready_asset.version_id,
        knowledge_card_hash="a" * 64,
        proposed_at=datetime.now(UTC),
    )
    decision = RuntimePolicy().evaluate(state=state, proposal=proposal)
    assert decision.outcome is PolicyOutcome.DENY
    assert "KNOWLEDGE_CARD_NOT_READY" in decision.reason_codes


def test_cross_asset_detail_is_denied_without_confirmed_related_asset(
    tmp_path,
    public_ready_asset,
) -> None:
    repository = SQLiteAssetRepository(tmp_path / "asset.sqlite3")
    repository.initialize()
    repository.create(public_ready_asset)
    state = build_loop(repository, public_ready_asset, allow_tool=True)
    related_asset_id = uuid4()
    state = state.model_copy(
        update={
            "permission_snapshot": {
                "tool:read_confirmed_related_evidence": True,
            },
            "retrieval_scope": RetrievalScope.CROSS_ASSET_DETAIL,
            "knowledge_card_version_id": public_ready_asset.version_id,
            "knowledge_card_hash": "a" * 64,
            "relation_candidate_ids": [state.confirmed_relation_ids[0]]
            if state.confirmed_relation_ids
            else [],
            "confirmed_relation_ids": [uuid4()],
            "confirmed_related_asset_ids": [],
        }
    )
    proposal = RuntimeToolCallProposal(
        proposal_id=uuid4(),
        name="read_confirmed_related_evidence",
        arguments={
            "asset_id": str(public_ready_asset.asset_id),
            "current_version_id": str(public_ready_asset.version_id),
            "knowledge_card_version_id": str(public_ready_asset.version_id),
            "knowledge_card_hash": "a" * 64,
            "scope": "CROSS_ASSET_DETAIL",
            "relation_bindings": [
                {
                    "relation_id": str(state.confirmed_relation_ids[0]),
                    "related_asset_id": str(related_asset_id),
                }
            ],
        },
        base_version_id=public_ready_asset.version_id,
        knowledge_card_version_id=public_ready_asset.version_id,
        knowledge_card_hash="a" * 64,
        proposed_at=datetime.now(UTC),
    )
    decision = RuntimePolicy().evaluate(state=state, proposal=proposal)
    assert decision.outcome is PolicyOutcome.DENY
    assert "RELATION_ASSET_BINDING_NOT_CONFIRMED" in decision.reason_codes


def test_invalid_tool_arguments_fail_closed(tmp_path, public_ready_asset) -> None:
    repository = SQLiteAssetRepository(tmp_path / "asset.sqlite3")
    repository.initialize()
    repository.create(public_ready_asset)
    state = build_loop(repository, public_ready_asset, allow_tool=True)
    proposal = RuntimeToolCallProposal(
        proposal_id=uuid4(),
        name="search_current_experience",
        arguments={
            "asset_id": str(public_ready_asset.asset_id),
            "current_version_id": str(public_ready_asset.version_id),
            "scope": "CURRENT_SOURCE",
            "query": "",
            "top_k": 100,
        },
        base_version_id=public_ready_asset.version_id,
        proposed_at=datetime.now(UTC),
    )
    decision = RuntimePolicy().evaluate(state=state, proposal=proposal)
    assert decision.outcome is PolicyOutcome.DENY
    assert {"INVALID_QUERY", "INVALID_TOP_K"}.issubset(decision.reason_codes)


def test_malformed_forced_allow_becomes_durable_terminal_failure(
    tmp_path,
    public_ready_asset,
) -> None:
    class ForcedAllowPolicy:
        def evaluate(self, *, state, proposal):
            return PolicyDecision(
                decision_id=uuid4(),
                run_id=state.run_id,
                proposal_id=proposal.proposal_id,
                outcome=PolicyOutcome.ALLOW,
                reason_codes=["FORCED_ALLOW_TEST_ONLY"],
                policy_version="forced-allow-negative-test",
                decided_at=datetime.now(UTC),
            )

    database = tmp_path / "forced-allow.sqlite3"
    repository = SQLiteAssetRepository(database)
    repository.initialize()
    repository.create(public_ready_asset)
    malformed = StructuredProposal(
        summary="Synthetic malformed executable proposal.",
        tool_call_proposals=[
            ToolCallProposal(
                name="search_current_experience",
                arguments={
                    "asset_id": str(public_ready_asset.asset_id),
                    "current_version_id": str(public_ready_asset.version_id),
                    "scope": "NOT_A_SCOPE",
                    "query": "synthetic malformed request",
                    "top_k": 3,
                },
            )
        ],
    )
    loop = DurableFakeAgentLoop(
        repository=repository,
        model_client=FakeModelClient(malformed),
        runtime_policy=ForcedAllowPolicy(),
        tool_executor=FakeToolExecutor(FakeScopedRetrievalRepository()),
    )
    state = asyncio.run(
        loop.run_current_source_smoke(
            asset=public_ready_asset,
            user_goal="Prove malformed forced ALLOW fails durably.",
            allow_tool=True,
        )
    )

    assert state.policy_decisions[0].outcome is PolicyOutcome.ALLOW
    assert state.tool_executions[0].status is ToolExecutionStatus.FAILED
    assert state.tool_executions[0].error_class == "InvalidToolArgumentsAtExecution"
    assert state.terminal_state is TerminalState.INTERNAL_ERROR
    assert state.verification_report is not None
    assert (
        "VISIBLE_TOOL_EXECUTION_FAILURE"
        in state.verification_report.finding_codes
    )
    restarted = SQLiteAssetRepository(database)
    restarted.initialize()
    assert restarted.get_latest_run_checkpoint(state.run_id) == state
