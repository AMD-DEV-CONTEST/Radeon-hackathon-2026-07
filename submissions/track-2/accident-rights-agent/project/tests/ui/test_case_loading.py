from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

from app.demo.business_cases import seed_experience_case
from app.services.case_service import CaseService
from app.ui.gradio_app import GradioController, _select_initial_case


def test_load_case_populates_metadata_fields(golden_ui_runtime):
    controller = GradioController(
        golden_ui_runtime.cases,
        golden_ui_runtime.workflows,
        golden_ui_runtime.reports,
    )

    loaded = controller.load_case(golden_ui_runtime.case_id, "mock")

    assert loaded[0] == "CASE-GOLDEN-DEMO"
    assert loaded[2] == "2026-07-20T08:30:00+08:00"
    assert loaded[3] == "合成路口 · Golden Demo"
    assert loaded[4] == "CN"
    assert loaded[5] == "insured_driver"
    assert loaded[6] == "2026-08-06"
    assert "分析完成" in loaded[7]
    assert "现在要做什么" in loaded[8]
    assert "车辆属性专项行动" in loaded[9]
    assert loaded[10]
    assert loaded[12]
    assert "保险协作摘要" in loaded[13]
    assert loaded[14]
    assert "文书审核" in loaded[16]
    assert "车辆属性与技术参数" in loaded[22]
    assert "期限与行动任务" in loaded[23]
    assert "人工批准与安全门" in loaded[24]
    assert loaded[25] == []
    assert loaded[-1].startswith("已打开当前事故")


def test_repeated_case_listing_does_not_leak_file_descriptors(tmp_path):
    service = CaseService(tmp_path / "cases")
    for index in range(6):
        service.create_case(
            case_id=f"CASE-FD-{index}",
            location=f"测试路口 {index}",
        )

    before = _open_file_descriptor_count()
    for _ in range(40):
        summaries = service.list_cases()
        assert len(summaries) == 6
    after = _open_file_descriptor_count()

    assert after <= before + 4


def test_collaboration_material_click_without_file_is_a_safe_noop(
    golden_ui_runtime,
):
    controller = GradioController(
        golden_ui_runtime.cases,
        golden_ui_runtime.workflows,
        golden_ui_runtime.reports,
    )

    owner_rows, insurer_rows, source_rows, notice = controller.add_collaboration_files(
        golden_ui_runtime.case_id,
        None,
        "other",
        "保险公司补充",
    )

    assert owner_rows
    assert owner_rows == insurer_rows
    assert source_rows
    assert "现有事故材料保持不变" in notice


def test_insurer_can_add_material_through_shared_case_service(
    golden_ui_runtime,
    tmp_path,
):
    controller = GradioController(
        golden_ui_runtime.cases,
        golden_ui_runtime.workflows,
        golden_ui_runtime.reports,
    )
    supplement = tmp_path / "保险公司补充材料.pdf"
    supplement.write_bytes(b"%PDF-1.4\n% synthetic insurer supplement\n%%EOF\n")

    owner_rows, insurer_rows, source_rows, notice = controller.add_collaboration_files(
        golden_ui_runtime.case_id,
        [str(supplement)],
        "insurance_policy",
        "保险公司补充",
    )

    assert owner_rows == insurer_rows
    assert any(
        row[0] == supplement.name and row[2] == "保险公司补充" for row in owner_rows
    )
    assert any(row[1] == supplement.name for row in source_rows)
    assert "已接收 1 份保险公司补充材料" in notice


def test_communication_button_returns_document_and_visible_generation_status(
    golden_ui_runtime,
):
    controller = GradioController(
        golden_ui_runtime.cases,
        golden_ui_runtime.workflows,
        golden_ui_runtime.reports,
    )

    document, status = controller.generate_communication(
        "交管部门",
        "已进入法院诉讼",
        golden_ui_runtime.state,
        golden_ui_runtime.case_id,
    )

    assert "《司法鉴定申请书》（提交受理法院）" in document
    assert "已生成" in status
    assert "交管部门" in status
    assert "已进入法院诉讼" in status
    assert re.search(r"生成时间：`\d{4}-\d{2}-\d{2}T", status)
    assert "系统不会自动发送" in status
    assert "事故认定书送达日期为2026-08-06" in document
    assert "事故认定书送达日期为2026-07-28" not in document


def test_changing_communication_conditions_clears_stale_document():
    document, status = GradioController.mark_communication_stale(
        "交管部门",
        "原鉴定遗漏事项或取得新材料",
    )

    assert document == ""
    assert "原文书已清空" in status
    assert "生成可用文书" in status
    assert "原鉴定遗漏事项或取得新材料" in status


def test_loading_another_case_clears_generated_communication(golden_ui_runtime):
    controller = GradioController(
        golden_ui_runtime.cases,
        golden_ui_runtime.workflows,
        golden_ui_runtime.reports,
    )

    loaded = controller.load_case(golden_ui_runtime.case_id, "mock")

    assert loaded[-3] == ""
    assert "尚未生成文书" in loaded[-2]
    assert "已打开当前事故" in loaded[-1]


def test_reloading_golden_fixture_starts_a_fresh_demo_view(golden_ui_runtime):
    controller = GradioController(
        golden_ui_runtime.cases,
        golden_ui_runtime.workflows,
        golden_ui_runtime.reports,
    )
    historical_thread = golden_ui_runtime.cases.latest_thread(
        golden_ui_runtime.case_id
    )

    seeded = controller.seed_fixture("golden")
    first_load = controller.load_case(seeded[0], "mock")
    refreshed = controller.load_case(seeded[0], "mock")

    assert seeded[0] == "CASE-GOLDEN-DEMO"
    assert first_load[1] == ""
    assert refreshed[1] == ""
    assert "等待分析" in first_load[7]
    assert "等待分析" in refreshed[7]
    assert "未运行" in first_load[19]
    assert golden_ui_runtime.cases.latest_thread(
        golden_ui_runtime.case_id
    ) == historical_thread


def test_audit_is_loaded_on_demand_with_a_browser_safe_limit(golden_ui_runtime):
    controller = GradioController(
        golden_ui_runtime.cases,
        golden_ui_runtime.workflows,
        golden_ui_runtime.reports,
    )

    rows = controller.refresh_audit(
        golden_ui_runtime.case_id,
        "全部",
        "全部",
        "全部",
    )

    assert rows
    assert len(rows) <= 20


def test_experience_case_metadata_keeps_loaded_case_in_my_accidents(tmp_path):
    service = CaseService(tmp_path / "cases")
    case_id, _ = seed_experience_case(service.workspace, "demo_c")
    controller = GradioController(
        service,
        cast(Any, None),
        cast(Any, None),
    )

    metadata = service.metadata(case_id)
    choices = controller.case_choices(include_case_id=case_id)

    assert metadata.location == "合成体验 · 材料相互冲突"
    assert metadata.accident_time is not None
    assert any(value == case_id for _, value in choices)


def test_legacy_experience_case_without_metadata_remains_selectable(tmp_path):
    service = CaseService(tmp_path / "cases")
    case_id = service.workspace.create_case("CASE-EXP-C-LEGACY")
    controller = GradioController(
        service,
        cast(Any, None),
        cast(Any, None),
    )

    choices = controller.case_choices(include_case_id=case_id)

    label = next(label for label, value in choices if value == case_id)
    assert "合成体验" in label
    assert "材料相互冲突" in label


def test_real_case_is_preferred_over_experience_cases_on_startup():
    choices = [
        ("合成体验 · 材料相互冲突 · 07月20日", "CASE-EXP-C-12345678"),
        ("合成路口 · Golden Demo · 07月20日", "CASE-GOLDEN-DEMO"),
        ("中山路与人民路路口 · 07月30日", "CASE-20260730-REAL0001"),
    ]

    assert _select_initial_case(choices) == "CASE-20260730-REAL0001"


def test_golden_case_is_startup_fallback_when_only_experience_cases_exist():
    choices = [
        ("合成体验 · 材料相互冲突 · 07月20日", "CASE-EXP-C-12345678"),
        ("合成路口 · Golden Demo · 07月20日", "CASE-GOLDEN-DEMO"),
    ]

    assert _select_initial_case(choices) == "CASE-GOLDEN-DEMO"


def test_golden_case_is_clearly_labeled_as_synthetic(golden_ui_runtime):
    controller = GradioController(
        golden_ui_runtime.cases,
        golden_ui_runtime.workflows,
        golden_ui_runtime.reports,
    )

    label = next(
        label
        for label, value in controller.case_choices(include_case_id="CASE-GOLDEN-DEMO")
        if value == "CASE-GOLDEN-DEMO"
    )

    assert label.startswith("合成体验 · 主演示")


def test_case_picker_hides_other_experience_cases(tmp_path):
    service = CaseService(tmp_path / "cases")
    current_case_id, _ = seed_experience_case(service.workspace, "demo_b")
    hidden_case_id, _ = seed_experience_case(service.workspace, "demo_c")
    service.create_case(
        case_id="CASE-REAL-001",
        location="人民路与中山路路口",
    )
    controller = GradioController(service, cast(Any, None), cast(Any, None))

    values = {
        value for _, value in controller.case_choices(include_case_id=current_case_id)
    }

    assert current_case_id in values
    assert hidden_case_id not in values
    assert "CASE-REAL-001" in values


def test_material_row_opens_the_immutable_stored_file(golden_ui_runtime):
    controller = GradioController(
        golden_ui_runtime.cases,
        golden_ui_runtime.workflows,
        golden_ui_runtime.reports,
    )
    expected = golden_ui_runtime.cases.sources(golden_ui_runtime.case_id)[0]

    path, note = controller.preview_material_row(
        golden_ui_runtime.case_id,
        (0, 0),
    )

    assert path is not None
    assert Path(path).is_file()
    assert expected.original_name in note


def _open_file_descriptor_count() -> int:
    descriptor_root = Path("/proc/self/fd")
    if not descriptor_root.exists():
        descriptor_root = Path("/dev/fd")
    return len(list(descriptor_root.iterdir()))
