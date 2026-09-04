from __future__ import annotations

from copy import deepcopy

from app.ui.owner_view_models import (
    insurer_review_html,
    insurer_summary_html,
    insurer_task_rows,
    owner_action_html,
    owner_appraisal_guidance_html,
    owner_communication_script,
    owner_material_rows,
    owner_overview_html,
    owner_task_choices,
    owner_task_rows,
)


def test_owner_overview_translates_case_state_without_internal_ids(
    golden_ui_runtime,
):
    case = golden_ui_runtime.cases.export_case(golden_ui_runtime.case_id)

    rendered = owner_overview_html(case, golden_ui_runtime.state)

    assert "合成路口 · Golden Demo" in rendered
    assert "两轮车辆主要责任、机动车次要责任" in rendered
    assert "88.6%" in rendered
    assert "当前材料倾向认定为非机动车" in rendered
    assert "FACT-" not in rendered
    assert "NODE-" not in rendered
    assert "LAW-" not in rendered
    assert "inputs_hash" not in rendered


def test_owner_action_prioritizes_deadline_and_plain_steps(
    golden_ui_runtime,
):
    case = golden_ui_runtime.cases.export_case(golden_ui_runtime.case_id)

    rendered = owner_action_html(case, golden_ui_runtime.state)
    rows = owner_task_rows(case, golden_ui_runtime.state)

    assert rows[0][0] in {"立即处理", "优先处理"}
    assert rows[0][0] in rendered
    assert "准备道路交通事故认定复核材料" in rendered
    assert rows[0][2] == "准备道路交通事故认定复核材料"
    assert rows[0][3] == "截止时间：08月10日 23:59"
    assert "截止时间：08月10日 23:59" in rendered
    assert all("TASK-" not in str(cell) for row in rows for cell in row)


def test_owner_task_completion_is_an_audited_overlay(
    golden_ui_runtime,
):
    state = golden_ui_runtime.state
    case_id = golden_ui_runtime.case_id
    first_task_id = state["rights_tasks"][0]["task_id"]

    golden_ui_runtime.cases.record_owner_task_status(
        case_id,
        first_task_id,
        status="completed",
    )
    case = golden_ui_runtime.cases.export_case(case_id)
    rows = owner_task_rows(case, state)
    choices = owner_task_choices(state, case)

    completed = next(row for row in rows if row[2] == state["rights_tasks"][0]["title"])
    assert completed[1] == "已完成"
    assert first_task_id not in {value for _, value in choices}
    assert any(
        event["event_type"] == "owner_task_status_updated"
        for event in case["audit_events"]
    )


def test_owner_materials_show_collaboration_provider(
    golden_ui_runtime,
):
    case_id = golden_ui_runtime.case_id
    source_id = golden_ui_runtime.cases.sources(case_id)[0].source_id
    golden_ui_runtime.cases.record_collaboration_materials(
        case_id,
        [source_id],
        provider="保险公司补充",
    )

    rows = owner_material_rows(golden_ui_runtime.cases.export_case(case_id))

    matching = next(row for row in rows if row[2] == "保险公司补充")
    assert matching[0]
    assert len(matching) == 4
    assert matching[3] == "已保存，可查看"
    assert any("合成示例" in row[0] for row in rows)
    categories = {row[1] for row in rows}
    assert "车辆技术参数" in categories
    assert "医疗材料" in categories
    assert any(str(row[0]).endswith(".jpg") for row in rows)
    assert any(str(row[0]).endswith(".mp4") for row in rows)


def test_communication_script_is_grounded_and_never_claims_submission(
    golden_ui_runtime,
):
    rendered = owner_communication_script(golden_ui_runtime.state, "交管部门")

    assert "《重新检验、鉴定申请书》" in rendered
    assert "第五十六条、第五十七条及第一百一十二条" in rendered
    assert "最高设计车速" in rendered
    assert "事故经过与现有材料" in rendered
    assert "当面提交" in rendered
    assert "中国邮政 EMS" in rendered
    assert "内件品名" in rendered
    assert "并非申请成立必须同时完成的法定条件" in rendered
    assert "本草稿不会自动提交" in rendered
    assert "两轮车辆主要责任、机动车次要责任" not in rendered
    assert "支持度" not in rendered
    assert "责任比例" not in rendered
    assert "已提交" not in rendered


def test_all_external_communication_drafts_omit_liability_predictions(
    golden_ui_runtime,
):
    forbidden = ("主要责任", "次要责任", "同等责任", "支持度", "责任比例")

    for target in ("交管部门", "事故相对方", "保险理赔员"):
        rendered = owner_communication_script(golden_ui_runtime.state, target)
        assert all(value not in rendered for value in forbidden)
        assert "88.6%" not in rendered


def test_external_draft_filters_liability_claims_embedded_in_case_facts(
    golden_ui_runtime,
):
    state = deepcopy(golden_ui_runtime.state)
    state["case_capsule"]["confirmed_facts"].insert(
        0,
        {
            "fact_id": "FACT-UNSAFE-LIABILITY",
            "statement": "办案人员口头倾向机动车主责并提出70%责任比例",
            "source_node_ids": ["NODE-UNSAFE-LIABILITY"],
            "status": "verified",
        },
    )

    rendered = owner_communication_script(state, "交管部门")

    assert "机动车主责" not in rendered
    assert "70%责任比例" not in rendered
    assert "FACT-UNSAFE-LIABILITY" not in rendered


def test_appraisal_documents_follow_the_procedure_stage(
    golden_ui_runtime,
):
    state = golden_ui_runtime.state

    initial = owner_communication_script(
        state,
        "交管部门",
        "交管部门尚未委托鉴定",
    )
    supplemental = owner_communication_script(
        state,
        "交管部门",
        "原鉴定遗漏事项或取得新材料",
    )
    court = owner_communication_script(
        state,
        "交管部门",
        "已进入法院诉讼",
    )

    assert "《车辆属性检验、鉴定申请书》" in initial
    assert "第四十九条、第五十四条" in initial
    assert "《补充鉴定申请书》" in supplemental
    assert "新的鉴定材料" in supplemental
    assert "《司法鉴定申请书》（提交受理法院）" in court
    assert "第三十条至第三十二条" in court
    assert "公安机关交通管理部门/人民法院" not in initial
    assert "公安机关交通管理部门（事故处理承办部门）" in initial


def test_owner_appraisal_guidance_explains_application_and_report_names(
    golden_ui_runtime,
):
    rendered = owner_appraisal_guidance_html(golden_ui_runtime.state)

    assert "车辆属性专项行动" in rendered
    assert "《补充鉴定书》是鉴定机构出具的结果" in rendered
    assert "车主提交的申请名称" in rendered
    assert "从分析直接进入行动" in rendered
    assert "当面 + EMS" in rendered
    assert "不是申请成立必须同时完成的法定条件" in rendered


def test_owner_appraisal_guidance_uses_initial_application_without_real_appraisal(
    golden_ui_runtime,
):
    state = deepcopy(golden_ui_runtime.state)
    state["vehicle_nature_result"]["appraisal_factors"] = [
        {
            "factor": "vehicle_nature_appraisal",
            "status": "unknown",
            "explanation": "未发现车辆属性鉴定意见。",
            "fact_ids": [],
            "evidence_ids": [],
        }
    ]

    rendered = owner_appraisal_guidance_html(state)

    assert "《车辆属性检验、鉴定申请书》" in rendered
    assert "第四十九条、第五十四条" in rendered
    assert "优先准备：《重新检验、鉴定申请书》" not in rendered


def test_insurer_views_use_plain_language_without_internal_ids(
    golden_ui_runtime,
):
    case = golden_ui_runtime.cases.export_case(golden_ui_runtime.case_id)

    summary = insurer_summary_html(case, golden_ui_runtime.state)
    review = insurer_review_html(golden_ui_runtime.state)
    tasks = insurer_task_rows(case, golden_ui_runtime.state)

    assert "保险协作摘要" in summary
    assert "现在协助车主" in summary
    assert "文书审核" in review
    assert "《道路交通事故认定复核申请书》草稿" in review
    assert "理赔员具体审核什么" in review
    assert "事实引用" in review
    assert "附件索引" in review
    assert "系统不会自动发送" in review
    assert "applicant.name" not in review
    assert "inputs_hash" not in summary + review
    assert 1 <= len(tasks) <= 3
    assert all(len(row) == 4 for row in tasks)
    assert all("TASK-" not in str(cell) for row in tasks for cell in row)
