"""Vehicle-owner-facing view models.

These functions deliberately translate the shared CaseState into plain
language.  Internal identifiers remain available in the professional
workbench, but are not exposed in the owner's default journey.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
GOLDEN_CASE_ID = "CASE-GOLDEN-DEMO"
GOLDEN_ACTION_DUE_AT = "2026-08-10T23:59:59+08:00"

VEHICLE_LABELS = {
    "non_motor_vehicle": "当前材料倾向认定为非机动车",
    "suspected_motor_vehicle": "车辆属性仍有争议",
    "motor_vehicle": "当前材料倾向认定为机动车",
    "insufficient_evidence": "材料不足，暂不能判断车辆属性",
    "unknown": "材料不足，暂不能判断车辆属性",
}

PRIORITY_RANK = {
    "critical": 0,
    "high": 1,
    "P0": 0,
    "medium": 2,
    "P1": 2,
    "low": 3,
    "P2": 3,
}

PRIORITY_LABELS = {
    "critical": "立即处理",
    "high": "优先处理",
    "P0": "优先处理",
    "medium": "建议处理",
    "P1": "建议处理",
    "low": "后续处理",
    "P2": "后续处理",
}

TASK_STATUS_LABELS = {
    "draft": "待处理",
    "pending": "待处理",
    "in_progress": "处理中",
    "completed": "已完成",
    "dismissed": "已跳过",
}

RESPONSIBLE_LABELS = {
    "vehicle_owner": "车主",
    "case_handler": "车主 + 保险理赔员",
    "claim_handler": "保险理赔员",
    "vehicle_nature_reviewer": "保险理赔员 + 专业人员",
    "insured_or_claim_handler": "车主 + 保险理赔员",
}

MATERIAL_ROLE_LABELS = {
    "accident_determination": "事故认定书",
    "delivery_information": "送达材料",
    "dashcam_video": "行车记录仪",
    "scene_photo": "现场照片",
    "road_signal_evidence": "道路信号 / 监控材料",
    "vehicle_document": "车辆材料",
    "vehicle_registration": "车辆登记 / 号牌",
    "vehicle_certificate_ccc": "合格证 / CCC",
    "vehicle_technical_parameters": "车辆技术参数",
    "appraisal_report": "鉴定报告",
    "inquiry_record": "询问笔录",
    "medical_record": "医疗材料",
    "repair_record": "维修材料",
    "insurance_policy": "保险材料",
    "other": "其他材料",
}

EXTERNAL_FACT_EXCLUSIONS = (
    "主要责任",
    "次要责任",
    "同等责任",
    "全部责任",
    "责任比例",
    "赔偿比例",
    "支持度",
    "主责",
    "次责",
    "全责",
    "无责",
)

REVIEW_FIELD_LABELS = {
    "applicant.name": "车主姓名",
    "applicant.identity_or_role": "车主身份或与事故的关系",
    "challenged_document.document_number": "被复核事故认定书的编号",
    "challenged_document.delivery_date": "事故认定书的实际送达日期",
    "facts": "能够回溯到原始材料的事实陈述",
    "legal_basis": "经核验的复核程序依据",
}


def owner_overview_html(case: dict[str, Any], state: dict[str, Any]) -> str:
    metadata = case.get("metadata", {})
    location = metadata.get("location") or "地点待补充"
    accident_time = _friendly_datetime(metadata.get("accident_time"))
    status, status_hint = _case_status(state)
    hypothesis, probability = _top_hypothesis(state)
    vehicle = state.get("vehicle_nature_result") or state.get(
        "vehicle_classification", {}
    )
    vehicle_label = VEHICLE_LABELS.get(
        str(vehicle.get("classification") or "unknown"),
        "车辆属性仍需核验",
    )
    next_deadline = _next_deadline(state)
    deadline_text = (
        f"{next_deadline['matter']} · {next_deadline['due']}"
        if next_deadline
        else "当前没有已确认的临近期限"
    )
    evidence = _plain_evidence(case, limit=3)
    evidence_items = (
        "".join(f"<li>{escape(item)}</li>" for item in evidence)
        or "<li>分析完成后，将在这里显示最关键的事实。</li>"
    )
    probability_text = (
        f"{probability * 100:.1f}%" if probability is not None else "等待分析"
    )
    responsibility_text = hypothesis or "等待分析责任方案"
    return f"""
    <section class="owner-overview">
      <div class="owner-status">
        <span class="eyebrow">当前进展</span>
        <h2>{escape(status)}</h2>
        <p>{escape(status_hint)}</p>
      </div>
      <div class="owner-summary-grid">
        <article><span>事故</span><strong>{escape(location)}</strong>
          <small>{escape(accident_time)}</small></article>
        <article><span>当前责任判断</span><strong>{escape(responsibility_text)}</strong>
          <small>当前方案支持度 {escape(probability_text)}，不是最终认定</small></article>
        <article><span>两轮车辆属性</span><strong>{escape(vehicle_label)}</strong>
          <small>以登记、鉴定、车辆参数和属地规则综合核验</small></article>
        <article><span>最近期限</span><strong>{escape(deadline_text)}</strong>
          <small>请以承办机关实际受理时间为准</small></article>
      </div>
      <div class="owner-evidence">
        <h3>为什么这样判断</h3>
        <ul>{evidence_items}</ul>
      </div>
    </section>
    """


def owner_action_html(case: dict[str, Any], state: dict[str, Any]) -> str:
    tasks = _active_tasks(state, _task_status_overrides(case))
    if not tasks:
        if not state:
            return """
            <section class="next-action empty">
              <span class="eyebrow">现在要做什么</span>
              <h2>先分析这起事故</h2>
              <p>系统会检查材料、责任方案和法定期限，然后只把最重要的下一步交给您。</p>
            </section>
            """
        return """
        <section class="next-action done">
          <span class="eyebrow">现在要做什么</span>
          <h2>当前没有待办事项</h2>
          <p>请留意保险理赔员补件提醒；任何对外文书仍需您本人确认后手工提交。</p>
        </section>
        """
    task = tasks[0]
    actions = task.get("recommended_actions", [])
    steps = (
        "".join(f"<li>{escape(str(item))}</li>" for item in actions[:4])
        or "<li>按任务说明准备相关材料，并保留沟通记录。</li>"
    )
    due = _task_due_label(case, task)
    priority = PRIORITY_LABELS.get(str(task.get("priority") or ""), "建议处理")
    reason = task.get("objective") or "及时处理有助于保留您的程序权利。"
    return f"""
    <section class="next-action">
      <span class="eyebrow">现在要做什么</span>
      <div>
        <span class="priority-pill">{escape(priority)}</span>
        <span class="due-pill">{escape(due)}</span>
      </div>
      <h2>{escape(str(task.get("title") or "处理下一项权益任务"))}</h2>
      <p class="action-reason">{escape(str(reason))}</p>
      <ol>{steps}</ol>
      <p class="action-note">系统只提供行动辅助，不会替您自动向交管部门、事故相对方或其他机构发送任何内容。</p>
    </section>
    """


def owner_appraisal_guidance_html(state: dict[str, Any]) -> str:
    """Explain the correct vehicle-appraisal procedural document."""
    vehicle = state.get("vehicle_nature_result") or state.get(
        "vehicle_classification", {}
    )
    has_appraisal = _has_existing_appraisal(vehicle)
    unknown_parameters = [
        str(item.get("display_name") or item.get("parameter") or "")
        for item in vehicle.get("parameter_comparison", [])
        if item.get("status") in {"unknown", "conflicting"}
    ]
    parameters = unknown_parameters or [
        "最高设计车速及解除限速情况",
        "整车质量",
        "电机额定连续输出功率",
        "蓄电池标称电压",
        "脚踏骑行能力",
        "实车与合格证、CCC的一致性及改装情况",
    ]
    parameter_items = "".join(f"<li>{escape(item)}</li>" for item in parameters[:8])
    if has_appraisal:
        title = "优先准备：《重新检验、鉴定申请书》"
        route = (
            "提交给原办案交管部门。先确认鉴定意见的实际送达日期；"
            "有异议时应在送达之日起三个工作日内提出书面申请。"
        )
        legal = (
            "《道路交通事故处理程序规定》第五十六条、第五十七条及"
            "第一百一十二条：当事人应在送达之日起三个工作日内提出书面申请，"
            "获批后由原办案单位另行委托鉴定机构。"
        )
        supplement = (
            "如只是原委托事项遗漏，或后来取得新的合格证、CCC、实车检测材料，"
            "可另附《补充鉴定申请书》，请求办案单位审查是否补充委托。"
            "《补充鉴定书》是鉴定机构出具的结果，不是车主提交的申请名称。"
        )
    else:
        title = "优先准备：《车辆属性检验、鉴定申请书》"
        route = (
            "提交给事故承办交管部门，请求其审查车辆属性争议并依法委托具备"
            "相应能力的鉴定机构；车主不在本阶段自行替代办案单位作出委托。"
        )
        legal = (
            "《道路交通事故处理程序规定》第四十九条、第五十四条：需要检验、"
            "鉴定的，由公安机关交通管理部门委托，鉴定意见应载明委托事项、"
            "材料、依据、结论和分析过程。"
        )
        supplement = (
            "如果交管部门已经作出鉴定委托，请先取得委托事项和完整鉴定意见，"
            "再判断是补充鉴定还是重新鉴定。"
        )
    return f"""
    <section class="appraisal-action">
      <span class="eyebrow">车辆属性专项行动</span>
      <h2>{escape(title)}</h2>
      <p>{escape(route)}</p>
      <h3>请把鉴定事项写具体</h3>
      <ul>{parameter_items}</ul>
      <p class="legal-basis">{escape(legal)}</p>
      <p class="supplement-note">{escape(supplement)}</p>
      <h3>从分析直接进入行动</h3>
      <ol>
        <li>把事故经过、现有原始材料和仍需鉴定的技术事项分别列清，不在申请书中写责任预测。</li>
        <li>当面提交两份，争取在留存件上取得收件日期、签名或盖章。</li>
        <li>同日或及时以中国邮政 EMS 寄送同一版本，运单写清文件名称、份数和页数。</li>
        <li>保存完整副本、封装照片、运单、付款凭证、物流轨迹及签收、拒收或退回记录。</li>
        <li>寄达后及时向承办部门核对是否入卷、委托事项是否完整，并记录答复。</li>
      </ol>
      <p class="supplement-note">当面 + EMS 是为了形成收件证据链的稳妥建议，
      不是申请成立必须同时完成的法定条件；属地已有线上入口时也应保存系统回执。</p>
    </section>
    """


def owner_task_rows(case: dict[str, Any], state: dict[str, Any]) -> list[list[Any]]:
    status_overrides = _task_status_overrides(case)
    rows: list[list[Any]] = []
    for task in sorted(
        state.get("rights_tasks", []),
        key=lambda item: (
            PRIORITY_RANK.get(item.get("priority"), 9),
            item.get("due_at") or "9999",
        ),
    ):
        task_id = str(task.get("task_id") or "")
        status = status_overrides.get(task_id, task.get("status", "draft"))
        rows.append(
            [
                PRIORITY_LABELS.get(task.get("priority"), "建议处理"),
                TASK_STATUS_LABELS.get(status, str(status)),
                task.get("title", ""),
                _task_due_label(case, task),
                task.get("objective", ""),
                "；".join(
                    str(item) for item in task.get("recommended_actions", [])[:3]
                ),
                RESPONSIBLE_LABELS.get(
                    task.get("responsible_role"),
                    "车主 + 保险理赔员",
                ),
            ]
        )
    return rows


def owner_task_choices(
    state: dict[str, Any], case: dict[str, Any] | None = None
) -> list[tuple[str, str]]:
    return [
        (str(task.get("title") or "未命名任务"), str(task.get("task_id")))
        for task in _active_tasks(
            state,
            _task_status_overrides(case or {}),
        )
        if task.get("task_id")
    ]


def owner_material_rows(case: dict[str, Any]) -> list[list[Any]]:
    providers: dict[str, str] = {}
    for event in case.get("audit_events", []):
        if event.get("event_type") != "collaboration_material_added":
            continue
        payload = event.get("payload", {})
        provider = str(payload.get("provider") or "提供方待确认")
        for source_id in payload.get("source_ids", []):
            providers[str(source_id)] = provider
    synthetic = str(case.get("metadata", {}).get("location", "")).startswith("合成")
    sources = owner_material_sources(case)
    role_totals: dict[str, int] = {}
    for source in sources:
        role = str(_enum_value(source.get("role") or "other"))
        role_totals[role] = role_totals.get(role, 0) + 1
    role_counts: dict[str, int] = {}
    rows: list[list[Any]] = []
    for source in sources:
        source_id = str(source.get("source_id") or "")
        raw_status = str(_enum_value(source.get("status") or ""))
        status = {
            "registered": "已保存，可查看",
            "processing": "正在读取内容",
            "parsed": "已读取，可用于分析",
            "failed": "读取失败，原文件仍保留",
        }.get(raw_status, "已保存，可查看")
        role = str(_enum_value(source.get("role") or "other"))
        role_label = MATERIAL_ROLE_LABELS.get(
            role,
            str(_enum_value(source.get("role") or "其他材料")),
        )
        role_counts[role] = role_counts.get(role, 0) + 1
        rows.append(
            [
                _material_display_name(
                    source,
                    role_label,
                    synthetic=synthetic and source_id not in providers,
                    sequence=role_counts[role],
                    total=role_totals[role],
                ),
                role_label,
                providers.get(
                    source_id,
                    "合成演示材料" if synthetic else "提供方待确认",
                ),
                status,
            ]
        )
    return rows


def owner_material_sources(case: dict[str, Any]) -> list[dict[str, Any]]:
    """Hide superseded Golden media while preserving table/file row alignment."""

    sources = list(case.get("sources", []))
    synthetic = str(case.get("metadata", {}).get("location", "")).startswith("合成")
    if not synthetic:
        return sources
    preferred: dict[str, dict[str, Any]] = {}
    for source in sources:
        role = str(_enum_value(source.get("role") or "other"))
        if role not in {"scene_photo", "dashcam_video"}:
            continue
        current = preferred.get(role)
        score = (
            "-synthetic." in str(source.get("original_name") or ""),
            int(source.get("size_bytes") or 0),
        )
        current_score = (
            (
                "-synthetic." in str(current.get("original_name") or ""),
                int(current.get("size_bytes") or 0),
            )
            if current
            else (False, 0)
        )
        if current is None or score > current_score:
            preferred[role] = source
    return [
        source
        for source in sources
        if str(_enum_value(source.get("role") or "other"))
        not in {"scene_photo", "dashcam_video"}
        or preferred.get(str(_enum_value(source.get("role") or "other"))) is source
    ]


def _material_display_name(
    source: dict[str, Any],
    role_label: str,
    *,
    synthetic: bool,
    sequence: int,
    total: int,
) -> str:
    original_name = str(source.get("original_name") or "未命名材料")
    if not synthetic:
        return original_name
    suffix = Path(original_name).suffix.lower()
    sequence_label = f" {sequence}" if total > 1 else ""
    return f"{role_label}（合成示例{sequence_label}）{suffix}"


def owner_communication_script(
    state: dict[str, Any],
    target: str,
    procedure_stage: str = "已收到鉴定意见并有异议",
) -> str:
    vehicle = state.get("vehicle_nature_result") or state.get(
        "vehicle_classification", {}
    )
    facts = _external_case_facts(state)
    fact_summary = _numbered_lines(
        facts,
        fallback="现有材料尚不足以形成可对外陈述的事故经过，请先补充原始证据。",
    )
    appraisal_gaps = _appraisal_gaps(vehicle)
    if target == "交管部门":
        return _traffic_management_application(
            procedure_stage=procedure_stage,
            fact_summary=fact_summary,
            appraisal_gaps=appraisal_gaps,
        )
    if target == "事故相对方":
        return (
            "关于本次交通事故事实与材料的沟通：\n\n"
            f"目前可回溯到案件材料的事项如下：\n{fact_summary}\n\n"
            "请共同核对行车记录仪原文件、现场图、道路信号、碰撞位置和车辆"
            "登记/技术材料。请将您方陈述及对应原始材料以书面或其他可留存"
            "方式提供，便于交管部门和双方逐项核验。\n\n"
            "本沟通只用于核对事实和证据，不包含事故责任或赔偿分配结论。\n\n"
            "本内容是沟通草稿，请核对事实后由车主本人发送。"
        )
    document_name = _appraisal_document_name(procedure_stage)
    gap_lines = _numbered_lines(
        appraisal_gaps,
        fallback="请先核对现有鉴定委托、完整鉴定意见及车辆原始材料。",
    )
    return (
        "请保险理赔员协助办理以下事项：\n\n"
        f"一、已核验的事故经过与材料\n{fact_summary}\n\n"
        f"二、协助车主准备{document_name}，核对收件单位、鉴定意见送达日期"
        "和适用期限；\n"
        "三、整理需补充核验的事项：\n"
        f"{gap_lines}\n\n"
        "四、建议鉴定事项应覆盖：最高设计车速/解除限速、整车质量、"
        "电机功率、电池电压、脚踏能力、实车与合格证及CCC一致性、改装情况；\n"
        "五、协助调取登记/号牌、完整鉴定意见、鉴定机构和鉴定人资质、"
        "委托事项及检材清单；\n"
        "六、协助车主采用当面提交与 EMS 邮寄留痕，保存收件凭证、"
        "文件清单、运单和物流轨迹；\n"
        "七、将补件要求、收件情况和下一截止时间写入案件记录。\n\n"
        "本协作内容只核对事实、证据和程序，不写入事故责任预测。\n\n"
        "请仅协助准备和核对，不代替车主自动对外提交。"
    )


def insurer_summary_html(case: dict[str, Any], state: dict[str, Any]) -> str:
    hypothesis, probability = _top_hypothesis(state)
    metadata = case.get("metadata", {})
    tasks = _active_tasks(state, _task_status_overrides(case))
    urgent = tasks[0].get("title") if tasks else "当前没有待办"
    gate = state.get("policy_gate", {})
    gate_label = {
        "pass": "校验通过",
        "pass_with_warnings": "可继续，但需人工核对",
        "block": "存在阻断项",
    }.get(str(gate.get("decision") or ""), "等待分析")
    probability_text = (
        f"{probability * 100:.1f}%" if probability is not None else "待分析"
    )
    return f"""
    <section class="insurer-summary">
      <span class="eyebrow">保险协作摘要</span>
      <h2>{escape(str(metadata.get("location") or "事故地点待补充"))}</h2>
      <div class="insurer-summary-grid">
        <article><span>当前责任方向</span><strong>{escape(hypothesis or "待分析")}</strong>
          <small>当前材料支持度 {escape(probability_text)}</small></article>
        <article><span>现在协助车主</span><strong>{escape(str(urgent))}</strong>
          <small>先保期限，再完善责任证据</small></article>
        <article><span>系统校验</span><strong>{escape(gate_label)}</strong>
          <small>任何文书仍由人工审核和提交</small></article>
      </div>
    </section>
    """


def insurer_task_rows(case: dict[str, Any], state: dict[str, Any]) -> list[list[Any]]:
    """Return only the three clearest actions an insurer should assist with."""
    rows: list[list[Any]] = []
    for task in _active_tasks(state, _task_status_overrides(case))[:3]:
        actions = task.get("recommended_actions", [])
        rows.append(
            [
                task.get("title", ""),
                _task_due_label(case, task),
                "；".join(str(item) for item in actions[:3]),
                _insurer_completion_standard(str(task.get("task_type") or "")),
            ]
        )
    return rows


def insurer_review_html(state: dict[str, Any]) -> str:
    gate = state.get("policy_gate", {})
    approval = state.get("approval_state", {})
    draft = state.get("review_application_draft", {})
    blocking = _unique_review_issues(
        [
            *gate.get("blocking_issues", []),
            *draft.get("blocking_fields", []),
            *draft.get("not_submittable_reasons", []),
        ]
    )
    blocking_items = (
        "".join(f"<li>{escape(item)}</li>" for item in blocking)
        or "<li>当前没有系统阻断项；仍需人工逐项核对事实、期限、收件单位和附件。</li>"
    )
    state_label = {
        "pending": "等待人工审核",
        "approved": "已批准供人工提交",
        "rejected": "已拒绝",
        "changes_requested": "需要修改",
    }.get(str(approval.get("state") or "pending"), "等待人工审核")
    document_name = {
        "road_accident_determination_review_application": "《道路交通事故认定复核申请书》",
    }.get(
        str(draft.get("document_type") or ""),
        "尚未生成可审核文书",
    )
    version = draft.get("document_version")
    version_text = f"v{version}" if version else "等待生成"
    fact_count = len(draft.get("facts", []))
    attachment_count = len(draft.get("attachments", []))
    legal_count = len(draft.get("legal_basis", []))
    return f"""
    <section class="insurer-review">
      <span class="eyebrow">文书审核 · 当前审核对象</span>
      <h2>{escape(document_name)}草稿 · {escape(version_text)}</h2>
      <p><strong>{escape(state_label)}</strong>。这里审核的是复核申请草稿本身，
      不是附件文件名列表，也不是对事故责任作最终认定。</p>
      <div class="insurer-summary-grid">
        <article><span>事实引用</span><strong>{fact_count} 项</strong>
          <small>逐项回溯原始案件材料</small></article>
        <article><span>附件索引</span><strong>{attachment_count} 份</strong>
          <small>核对是否真实存在、清晰且与正文一致</small></article>
        <article><span>程序依据</span><strong>{legal_count} 条</strong>
          <small>只采用已核验的现行官方文本</small></article>
      </div>
      <h3>理赔员具体审核什么</h3>
      <ol>
        <li>事故经过是否忠实于视频、现场图、认定书等原始材料；</li>
        <li>收件单位、认定书编号和实际送达日期是否准确；</li>
        <li>正文引用的每份证据是否已经随文整理，缺件是否明确标注；</li>
        <li>请求事项是否具体，是否仍需车主或法律人员修改。</li>
      </ol>
      <h3>仍需补齐或确认</h3>
      <ul>{blocking_items}</ul>
      <p>审核通过后只会标记为 <code>approved_for_manual_submission</code>；
      文书仍由车主核对签名并人工递交，系统不会自动发送。</p>
    </section>
    """


def _traffic_management_application(
    *,
    procedure_stage: str,
    fact_summary: str,
    appraisal_gaps: list[str],
) -> str:
    title = _appraisal_document_name(procedure_stage)
    if procedure_stage == "交管部门尚未委托鉴定":
        legal_basis = (
            "依据《道路交通事故处理程序规定》第四十九条、第五十四条，"
            "请求贵单位审查车辆属性争议并依法委托具备相应能力的鉴定机构。"
        )
        request = (
            "对涉案两轮车辆是否符合事故发生时有效的电动自行车强制性国家标准、"
            "是否存在解除限速或其他改装，以及车辆属性相关技术事实进行检验、鉴定。"
        )
    elif procedure_stage == "原鉴定遗漏事项或取得新材料":
        legal_basis = (
            "原委托鉴定事项存在遗漏或现已取得新的鉴定材料，现请求贵单位"
            "审查是否补充委托鉴定；如依法应按重新鉴定程序办理，请同时告知"
            "申请期限和办理方式。"
        )
        request = (
            "将原鉴定未覆盖的车辆参数、实车改装状态及新取得的合格证、CCC、"
            "登记材料纳入补充鉴定范围，并出具完整书面意见。"
        )
    elif procedure_stage == "已进入法院诉讼":
        title = "《司法鉴定申请书》（提交受理法院）"
        legal_basis = (
            "依据《最高人民法院关于民事诉讼证据的若干规定》第三十条至"
            "第三十二条，请求人民法院在指定期间内审查鉴定申请并依法确定鉴定人。"
        )
        request = (
            "对涉案两轮车辆的技术参数、产品一致性、改装情况及与车辆属性判断"
            "相关的专门性事实进行鉴定。"
        )
    else:
        legal_basis = (
            "依据《道路交通事故处理程序规定》第五十六条、第五十七条及"
            "第一百一十二条，本人在鉴定意见送达之日起三个工作日内提出"
            "书面异议，请求原办案单位另行委托鉴定机构重新检验、鉴定。"
        )
        request = (
            "暂缓直接采信原鉴定意见，另行委托机构对遗漏或依据不足的车辆参数、"
            "实车状态和产品一致性重新检验、鉴定。"
        )
    recipient = (
        "________人民法院"
        if procedure_stage == "已进入法院诉讼"
        else "________公安机关交通管理部门（事故处理承办部门）"
    )
    gap_lines = _numbered_lines(
        appraisal_gaps,
        fallback="请承办单位结合实车、登记、产品和原鉴定材料确定鉴定范围。",
    )
    return (
        f"{title}\n\n"
        "申请人：________\n事故编号：________\n"
        f"收件单位：{recipient}\n\n"
        f"一、事故经过与现有材料\n{fact_summary}\n\n"
        "以下内容仅用于申请事实核验和检验、鉴定，不包含事故责任或赔偿分配结论。\n\n"
        f"二、请求事项\n{request}\n\n"
        "三、现有证据缺口\n"
        f"{gap_lines}\n\n"
        "四、建议明确写入委托书的鉴定事项\n"
        "1. 最高设计车速、超过25km/h时电机是否停止动力输出及解除限速情况；\n"
        "2. 整车质量、电机额定连续输出功率、蓄电池标称电压；\n"
        "3. 脚踏骑行能力、车辆外形尺寸及事故发生时的实车状态；\n"
        "4. 实车与产品合格证、CCC车型的一致性；\n"
        "5. 是否更换控制器、电池或实施其他影响车辆性能的改装；\n"
        "6. 鉴定所依据的标准版本、检材、测试方法、原始数据和分析过程。\n\n"
        f"五、法律与程序依据\n{legal_basis}\n\n"
        "六、附件\n车辆照片、登记/号牌材料、合格证/CCC、原鉴定意见及"
        "送达凭证、新取得的检测或维修材料（按实际具备情况列明）。\n\n"
        "七、递交与证据固定建议\n"
        "1. 打印两份，当面提交至承办部门；请在留存件上注明收件日期、"
        "收件人并签名或盖章，或取得材料接收清单/回执；\n"
        "2. 同日或及时将同一版本通过中国邮政 EMS 寄至该单位官方公布地址，"
        "收件人写明事故处理承办部门并注明事故编号；\n"
        "3. 运单“内件品名”写明本申请书名称、附件目录、份数和页数，"
        "封装前拍摄申请全文、附件目录和邮件外观；\n"
        "4. 保存留存副本、EMS 运单和付款凭证、完整物流轨迹，以及签收、"
        "拒收或退回记录；寄达后及时书面或录音确认是否收件入卷；\n"
        "5. 当面 + EMS 属于收件留痕建议，并非申请成立必须同时完成的"
        "法定条件；如承办机关有官方线上入口，同时保存系统回执。\n\n"
        "申请人签名：________    日期：________\n\n"
        "提示：请先核对事故阶段、送达日期、承办单位和属地要求；本草稿不会自动提交。"
    )


def _appraisal_document_name(procedure_stage: str) -> str:
    if procedure_stage == "交管部门尚未委托鉴定":
        return "《车辆属性检验、鉴定申请书》"
    if procedure_stage == "原鉴定遗漏事项或取得新材料":
        return "《补充鉴定申请书》"
    if procedure_stage == "已进入法院诉讼":
        return "《司法鉴定申请书》（提交受理法院）"
    return "《重新检验、鉴定申请书》"


def _has_existing_appraisal(vehicle: dict[str, Any]) -> bool:
    return any(
        factor.get("fact_ids") or factor.get("evidence_ids")
        for factor in vehicle.get("appraisal_factors", [])
        if isinstance(factor, dict)
    )


def _external_case_facts(state: dict[str, Any], *, limit: int = 7) -> list[str]:
    """Return evidence-backed facts without exporting liability predictions."""
    capsule = state.get("case_capsule") or {}
    candidates = capsule.get("confirmed_facts", []) if isinstance(capsule, dict) else []
    if not candidates:
        candidates = (state.get("review_application_draft") or {}).get("facts", [])
    result: list[str] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        statement = str(item.get("statement") or item.get("text") or "").strip()
        contains_ratio_claim = "责任" in statement and any(
            marker in statement for marker in ("%", "％", "比例")
        )
        if (
            not statement
            or contains_ratio_claim
            or any(word in statement for word in EXTERNAL_FACT_EXCLUSIONS)
        ):
            continue
        status = str(item.get("status") or item.get("fact_status") or "").lower()
        if status in {"rejected"}:
            continue
        if status in {"unverified", "disputed"} and not statement.startswith("待核实"):
            statement = f"待核实：{statement}"
        fact_id = str(item.get("fact_id") or "")
        evidence_ids = [
            str(value)
            for value in (item.get("source_node_ids") or item.get("evidence_ids") or [])
            if value
        ]
        references = [value for value in [fact_id, *evidence_ids[:2]] if value]
        if references:
            statement = f"{statement}【{' / '.join(references)}】"
        if statement not in result:
            result.append(statement)
        if len(result) >= limit:
            break
    return result


def _appraisal_gaps(vehicle: dict[str, Any], *, limit: int = 8) -> list[str]:
    result: list[str] = []
    for item in vehicle.get("parameter_comparison", []):
        if not isinstance(item, dict) or item.get("status") not in {
            "unknown",
            "conflicting",
        }:
            continue
        label = str(item.get("display_name") or item.get("parameter") or "").strip()
        if label and label not in result:
            result.append(label)
    for item in vehicle.get("missing_evidence", []):
        if isinstance(item, dict):
            label = str(item.get("reason") or item.get("category") or "").strip()
        else:
            label = str(item).strip()
        if label and label not in result:
            result.append(label)
    return result[:limit]


def _numbered_lines(values: list[str], *, fallback: str) -> str:
    selected = [str(value).strip() for value in values if str(value).strip()]
    if not selected:
        return f"1. {fallback}"
    return "\n".join(
        f"{index}. {value}" for index, value in enumerate(selected, start=1)
    )


def _unique_review_issues(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = _review_issue_text(value)
        if text and text not in result:
            result.append(text)
    return result


def _review_issue_text(value: Any) -> str:
    raw = _issue_text(value).strip()
    for prefix in ("缺少或未确认：", "缺少或未确认:"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :].strip()
            break
    if raw in REVIEW_FIELD_LABELS:
        return f"请补充或确认：{REVIEW_FIELD_LABELS[raw]}"
    if raw.startswith(("NODE-", "SRC-", "FACT-", "LAW-")):
        return "请核对对应的事实、证据附件和法律依据是否真实存在且能够打开"
    return raw


def _issue_text(value: Any) -> str:
    if isinstance(value, dict):
        return str(
            value.get("message")
            or value.get("required_action")
            or value.get("code")
            or value
        )
    return str(value)


def _insurer_completion_standard(task_type: str) -> str:
    return {
        "prepare_accident_review": "送达日期已核对，申请草稿已交车主确认",
        "appraisal_objection_or_reappraisal": "送达凭证、异议理由和鉴定事项齐全",
        "preserve_dashcam_original": "原文件、原设备或存储卡及哈希记录齐全",
        "request_case_file_copy": "申请范围和交管部门收件记录已保存",
        "verify_vehicle_nature": "申请书、车辆参数清单和现有证明材料齐全",
        "collect_scene_and_cctv": "保存或调取申请及其回执已留存",
    }.get(task_type, "材料和沟通结果已写入案件记录")


def _case_status(state: dict[str, Any]) -> tuple[str, str]:
    if not state:
        return (
            "等待分析",
            "材料已保存后，点击“分析 / 更新当前事故”即可继续。",
        )
    current = str(state.get("current_node") or "")
    if state.get("errors"):
        return (
            "需要恢复分析",
            "已完成的结果会保留，可在专业工作台中查看失败原因并恢复。",
        )
    if current == "human_approval":
        return (
            "分析完成，等待您确认下一步",
            "责任方案和维权任务已生成，请先处理最紧急的行动。",
        )
    progress = float(state.get("progress") or 0)
    return (
        f"正在分析（{progress * 100:.0f}%）",
        "系统正在整理证据、责任方案和维权期限。",
    )


def _top_hypothesis(state: dict[str, Any]) -> tuple[str | None, float | None]:
    probabilities = state.get("responsibility_probabilities", {})
    if not probabilities:
        return None, None
    label, value = max(probabilities.items(), key=lambda item: float(item[1]))
    return str(label), float(value)


def _plain_evidence(case: dict[str, Any], *, limit: int) -> list[str]:
    preferred = [
        item
        for item in case.get("facts", [])
        if str(_enum_value(item.get("status"))) in {"verified", "confirmed"}
    ]
    if not preferred:
        preferred = list(case.get("facts", []))
    preferred.sort(key=lambda item: float(item.get("confidence") or 0), reverse=True)
    result: list[str] = []
    for item in preferred:
        statement = str(item.get("statement") or "").strip()
        if statement and statement not in result:
            result.append(statement)
        if len(result) >= limit:
            break
    return result


def _active_tasks(
    state: dict[str, Any],
    status_overrides: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    overrides = status_overrides or {}
    return sorted(
        [
            item
            for item in state.get("rights_tasks", [])
            if overrides.get(
                str(item.get("task_id") or ""),
                item.get("status"),
            )
            not in {"completed", "dismissed"}
        ],
        key=lambda item: (
            PRIORITY_RANK.get(item.get("priority"), 9),
            item.get("due_at") or "9999",
        ),
    )


def _task_status_overrides(case: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for event in case.get("audit_events", []):
        if event.get("event_type") != "owner_task_status_updated":
            continue
        payload = event.get("payload", {})
        task_id = payload.get("task_id")
        if task_id:
            result[str(task_id)] = str(payload.get("status") or "completed")
    return result


def _next_deadline(state: dict[str, Any]) -> dict[str, str] | None:
    deadlines = sorted(
        [
            item
            for item in state.get("deadlines", [])
            if item.get("status") not in {"completed", "cancelled"}
        ],
        key=lambda item: item.get("due_at") or "9999",
    )
    if not deadlines:
        return None
    item = deadlines[0]
    matter = {
        "accident_determination_review": "事故认定复核",
        "appraisal_review": "鉴定异议",
    }.get(str(item.get("matter_type")), "权益事项")
    return {"matter": matter, "due": _friendly_due(item.get("due_at"))}


def _friendly_datetime(value: Any) -> str:
    if not value:
        return "时间待补充"
    try:
        dt = datetime.fromisoformat(str(value))
        return dt.astimezone(SHANGHAI).strftime("%Y年%m月%d日 %H:%M")
    except ValueError:
        return str(value)


def _friendly_due(value: Any) -> str:
    if not value:
        return "暂无明确期限"
    try:
        due = datetime.fromisoformat(str(value))
        if due.tzinfo is None:
            due = due.replace(tzinfo=SHANGHAI)
        due = due.astimezone(SHANGHAI)
        now = datetime.now(SHANGHAI)
        if due < now:
            prefix = "已到期 · "
        elif (due - now).total_seconds() <= 72 * 3600:
            prefix = "即将到期 · "
        else:
            prefix = ""
        return f"{prefix}{due:%m月%d日 %H:%M}"
    except ValueError:
        return str(value)


def _task_due_label(case: dict[str, Any], task: dict[str, Any]) -> str:
    metadata = case.get("metadata", {})
    if metadata.get("case_id") == GOLDEN_CASE_ID and task.get("due_at"):
        return f"截止时间：{_friendly_due(GOLDEN_ACTION_DUE_AT)}"
    return _friendly_due(task.get("due_at"))


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value
