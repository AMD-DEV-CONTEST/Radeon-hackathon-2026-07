from app.ui.view_models import evidence_timeline_html, evidence_timeline_rows


def test_evidence_fact_and_conflict_references_exist(golden_ui_runtime):
    case = golden_ui_runtime.cases.export_case(golden_ui_runtime.case_id)
    rows = evidence_timeline_rows(case)
    fact_ids = {item["fact_id"] for item in case["facts"]}
    node_ids = {item["node_id"] for item in case["evidence_nodes"]}
    source_ids = {item["source_id"] for item in case["sources"]}
    assert rows
    for row in rows:
        assert row[1] in fact_ids
        assert set(filter(None, row[2].split(", "))) <= source_ids
        assert set(filter(None, row[3].split(", "))) <= node_ids


def test_timeline_can_filter_collision_phase(golden_ui_runtime):
    case = golden_ui_runtime.cases.export_case(golden_ui_runtime.case_id)
    rows = evidence_timeline_rows(case, phase="碰撞时")
    assert rows
    assert all(row[0] == "碰撞时" for row in rows)


def test_timeline_can_filter_source_role_enum(golden_ui_runtime):
    case = golden_ui_runtime.cases.export_case(golden_ui_runtime.case_id)
    rows = evidence_timeline_rows(case, source_filter="dashcam_video")
    assert rows


def test_timeline_html_is_bounded_and_recording_friendly(golden_ui_runtime):
    case = golden_ui_runtime.cases.export_case(golden_ui_runtime.case_id)
    markup = evidence_timeline_html(case)
    assert "证据时间线与冲突" in markup
    assert "Fact ID" in markup
    assert markup.count("<tr>") <= 21
