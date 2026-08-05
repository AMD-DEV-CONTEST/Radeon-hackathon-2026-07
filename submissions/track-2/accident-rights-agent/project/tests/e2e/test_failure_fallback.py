from __future__ import annotations

from pathlib import Path

from app.services.case_service import CaseService


def test_model_unavailable_retries_failed_node_only(e2e_runtime):
    failed = list(
        e2e_runtime.workflows.run_incremental(
            e2e_runtime.case_id,
            simulate_failure_at="vehicle_nature",
        )
    )[-1]
    assert failed["state"]["node_results"]["vehicle_nature"]["status"] == "failed"
    evidence_before = failed["state"]["node_results"]["evidence_ready"]

    retried = e2e_runtime.workflows.retry_failed(failed["thread_id"])
    assert retried["state"]["node_results"]["vehicle_nature"]["status"] == "succeeded"
    assert retried["state"]["node_results"]["evidence_ready"] == evidence_before
    assert retried["failure_count"] == 0


def test_schema_error_is_repaired_once(e2e_runtime):
    final = list(
        e2e_runtime.workflows.run_incremental(
            e2e_runtime.case_id,
            simulate_json_error_at="legal_retrieval",
        )
    )[-1]
    result = final["state"]["node_results"]["legal_retrieval"]
    assert result["status"] == "succeeded"
    assert result["retry_count"] == 1


def test_parser_failure_is_persisted_without_clearing_case(
    tmp_path, e2e_runtime, monkeypatch
):
    source = next(
        item
        for item in e2e_runtime.cases.sources(
            e2e_runtime.case_id
        )
        if item.kind == "image"
    )
    original = e2e_runtime.cases.workspace.resolve_source(
        e2e_runtime.cases.workspace.store(
            e2e_runtime.case_id
        ).get_source(source.source_id)
    )
    service = CaseService(tmp_path / "parser-cases")
    case_id = service.create_case(files=[Path(original)]).metadata.case_id

    def fail_parser(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("simulated image decoder failure")

    monkeypatch.setattr("app.evidence.pipeline.parse_image", fail_parser)
    result = service.reconstruct(case_id, mode="mock")
    assert result["status"] == "failed"
    exported = service.export_case(case_id)
    assert exported["sources"]
    assert exported["processing_runs"][-1]["status"] == "failed"
    assert any(
        item["event_type"] == "source_processing_failed"
        for item in exported["audit_events"]
    )
