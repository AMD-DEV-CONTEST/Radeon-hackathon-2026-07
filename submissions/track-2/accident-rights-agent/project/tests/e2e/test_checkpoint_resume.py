def test_safe_stop_resume_preserves_high_cost_node(e2e_runtime):
    generator = e2e_runtime.workflows.run_incremental(
        e2e_runtime.case_id
    )
    intake = next(generator)
    evidence = next(generator)
    thread_id = evidence["thread_id"]
    evidence_result = evidence["state"]["node_results"]["evidence_ready"]
    e2e_runtime.workflows.request_stop(thread_id)
    paused = next(generator)
    assert paused["paused"] is True
    assert paused["recoverable"] is True
    assert paused["next"] == ["legal_retrieval"]

    resumed = list(
        e2e_runtime.workflows.resume_incremental(thread_id)
    )[-1]
    assert resumed["state"]["node_results"]["evidence_ready"] == evidence_result
    assert (
        resumed["state"]["evidence_summary"][
            "high_cost_parser_reexecuted"
        ]
        is False
    )
    assert resumed["current_node"] == "human_approval"
    assert intake["case_id"] == resumed["case_id"]
