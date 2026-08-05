from app.ui.view_models import (
    progress_overview,
    progress_overview_html,
    progress_rows,
    progress_table_html,
)


def test_node_statuses_and_checkpoint_are_visible(golden_ui_runtime):
    state = golden_ui_runtime.state
    rows = progress_rows(state)
    assert [row[0] for row in rows] == [
        "intake",
        "evidence",
        "legal_retrieval",
        "vehicle_nature",
        "liability",
        "rights_workflow",
        "verifier",
        "human_approval",
    ]
    assert all(row[1] in {"succeeded", "warning", "blocked"} for row in rows)
    overview = progress_overview(state, recoverable=False, next_nodes=[])
    assert overview["progress_percent"] == 100
    assert overview["latest_checkpoint"] == "human_approval"

    overview_markup = progress_overview_html(overview)
    table_markup = progress_table_html(state)
    assert "执行状态与 Checkpoint" in overview_markup
    assert "100%" in overview_markup
    assert "human_approval" in table_markup
    assert "<table" in table_markup
