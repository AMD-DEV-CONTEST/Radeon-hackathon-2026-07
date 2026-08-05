from __future__ import annotations

from app.graph.workflow import CaseOrchestrator


def test_liability_to_rights_to_approval_pending_and_resume(
    tmp_path, demo_case_a, legal_retriever
):
    workspace, case_id = demo_case_a
    graph = CaseOrchestrator(
        workspace=workspace,
        retriever=legal_retriever,
        checkpoint_path=tmp_path / "rights-graph.sqlite3",
    )
    try:
        interrupted = graph.run(
            case_id,
            thread_id="THREAD-RIGHTS-INTEGRATION",
            interrupt_after="rights_workflow",
        )
        rights_node = interrupted["node_results"]["rights_workflow"]
        assert rights_node["status"] == "succeeded"
        completed = graph.resume("THREAD-RIGHTS-INTEGRATION")
        assert completed["node_results"]["rights_workflow"] == rights_node
        assert completed["delivery_date_result"]["status"] == "confirmed"
        assert completed["deadlines"][0]["rule_id"] == (
            "RULE-CN-DEADLINE-ACCIDENT-REVIEW-2017"
        )
        assert completed["rights_tasks"]
        assert completed["evidence_collection_plan"]
        assert completed["review_application_draft"]["status"] == "draft"
        assert completed["policy_gate"]["decision"] in {
            "pass",
            "pass_with_warnings",
        }
        assert completed["approval_status"] == "pending"
        assert completed["document_status"] == "draft"
    finally:
        graph.close()


def test_incomplete_draft_cannot_be_approved(
    tmp_path, demo_case_a, legal_retriever
):
    workspace, case_id = demo_case_a
    graph = CaseOrchestrator(
        workspace=workspace,
        retriever=legal_retriever,
        checkpoint_path=tmp_path / "approval-api.sqlite3",
    )
    try:
        graph.run(case_id, thread_id="THREAD-APPROVE")
        try:
            graph.decide_approval(
                "THREAD-APPROVE",
                decision="approved",
                approver="legal-reviewer",
                comments="facts and citations checked",
            )
        except ValueError as exc:
            assert "blocking fields" in str(exc)
        else:
            raise AssertionError("Incomplete draft must not be approved.")
        status = graph.decide_approval(
            "THREAD-APPROVE",
            decision="changes_requested",
            approver="legal-reviewer",
            comments="complete applicant and document fields",
        )
        assert status["approval_status"] == "changes_requested"
        assert status["document_status"] == "draft"
        assert status["approval_state"]["record"]["audit_event_id"].startswith(
            "AUDIT-"
        )
        events = workspace.store(case_id).list_audit_events(case_id)
        assert any(
            f"AUDIT-{event['id']}"
            == status["approval_state"]["record"]["audit_event_id"]
            for event in events
        )
    finally:
        graph.close()
