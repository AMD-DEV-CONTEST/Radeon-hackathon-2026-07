from app.ui.view_models import rights_summary_html, rights_view


def test_due_deadlines_and_high_priority_tasks_are_first(golden_ui_runtime):
    view = rights_view(golden_ui_runtime.state)
    assert view["deadlines"]
    assert view["tasks"]
    ranks = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    task_ranks = [ranks[item["priority"]] for item in view["tasks"]]
    assert task_ranks == sorted(task_ranks)
    assert view["review_application_draft"]["status"] == "draft"
    assert "blocking_fields" in view["review_application_draft"]


def test_rights_summary_does_not_expand_the_full_draft(golden_ui_runtime):
    rendered = rights_summary_html(golden_ui_runtime.state)

    assert "期限与行动任务" in rendered
    assert "完整任务证据与规则依据保留在导出报告中" in rendered
    assert len(rendered) < 15_000
