from __future__ import annotations

from app.graph.workflow import CaseOrchestrator
from app.verifier.consistency import ConsistencyVerifier


def test_vehicle_compensation_conflict_blocks(
    tmp_path, demo_case_a, legal_retriever
):
    workspace, case_id = demo_case_a
    graph = CaseOrchestrator(
        workspace=workspace,
        retriever=legal_retriever,
        checkpoint_path=tmp_path / "consistency.sqlite3",
    )
    try:
        state = graph.run(case_id, thread_id="THREAD-CONSISTENCY")
    finally:
        graph.close()
    mutated = {
        **state,
        "compensation_route_result": {
            **state["compensation_route_result"],
            "regime": "motor_vs_motor",
        },
    }
    result = ConsistencyVerifier().verify(
        state=mutated,
        evidence_export=workspace.store(case_id).export_case(case_id),
    )
    assert result.passed is False
    assert "CONSISTENCY-VEHICLE-COMPENSATION" in {
        item.code for item in result.issues
    }


def test_stale_approval_is_blocked(tmp_path, demo_case_a, legal_retriever):
    workspace, case_id = demo_case_a
    graph = CaseOrchestrator(
        workspace=workspace,
        retriever=legal_retriever,
        checkpoint_path=tmp_path / "approval-consistency.sqlite3",
    )
    try:
        state = graph.run(case_id, thread_id="THREAD-STALE-APPROVAL")
    finally:
        graph.close()
    mutated = {
        **state,
        "approval_state": {
            **state["approval_state"],
            "state": "approved",
            "inputs_hash": "f" * 64,
        },
    }
    result = ConsistencyVerifier().verify(
        state=mutated,
        evidence_export=workspace.store(case_id).export_case(case_id),
    )
    assert "CONSISTENCY-STALE-APPROVAL" in {
        item.code for item in result.issues
    }
