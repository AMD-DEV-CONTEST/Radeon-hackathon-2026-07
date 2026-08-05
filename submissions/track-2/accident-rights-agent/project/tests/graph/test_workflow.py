from __future__ import annotations

from app.graph.verifier import CaseVerifier
from app.graph.workflow import CaseOrchestrator


def test_end_to_end_interrupt_resume_does_not_repeat_evidence(
    tmp_path, demo_case, legal_retriever
):
    workspace, case_id = demo_case
    graph = CaseOrchestrator(
        workspace=workspace,
        retriever=legal_retriever,
        checkpoint_path=tmp_path / "checkpoints.sqlite3",
    )
    try:
        interrupted = graph.run(
            case_id,
            thread_id="THREAD-RECOVERY",
            interrupt_after="evidence_ready",
        )
        evidence_result = interrupted["node_results"]["evidence_ready"]
        status = graph.status("THREAD-RECOVERY")
        assert status["recoverable"] is True
        assert status["next"] == ["legal_retrieval"]

        completed = graph.resume("THREAD-RECOVERY")
        assert completed["current_node"] == "human_approval"
        assert completed["approval_status"] == "pending"
        assert completed["document_status"] == "draft"
        assert completed["human_action_required"] is True
        assert completed["verifier_results"]["passed"] is True
        assert completed["node_results"]["evidence_ready"] == evidence_result
        assert (
            completed["evidence_summary"]["high_cost_parser_reexecuted"]
            is False
        )
    finally:
        graph.close()


def test_schema_error_retries_exactly_once(
    tmp_path, demo_case, legal_retriever
):
    workspace, case_id = demo_case
    graph = CaseOrchestrator(
        workspace=workspace,
        retriever=legal_retriever,
        checkpoint_path=tmp_path / "retry.sqlite3",
    )
    try:
        completed = graph.run(
            case_id,
            thread_id="THREAD-RETRY",
            simulate_json_error_at="legal_retrieval",
        )
        result = completed["node_results"]["legal_retrieval"]
        assert result["status"] == "succeeded"
        assert result["retry_count"] == 1
        assert "retried once" in result["warnings"][0]
    finally:
        graph.close()


def test_verifier_blocks_missing_citations(demo_case, legal_retriever):
    workspace, case_id = demo_case
    state = {
        "case_id": case_id,
        "legal_citations": [],
        "liability_hypotheses": [
            {
                "label": "确定责任结论",
                "certainty": "deterministic",
                "evidence_ids": ["NODE-TEST-001"],
                "citation_ids": [],
                "compensation_regime": "pending_vehicle_classification",
            }
        ],
        "vehicle_classification": {
            "classification": "suspected_motor_vehicle"
        },
        "protected_fields_valid": True,
        "document_status": "draft",
    }
    result = CaseVerifier(
        workspace, legal_retriever.corpus
    ).verify(state)
    assert result["passed"] is False
    assert "legal_citations" in result["blocking_reasons"]
    assert "fact_compatibility" in result["blocking_reasons"]
