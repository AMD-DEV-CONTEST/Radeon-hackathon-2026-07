from __future__ import annotations

from app.graph.workflow import CaseOrchestrator


def test_demo_a_runs_through_business_agents_and_checkpoints(
    tmp_path, demo_case_a, legal_retriever
):
    workspace, case_id = demo_case_a
    graph = CaseOrchestrator(
        workspace=workspace,
        retriever=legal_retriever,
        checkpoint_path=tmp_path / "business-checkpoints.sqlite3",
    )
    try:
        interrupted = graph.run(
            case_id,
            thread_id="THREAD-BUSINESS-A",
            interrupt_after="vehicle_nature",
        )
        vehicle_node = interrupted["node_results"]["vehicle_nature"]
        assert vehicle_node["status"] == "succeeded"

        completed = graph.resume("THREAD-BUSINESS-A")
        assert completed["node_results"]["vehicle_nature"] == vehicle_node
        assert completed["node_results"]["liability"]["status"] == "succeeded"
        assert completed["current_node"] == "human_approval"
        assert completed["verifier_results"]["passed"] is True
        assert completed["evidence_summary"]["high_cost_parser_reexecuted"] is False
        assert len(completed["violation_matrix"]) == 24
        assert len(completed["liability_hypotheses"]) >= 2
        assert abs(sum(completed["responsibility_probabilities"].values()) - 1.0) < 1e-6
        assert completed["insurance_payment_estimate"]["status"] == "insufficient_data"
        events = workspace.store(case_id).list_audit_events(case_id)
        assert {
            "business_intake_completed",
            "vehicle_nature_completed",
            "liability_completed",
        } <= {item["event_type"] for item in events}
    finally:
        graph.close()


def test_demo_b_triggers_missing_evidence_branch(
    tmp_path, demo_case_b, legal_retriever
):
    workspace, case_id = demo_case_b
    graph = CaseOrchestrator(
        workspace=workspace,
        retriever=legal_retriever,
        checkpoint_path=tmp_path / "business-b.sqlite3",
    )
    try:
        completed = graph.run(case_id, thread_id="THREAD-BUSINESS-B")
        assert completed["branch_reason"] == "missing_evidence"
        assert (
            completed["liability_result"]["uncertainty"]["unique_conclusion_blocked"]
            is True
        )
        assert completed["accident_responsibility"]["selected_hypothesis_id"] is None
    finally:
        graph.close()


def test_demo_c_marks_vehicle_and_liability_as_disputed(
    tmp_path, demo_case_c, legal_retriever
):
    workspace, case_id = demo_case_c
    graph = CaseOrchestrator(
        workspace=workspace,
        retriever=legal_retriever,
        checkpoint_path=tmp_path / "business-c.sqlite3",
    )
    try:
        completed = graph.run(case_id, thread_id="THREAD-BUSINESS-C")
        assert completed["vehicle_nature_result"]["conclusion_status"] == "disputed"
        assert completed["vehicle_nature_result"]["confidence"] <= 0.52
        assert completed["liability_result"]["uncertainty"]["disputed_fact_ids"]
        assert completed["branch_reason"] == "missing_evidence"
    finally:
        graph.close()
