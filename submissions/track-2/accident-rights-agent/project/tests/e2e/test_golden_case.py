from __future__ import annotations

import time


def test_golden_case_reaches_approval_pending_and_exports(e2e_runtime):
    started = time.perf_counter()
    updates = list(
        e2e_runtime.workflows.run_incremental(e2e_runtime.case_id)
    )
    elapsed = time.perf_counter() - started
    final = updates[-1]
    state = final["state"]
    assert elapsed < 90
    assert final["current_node"] == "human_approval"
    assert state["approval_status"] == "pending"
    assert state["document_status"] == "draft"
    assert state["human_action_required"] is True
    assert state["vehicle_nature_result"]
    assert len(state["liability_hypotheses"]) >= 2
    assert state["rights_tasks"]
    assert any(
        item.get("due_at") == "2026-08-11T23:59:59+08:00"
        for item in state["deadlines"]
    )
    assert state["review_application_draft"]["status"] == "draft"
    assert state["policy_gate"]["decision"] in {
        "pass",
        "pass_with_warnings",
    }
    assert final["failure_count"] == 0
    assert len(final["node_durations_ms"]) >= 8
    sources = e2e_runtime.cases.sources(e2e_runtime.case_id)
    assert any(
        source.kind == "image" and source.role == "scene_photo"
        for source in sources
    )
    assert any(
        source.kind == "image" and source.role == "road_signal_evidence"
        for source in sources
    )
    assert any(source.kind == "video" for source in sources)
    artifact = e2e_runtime.reports.export(e2e_runtime.case_id, state)
    assert artifact.markdown_path.is_file()
    assert artifact.html_path.is_file()
