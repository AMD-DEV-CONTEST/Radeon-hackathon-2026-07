from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.experience_asset.api.main import create_app
from app.experience_asset.application.m2 import M2CriticalMomentService
from app.experience_asset.domain.enums import TerminalState
from app.experience_asset.inference import FakeModelClient
from app.experience_asset.inference.models import M2SemanticRoleProposal
from app.experience_asset.persistence import AssetNotFoundError, SQLiteAssetRepository
from app.experience_asset.workflow import (
    M2_GRAPH_EDGES,
    M2_GRAPH_NODES,
    M2_GRAPH_STATE_ALLOWED_KEYS,
    M2_TOPOLOGY_HASH,
    M2_WORKFLOW_VERSION,
    M2GraphStateV1,
    M2ProductionGraph,
)


def _accepted_m1(client: TestClient, *, source_text: str) -> dict:
    created = client.post(
        "/api/v1/m1/assets",
        json={
            "source_kind": "PASTED_TEXT",
            "display_label": "M2 LangGraph fixture",
            "text": source_text,
            "goal_hint": "复盘关键时刻",
        },
    ).json()
    response = client.post(
        f"/api/v1/m1/assets/{created['asset']['asset_id']}/confirm",
        json={
            "expected_version_id": created["asset"]["version_id"],
            "complete_with_gaps": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _start_m2_context(
    repository: SQLiteAssetRepository,
    graph: M2ProductionGraph,
    *,
    asset_id: UUID,
    base_version_id: UUID,
) -> tuple[UUID, M2GraphStateV1]:
    run_id = uuid4()
    command_id = uuid4()
    model_id, server_base_url, model_config_hash = graph._runtime_identity()
    repository.start_workflow_run(
        run_id=run_id,
        asset_id=asset_id,
        base_version_id=base_version_id,
        command_id=command_id,
        command="E3-M2-restart-test",
        user_goal="Resume M2 without duplicating the canonical write.",
        allow_current_source_search=False,
        workflow_version=M2_WORKFLOW_VERSION,
        topology_hash=M2_TOPOLOGY_HASH,
        model_id=model_id,
        model_config_hash=model_config_hash,
        server_base_url=server_base_url,
        code_commit="UNCOMMITTED",
        started_at=datetime.now(UTC),
    )
    return run_id, M2GraphStateV1(
        run_id=str(run_id),
        asset_id=str(asset_id),
        base_version_id=str(base_version_id),
        command_id=str(command_id),
        node_attempt=0,
    )


def test_m2_api_uses_one_compiled_graph_and_sanitized_checkpoint_trace(
    tmp_path: Path,
) -> None:
    database = tmp_path / "asset.sqlite3"
    workflow_database = database.with_suffix(".workflow.sqlite3")
    private_source = "PRIVATE-M2-SOURCE-MUST-NOT-ENTER-GRAPH-CHECKPOINT 当天改变方案。"
    app = create_app(
        database_path=database,
        model_client=FakeModelClient(),
        code_commit="b" * 40,
    )

    with TestClient(app) as client:
        accepted = _accepted_m1(client, source_text=private_source)
        response = client.post(
            f"/api/v1/m2/assets/{accepted['asset']['asset_id']}",
            json={"expected_m1_version_id": accepted["asset"]["version_id"]},
        )
        assert response.status_code == 201, response.text
        artifact = response.json()["artifact"]
        run_id = UUID(artifact["generated_by_run_id"])
        assert app.state.m2_graph.compile_count == 1
        assert set(app.state.m2_graph.compiled.get_graph().nodes) >= {
            *M2_GRAPH_NODES,
            "__start__",
            "__end__",
        }

    traces = app.state.repository.list_workflow_traces(run_id)
    assert [trace["node_name"] for trace in traces] == list(M2_GRAPH_NODES)
    assert all(trace["workflow_version"] == M2_WORKFLOW_VERSION for trace in traces)
    assert all(trace["topology_hash"] == M2_TOPOLOGY_HASH for trace in traces)
    assert all(trace["checkpoint_id"] for trace in traces)
    assert private_source.encode() not in workflow_database.read_bytes()
    terminal = app.state.repository.get_terminal_result(run_id)
    assert terminal is not None
    assert terminal.state is TerminalState.SUCCEEDED
    assert {
        "run_id",
        "asset_id",
        "base_version_id",
        "command_id",
        "workflow_version",
        "topology_hash",
        "node_attempt",
        "last_node",
        "selected_edge",
        "semantic_role_proposal_hash",
        "model_call_count",
        "artifact_id",
        "canonical_version_id",
        "terminal_candidate",
        "finding_codes",
        "safe_message",
        "retryable",
    } == M2_GRAPH_STATE_ALLOWED_KEYS


def test_m2_machine_readable_checkpoint_matches_graph_contract() -> None:
    checkpoint = json.loads(
        (
            Path(__file__).parents[2]
            / "contracts"
            / "checkpoints"
            / "e3-m2-preparation-v1.json"
        ).read_text(encoding="utf-8")
    )
    workflow = checkpoint["workflow"]
    assert workflow["version"] == M2_WORKFLOW_VERSION
    assert workflow["topology_hash"] == M2_TOPOLOGY_HASH
    assert workflow["nodes"] == list(M2_GRAPH_NODES)
    assert workflow["conditional_edges"] == [
        f"{source}->{target}"
        for source, target in M2_GRAPH_EDGES
        if source != "START" and target != "END"
    ]
    assert set(workflow["state_allowlist"]) == M2_GRAPH_STATE_ALLOWED_KEYS


def test_m2_structured_schema_is_bounded_to_supplied_statement_ids() -> None:
    first = uuid4()
    second = uuid4()

    schema = M2ProductionGraph._semantic_output_schema(
        statement_ids=[first, second]
    )

    assignments = schema["properties"]["assignments"]
    statement_id = schema["$defs"]["M2SemanticRoleAssignment"]["properties"][
        "statement_id"
    ]
    assert assignments["minItems"] == 2
    assert assignments["maxItems"] == 2
    assert statement_id["enum"] == [str(first), str(second)]
    assert "reasoning" not in schema["$defs"]["M2SemanticRoleAssignment"][
        "properties"
    ]
    assert "enum" not in M2SemanticRoleProposal.model_json_schema()["$defs"][
        "M2SemanticRoleAssignment"
    ]["properties"]["statement_id"]


def test_m2_role_reasoning_defaults_without_affecting_runtime_decision() -> None:
    statement_id = uuid4()
    proposal = M2SemanticRoleProposal.model_validate(
        {
            "assignments": [
                {"statement_id": str(statement_id), "roles": ["CHANGE"]}
            ]
        }
    )

    assert proposal.assignments[0].statement_id == statement_id
    assert proposal.assignments[0].reasoning


def test_m2_stale_base_safe_stops_before_canonical_effect(tmp_path: Path) -> None:
    database = tmp_path / "asset.sqlite3"
    app = create_app(database_path=database, model_client=FakeModelClient())
    with TestClient(app) as client:
        accepted = _accepted_m1(
            client,
            source_text="第一次试坐后改变选择, 后来申请退换。",
        )
        repository = app.state.repository
        graph = M2ProductionGraph(
            repository=repository,
            service=M2CriticalMomentService(repository),
            model_client=FakeModelClient(),
        )
        run_id, initial = _start_m2_context(
            repository,
            graph,
            asset_id=UUID(accepted["asset"]["asset_id"]),
            base_version_id=UUID(accepted["asset"]["version_id"]),
        )
        changed = client.patch(
            f"/api/v1/m1/assets/{accepted['asset']['asset_id']}/brief",
            json={
                "expected_version_id": accepted["asset"]["version_id"],
                "context": "在启动 M2 后更正了当前 M1。",
            },
        )
        assert changed.status_code == 200, changed.text

    async def invoke_stale_run() -> None:
        async with AsyncSqliteSaver.from_conn_string(
            str(tmp_path / "stale-workflow.sqlite3")
        ) as saver:
            await saver.setup()
            graph.compile(saver)
            await graph.compiled.ainvoke(initial.as_graph_state(), graph._config(run_id))

    asyncio.run(invoke_stale_run())
    terminal = repository.get_terminal_result(run_id)
    assert terminal is not None
    assert terminal.state is TerminalState.POLICY_BLOCKED
    assert [
        trace["selected_edge"]
        for trace in repository.list_workflow_traces(run_id)
    ] == ["stale_or_incompatible", "end"]
    with pytest.raises(AssetNotFoundError):
        repository.get_current_m2(UUID(accepted["asset"]["asset_id"]))


def test_m2_restart_resumes_after_persist_without_duplicate_canonical_write(
    tmp_path: Path,
) -> None:
    database = tmp_path / "asset.sqlite3"
    app = create_app(database_path=database, model_client=FakeModelClient())
    with TestClient(app) as client:
        accepted = _accepted_m1(
            client,
            source_text="第一次试坐后改变选择, 后来申请退换。",
        )
    repository = app.state.repository
    asset_id = UUID(accepted["asset"]["asset_id"])
    base_version_id = UUID(accepted["asset"]["version_id"])
    workflow_database = tmp_path / "workflow.sqlite3"
    first = M2ProductionGraph(
        repository=repository,
        service=M2CriticalMomentService(repository),
        model_client=FakeModelClient(),
    )
    run_id, initial = _start_m2_context(
        repository,
        first,
        asset_id=asset_id,
        base_version_id=base_version_id,
    )

    async def interrupt_then_resume() -> None:
        async with AsyncSqliteSaver.from_conn_string(str(workflow_database)) as saver:
            await saver.setup()
            first.compile(saver, interrupt_after=["persist_m2_map"])
            await first.compiled.ainvoke(
                initial.as_graph_state(),
                first._config(run_id),
            )
            assert repository.get_terminal_result(run_id) is None

        artifact_before = repository.get_current_m2(asset_id)
        versions_before = repository.list_version_ids(asset_id)
        restarted = M2ProductionGraph(
            repository=repository,
            service=M2CriticalMomentService(repository),
            model_client=FakeModelClient(),
        )
        async with AsyncSqliteSaver.from_conn_string(str(workflow_database)) as saver:
            await saver.setup()
            restarted.compile(saver)
            await restarted.resume_incomplete(run_id)

        assert repository.get_terminal_result(run_id).state is TerminalState.SUCCEEDED
        assert repository.get_current_m2(asset_id) == artifact_before
        assert repository.list_version_ids(asset_id) == versions_before

    asyncio.run(interrupt_then_resume())
