"""Pure view-model functions for Gradio and regression tests."""

from __future__ import annotations

import html
import json
from typing import Any

UI_NODES = (
    ("intake", "intake_complete"),
    ("evidence", "evidence_ready"),
    ("legal_retrieval", "legal_retrieval"),
    ("vehicle_nature", "vehicle_nature"),
    ("liability", "liability"),
    ("rights_workflow", "rights_workflow"),
    ("verifier", "verifier"),
    ("human_approval", "human_approval"),
)


def progress_rows(state: dict[str, Any]) -> list[list[Any]]:
    results = state.get("node_results", {})
    rows: list[list[Any]] = []
    for label, backend_name in UI_NODES:
        result = results.get(backend_name)
        if not result:
            rows.append([label, "pending", "", "", 0, "", ""])
            continue
        raw_status = result.get("status", "pending")
        warnings = result.get("warnings", [])
        if raw_status == "succeeded" and warnings:
            display_status = "warning"
        else:
            display_status = raw_status
        if (
            label == "human_approval"
            and state.get("policy_gate", {}).get("decision") == "block"
        ):
            display_status = "blocked"
        outputs = result.get("outputs", {})
        summary = _summary(outputs)
        reason = "; ".join(result.get("errors", []))
        rows.append(
            [
                label,
                display_status,
                result.get("started_at", ""),
                result.get("finished_at", ""),
                result.get("retry_count", 0),
                summary,
                reason,
            ]
        )
    return rows


def progress_overview(
    state: dict[str, Any], *, recoverable: bool, next_nodes: list[str]
) -> dict[str, Any]:
    results = state.get("node_results", {})
    failed = [
        name for name, result in results.items() if result.get("status") == "failed"
    ]
    return {
        "case_id": state.get("case_id"),
        "thread_id": state.get("thread_id"),
        "progress_percent": round(float(state.get("progress", 0.0)) * 100, 1),
        "current_node": state.get("current_node", "pending"),
        "latest_checkpoint": state.get("current_node", "pending"),
        "recoverable": recoverable,
        "next_nodes": next_nodes,
        "failed_nodes": failed,
        "warning_count": len(state.get("warnings", [])),
        "error_count": len(state.get("errors", [])),
    }


def progress_overview_html(overview: dict[str, Any]) -> str:
    """Render checkpoint status without mounting an expandable JSON tree."""

    progress = overview.get("progress_percent", 0)
    try:
        progress_label = f"{float(progress):.0f}%"
    except (TypeError, ValueError):
        progress_label = "0%"
    return (
        '<section class="diagnostic-summary">'
        '<div class="diagnostic-heading"><div><span class="eyebrow">LangGraph Workflow</span>'
        "<h3>执行状态与 Checkpoint</h3></div>"
        f'<div class="diagnostic-verdict"><strong>{_html(progress_label)}</strong>'
        f"<span>{_html(overview.get('current_node') or '未运行')}</span></div></div>"
        '<div class="diagnostic-grid">'
        '<article class="diagnostic-card"><span>当前节点</span>'
        f"<strong>{_html(overview.get('current_node') or '未运行')}</strong>"
        f"<small>下一节点：{_html(', '.join(overview.get('next_nodes', [])) or '等待启动')}</small></article>"
        '<article class="diagnostic-card"><span>Thread / Checkpoint</span>'
        f"<strong>{_html(overview.get('thread_id') or '尚未创建')}</strong>"
        f"<small>可恢复：{_html(overview.get('recoverable', False))}</small></article>"
        '<article class="diagnostic-card"><span>运行质量</span>'
        f"<strong>警告 {_html(overview.get('warning_count', 0))} · 错误 {_html(overview.get('error_count', 0))}</strong>"
        f"<small>失败节点：{_html(', '.join(overview.get('failed_nodes', [])) or '无')}</small></article>"
        '</div><div class="diagnostic-footer">完整 checkpoint 状态保留在后端与导出报告中，浏览器仅显示录屏所需摘要。</div>'
        "</section>"
    )


def progress_table_html(state: dict[str, Any]) -> str:
    """Render the eight workflow nodes as a compact table."""

    status_labels = {
        "pending": "等待",
        "running": "运行中",
        "succeeded": "完成",
        "warning": "完成（有提示）",
        "failed": "失败",
        "blocked": "已阻断",
    }
    body = []
    for row in progress_rows(state):
        body.append(
            "<tr>"
            f"<td><strong>{_html(row[0])}</strong></td>"
            f"<td>{_html(status_labels.get(str(row[1]), row[1]))}</td>"
            f"<td>{_html(row[5] or '等待运行')}</td>"
            f"<td>{_html(row[6] or '—')}</td>"
            "</tr>"
        )
    return (
        '<section class="diagnostic-summary"><div class="diagnostic-table-wrap">'
        '<table class="diagnostic-table"><thead><tr><th>节点</th><th>状态</th><th>摘要</th><th>异常</th></tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table></div></section>"
    )


def evidence_timeline_rows(
    case: dict[str, Any],
    *,
    phase: str = "全部",
    source_filter: str = "全部",
    status_filter: str = "全部",
) -> list[list[Any]]:
    nodes = {item["node_id"]: item for item in case.get("evidence_nodes", [])}
    sources = {item["source_id"]: item for item in case.get("sources", [])}
    conflicts_by_fact: dict[str, list[str]] = {}
    for conflict in case.get("conflicts", []):
        for fact_id in conflict.get("fact_ids", []):
            conflicts_by_fact.setdefault(fact_id, []).append(
                conflict.get("conflict_id", "")
            )
    events = case.get("timeline", [])
    phase_by_node: dict[str, str] = {}
    for index, event in enumerate(events):
        selected_phase = _phase(event.get("label", ""), index, len(events))
        for node_id in event.get("source_node_ids", []):
            phase_by_node[node_id] = selected_phase

    rows: list[list[Any]] = []
    for fact in case.get("facts", []):
        node_ids = fact.get("source_node_ids", [])
        linked_nodes = [nodes.get(node_id, {}) for node_id in node_ids]
        source_ids = sorted(
            {node.get("source_id") for node in linked_nodes if node.get("source_id")}
        )
        selected_phase = next(
            (
                phase_by_node[node_id]
                for node_id in node_ids
                if node_id in phase_by_node
            ),
            "阶段不确定",
        )
        display_status = {
            "verified": "confirmed",
            "unverified": "unverified",
            "disputed": "disputed",
            "rejected": "rejected",
        }.get(fact.get("status", ""), fact.get("status", "unverified"))
        source_roles = sorted(
            {
                _enum_value(sources[source_id]["role"])
                for source_id in source_ids
                if source_id in sources
            }
        )
        if phase != "全部" and selected_phase != phase:
            continue
        if source_filter != "全部" and source_filter not in source_roles:
            continue
        if status_filter != "全部" and display_status != status_filter:
            continue
        locator = [node.get("locator", {}) for node in linked_nodes if node]
        rows.append(
            [
                selected_phase,
                fact.get("fact_id"),
                ", ".join(source_ids),
                ", ".join(node_ids),
                json.dumps(locator, ensure_ascii=False, default=str),
                fact.get("statement"),
                round(float(fact.get("confidence", 0.0)), 3),
                display_status,
                ", ".join(conflicts_by_fact.get(fact.get("fact_id"), [])),
            ]
        )
    return rows


def evidence_timeline_html(
    case: dict[str, Any],
    *,
    phase: str = "全部",
    source_filter: str = "全部",
    status_filter: str = "全部",
) -> str:
    """Render a bounded evidence timeline without a large editable grid."""

    rows = evidence_timeline_rows(
        case,
        phase=phase,
        source_filter=source_filter,
        status_filter=status_filter,
    )
    body = []
    for row in rows[:20]:
        body.append(
            "<tr>"
            f"<td>{_html(row[0])}</td>"
            f"<td><strong>{_html(row[1])}</strong></td>"
            f"<td>{_html(row[5])}</td>"
            f"<td>{_html(row[2])}</td>"
            f"<td>{_html(row[7])}</td>"
            f"<td>{_html(row[8] or '—')}</td>"
            "</tr>"
        )
    if not body:
        body.append('<tr><td colspan="6">当前筛选条件下没有事实。</td></tr>')
    conflict_count = sum(1 for row in rows if row[8])
    return (
        '<section class="diagnostic-summary">'
        '<div class="diagnostic-heading"><div><span class="eyebrow">Evidence Graph</span>'
        "<h3>证据时间线与冲突</h3></div>"
        f'<div class="diagnostic-verdict"><strong>{len(rows)} 条事实</strong>'
        f"<span>{conflict_count} 条关联冲突</span></div></div>"
        '<div class="diagnostic-table-wrap"><table class="diagnostic-table">'
        "<thead><tr><th>阶段</th><th>Fact ID</th><th>事实</th><th>Source ID</th><th>状态</th><th>冲突</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
        '<div class="diagnostic-footer">最多显示 20 条；原始文件通过下方“查看原始证据”按需加载。</div>'
        "</section>"
    )


def evidence_preview_choices(case: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        (
            f"{item['source_id']} · {item['original_name']} · {item['role']}",
            item["source_id"],
        )
        for item in case.get("sources", [])
    ]


def liability_view(state: dict[str, Any]) -> dict[str, Any]:
    vehicle = state.get("vehicle_nature_result") or state.get(
        "vehicle_classification", {}
    )
    liability = state.get("liability_result", {})
    return {
        "vehicle_nature": {
            **vehicle,
            "parameter_comparison": state.get("parameter_comparison", []),
        },
        "accident_responsibility": liability.get(
            "accident_responsibility",
            state.get("accident_responsibility", {}),
        ),
        "civil_compensation_allocation": liability.get(
            "civil_compensation_allocation",
            state.get("civil_compensation_allocation", {}),
        ),
        "insurance_payment_estimate": liability.get(
            "insurance_payment_estimate",
            state.get(
                "insurance_payment_estimate",
                {"status": "insufficient_data"},
            ),
        ),
        "compensation_regime": liability.get("compensation_regime")
        or state.get("compensation_route_result", {}).get("compensation_regime")
        or "pending_vehicle_classification",
        "violation_matrix": state.get("violation_matrix", []),
        "causation_matrix": state.get("causation_matrix", []),
        "liability_hypotheses": state.get("liability_hypotheses", []),
        "responsibility_probabilities": state.get("responsibility_probabilities", {}),
        "counterfactual_analysis": state.get("counterfactual_analysis", []),
        "verifier": state.get("verifier_results", {}),
        "policy_gate": state.get("policy_gate", {}),
        "citation_chain": {
            "fact_ids": _collect_ids(state, "fact_ids"),
            "evidence_ids": _collect_ids(state, "evidence_ids"),
            "law_ids": _collect_ids(state, "law_ids")
            or [
                item.get("law_id")
                for item in state.get("legal_citations", [])
                if item.get("law_id")
            ],
        },
    }


def liability_summary_html(state: dict[str, Any]) -> str:
    """Render the liability result without mounting the full nested JSON tree."""

    vehicle = state.get("vehicle_nature_result") or state.get(
        "vehicle_classification", {}
    )
    if not vehicle and not state.get("liability_hypotheses"):
        return _empty_diagnostic("尚未生成车辆属性与责任分析。")

    classification_labels = {
        "non_motor_vehicle": "非机动车",
        "suspected_motor_vehicle": "疑似机动车",
        "motor_vehicle": "机动车",
        "insufficient_evidence": "证据不足",
    }
    status_labels = {
        "compliant": "符合",
        "non_compliant": "不符合",
        "unknown": "待补证",
        "conflicting": "存在冲突",
        "not_applicable": "不适用",
    }
    classification = str(vehicle.get("classification") or "insufficient_evidence")
    confidence = _percent(vehicle.get("confidence"))
    conclusion_status = str(vehicle.get("conclusion_status") or "pending")

    comparison = state.get("parameter_comparison") or vehicle.get(
        "parameter_comparison", []
    )
    parameter_rows = []
    for item in comparison[:12]:
        raw_status = str(item.get("status") or "unknown")
        parameter_rows.append(
            "<tr>"
            f"<td><strong>{_html(item.get('display_name') or item.get('parameter'))}</strong></td>"
            f"<td>{_html(_display_value(item.get('observed_value')))}</td>"
            f"<td>{_html(item.get('standard_requirement'))}</td>"
            f'<td><span class="diagnostic-pill status-{_html(raw_status)}">'
            f"{_html(status_labels.get(raw_status, raw_status))}</span></td>"
            "</tr>"
        )
    if not parameter_rows:
        parameter_rows.append('<tr><td colspan="4">暂无参数比较结果。</td></tr>')

    missing_items = []
    for item in vehicle.get("missing_evidence", [])[:8]:
        priority = item.get("priority") or "待补充"
        reason = item.get("reason") or item.get("category") or "未说明"
        missing_items.append(
            f"<li><strong>{_html(priority)}</strong> · {_html(reason)}</li>"
        )
    missing_html = "".join(missing_items) or "<li>当前未列出阻断性缺失材料。</li>"

    hypotheses = sorted(
        state.get("liability_hypotheses", []),
        key=lambda item: float(item.get("probability") or 0.0),
        reverse=True,
    )
    probability_map = state.get("responsibility_probabilities", {})
    hypothesis_cards = []
    for index, item in enumerate(hypotheses[:4], start=1):
        probability = item.get("probability")
        if probability is None:
            probability = probability_map.get(item.get("label"))
        missing = item.get("missing_evidence", [])
        missing_note = (
            f"待补证：{_html('；'.join(str(value) for value in missing[:3]))}"
            if missing
            else "当前方案没有新增缺失项"
        )
        hypothesis_cards.append(
            '<article class="diagnostic-card hypothesis-card">'
            f'<div class="diagnostic-rank">方案 {index}</div>'
            f"<h4>{_html(item.get('label') or item.get('hypothesis_id'))}</h4>"
            f'<div class="probability">{_percent(probability)}</div>'
            f"<p>{_html(item.get('explanation') or '仅作为可比较的工程假设，不是最终定责。')}</p>"
            f"<small>{missing_note}</small>"
            "</article>"
        )
    if not hypothesis_cards:
        hypothesis_cards.append(
            '<article class="diagnostic-card"><p>暂无责任假设。</p></article>'
        )

    liability = state.get("liability_result", {})
    accident = liability.get("accident_responsibility") or state.get(
        "accident_responsibility", {}
    )
    civil = liability.get("civil_compensation_allocation") or state.get(
        "civil_compensation_allocation", {}
    )
    insurance = liability.get("insurance_payment_estimate") or state.get(
        "insurance_payment_estimate", {"status": "insufficient_data"}
    )
    shares = []
    for item in civil.get("share_ranges", [])[:4]:
        shares.append(
            f"{_html(item.get('party'))}: {_percent(item.get('minimum'))}–"
            f"{_percent(item.get('maximum'))}"
        )
    selected_id = accident.get("selected_hypothesis_id")
    selected_label = next(
        (
            item.get("label")
            for item in hypotheses
            if item.get("hypothesis_id") == selected_id
        ),
        selected_id or "保留多方案",
    )
    insurance_value = (
        f"{insurance.get('currency', 'CNY')} {insurance.get('estimated_amount')}"
        if insurance.get("status") == "available"
        else "材料不足，不生成金额"
    )
    gate = state.get("policy_gate", {})

    return (
        '<section class="diagnostic-summary">'
        '<div class="diagnostic-heading"><div><span class="eyebrow">Vehicle Agent</span>'
        "<h3>车辆属性与技术参数</h3></div>"
        f'<div class="diagnostic-verdict"><strong>{_html(classification_labels.get(classification, classification))}</strong>'
        f"<span>置信度 {confidence} · {_html(conclusion_status)}</span></div></div>"
        '<div class="diagnostic-table-wrap"><table class="diagnostic-table">'
        "<thead><tr><th>参数</th><th>观测值</th><th>标准要求</th><th>状态</th></tr></thead>"
        f"<tbody>{''.join(parameter_rows)}</tbody></table></div>"
        '<div class="diagnostic-missing"><h4>冲突 / 缺失材料</h4>'
        f"<ul>{missing_html}</ul></div>"
        '<div class="diagnostic-heading"><div><span class="eyebrow">Liability Agent</span>'
        '<h3>责任假设与概率</h3></div><span class="diagnostic-note">概率用于方案比较，不是司法结论</span></div>'
        f'<div class="hypothesis-grid">{"".join(hypothesis_cards)}</div>'
        '<div class="diagnostic-heading"><div><span class="eyebrow">Separated Outcomes</span>'
        "<h3>三对象拆分</h3></div></div>"
        '<div class="diagnostic-grid">'
        '<article class="diagnostic-card"><span>事故责任</span>'
        f"<strong>{_html(selected_label)}</strong><small>{_html(accident.get('status') or 'pending')}</small></article>"
        '<article class="diagnostic-card"><span>民事赔偿</span>'
        f"<strong>{_html('；'.join(shares) or civil.get('regime') or '待核验')}</strong>"
        f"<small>{_html(civil.get('status') or 'pending')}</small></article>"
        '<article class="diagnostic-card"><span>保险支付</span>'
        f"<strong>{_html(insurance_value)}</strong><small>{_html(insurance.get('status') or 'pending')}</small></article>"
        '</div><div class="diagnostic-footer">'
        f"Policy Gate：<strong>{_html(gate.get('decision') or 'pending')}</strong>。"
        "完整 Fact / Evidence / Law 引用链保留在导出报告中，不在浏览器展开大型 JSON。"
        "</div></section>"
    )


def rights_view(state: dict[str, Any]) -> dict[str, Any]:
    priority_rank = {
        "critical": 0,
        "high": 1,
        "medium": 2,
        "low": 3,
        "P0": 0,
        "P1": 1,
        "P2": 2,
    }
    tasks = sorted(
        state.get("rights_tasks", []),
        key=lambda item: (
            priority_rank.get(item.get("priority"), 9),
            item.get("due_at") or "9999",
        ),
    )
    deadlines = sorted(
        state.get("deadlines", []),
        key=lambda item: item.get("due_at") or "9999",
    )
    return {
        "delivery_date": state.get("delivery_date_result", {}),
        "appraisal_delivery_date": state.get("appraisal_delivery_date_result", {}),
        "deadlines": deadlines,
        "tasks": tasks,
        "evidence_collection_plan": state.get("evidence_collection_plan", []),
        "review_application_draft": state.get("review_application_draft", {}),
    }


def rights_summary_html(state: dict[str, Any]) -> str:
    """Render deadlines and tasks as a small recording-friendly view."""

    view = rights_view(state)
    if not view["deadlines"] and not view["tasks"]:
        return _empty_diagnostic("尚未生成权益期限与行动任务。")
    deadline_rows = []
    for item in view["deadlines"][:8]:
        deadline_rows.append(
            "<tr>"
            f"<td>{_html(item.get('name') or item.get('deadline_type') or item.get('task_type'))}</td>"
            f"<td><strong>{_html(item.get('due_at') or item.get('deadline'))}</strong></td>"
            f"<td>{_html(item.get('status') or item.get('confidence') or '已计算')}</td>"
            "</tr>"
        )
    task_cards = []
    for item in view["tasks"][:8]:
        task_cards.append(
            '<article class="diagnostic-card">'
            f"<span>{_html(item.get('priority') or 'P2')} · {_html(item.get('status') or 'pending')}</span>"
            f"<strong>{_html(item.get('title') or item.get('task') or item.get('task_type'))}</strong>"
            f"<small>{_html(item.get('due_at') or item.get('deadline') or '无固定日期')}</small>"
            "</article>"
        )
    draft = view.get("review_application_draft", {})
    deadline_body = "".join(deadline_rows) or (
        '<tr><td colspan="3">暂无期限。</td></tr>'
    )
    return (
        '<section class="diagnostic-summary">'
        '<div class="diagnostic-heading"><div><span class="eyebrow">Rights Workflow</span>'
        "<h3>期限与行动任务</h3></div></div>"
        '<div class="diagnostic-table-wrap"><table class="diagnostic-table">'
        "<thead><tr><th>期限</th><th>截止时间</th><th>状态</th></tr></thead>"
        f"<tbody>{deadline_body}</tbody></table></div>"
        f'<div class="diagnostic-grid">{"".join(task_cards)}</div>'
        '<div class="diagnostic-footer">'
        f"当前草稿：<strong>{_html(draft.get('title') or draft.get('document_type') or '尚未生成')}</strong> · "
        f"状态 {_html(draft.get('status') or draft.get('document_status') or 'draft')}。"
        "完整任务证据与规则依据保留在导出报告中。"
        "</div></section>"
    )


def approval_view(state: dict[str, Any]) -> dict[str, Any]:
    gate = state.get("policy_gate", {})
    draft = state.get("review_application_draft", {})
    approval = state.get("approval_state", {})
    blocked_reasons = [
        *gate.get("blocking_issues", []),
        *draft.get("blocking_fields", []),
        *draft.get("not_submittable_reasons", []),
    ]
    return {
        "draft": draft,
        "key_facts": draft.get("facts", []),
        "responsibility_conclusion": state.get("accident_responsibility", {}),
        "policy_gate": gate,
        "risk_warnings": [
            *gate.get("warnings", []),
            *draft.get("risk_language_findings", []),
        ],
        "approval": approval,
        "can_approve": (
            gate.get("decision") != "block"
            and not draft.get("blocking_fields")
            and not draft.get("not_submittable_reasons")
            and bool(draft)
        ),
        "blocked_reasons": blocked_reasons,
        "display_document_status": (
            "approved_for_manual_submission"
            if approval.get("state") == "approved"
            else "draft"
        ),
    }


def approval_summary_html(state: dict[str, Any]) -> str:
    """Render the approval gate without expanding the complete draft body."""

    view = approval_view(state)
    if not view["draft"] and not view["policy_gate"]:
        return _empty_diagnostic("尚未生成待审批草稿。")
    gate = view["policy_gate"]
    approval = view["approval"]
    issues = [*view["blocked_reasons"], *view["risk_warnings"]]
    issue_items = "".join(f"<li>{_html(item)}</li>" for item in issues[:10])
    if not issue_items:
        issue_items = "<li>当前没有阻断项；仍需人工核对事实、附件和收件信息。</li>"
    return (
        '<section class="diagnostic-summary">'
        '<div class="diagnostic-heading"><div><span class="eyebrow">Verifier + Human Approval</span>'
        "<h3>人工批准与安全门</h3></div>"
        f'<div class="diagnostic-verdict"><strong>{_html(gate.get("decision") or "pending")}</strong>'
        f"<span>{'允许进入人工审核' if view['can_approve'] else '当前不可批准'}</span></div></div>"
        '<div class="diagnostic-grid">'
        '<article class="diagnostic-card"><span>文书状态</span>'
        f"<strong>{_html(view['display_document_status'])}</strong><small>系统不会自动提交或发送</small></article>"
        '<article class="diagnostic-card"><span>审批状态</span>'
        f"<strong>{_html(approval.get('state') or 'pending')}</strong><small>{_html(approval.get('approver') or '等待审批人')}</small></article>"
        '<article class="diagnostic-card"><span>Policy Gate</span>'
        f"<strong>{_html(gate.get('decision') or 'pending')}</strong><small>证据、法律、一致性与风险语言</small></article>"
        '</div><div class="diagnostic-missing"><h4>阻断项与风险提示</h4>'
        f"<ul>{issue_items}</ul></div>"
        '<div class="diagnostic-footer">完整草稿正文和变更摘要保留在导出报告中。</div>'
        "</section>"
    )


def _html(value: Any) -> str:
    return html.escape(str(value if value not in (None, "") else "—"), quote=True)


def _percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _display_value(value: Any) -> str:
    if value in (None, ""):
        return "未提供"
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def _empty_diagnostic(message: str) -> str:
    return (
        '<section class="diagnostic-summary"><div class="diagnostic-footer">'
        f"{_html(message)}</div></section>"
    )


def audit_rows(
    case: dict[str, Any],
    *,
    node_filter: str = "全部",
    event_filter: str = "全部",
    result_filter: str = "全部",
) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for event in case.get("audit_events", []):
        payload = redact_sensitive(event.get("payload", {}))
        node = str(payload.get("node") or payload.get("current_node") or "")
        event_type = event.get("event_type", "")
        result = str(
            payload.get("status")
            or payload.get("decision")
            or payload.get("result")
            or "recorded"
        )
        if node_filter != "全部" and node != node_filter:
            continue
        if event_filter != "全部" and event_type != event_filter:
            continue
        if result_filter != "全部" and result != result_filter:
            continue
        rows.append(
            [
                event.get("created_at"),
                event.get("actor"),
                event_type,
                event.get("case_id"),
                node,
                payload.get("inputs_hash", ""),
                result,
                payload.get("duration_ms", ""),
                _related_ids(payload),
                json.dumps(payload, ensure_ascii=False, default=str),
            ]
        )
    return rows


def redact_sensitive(value: Any, key: str = "") -> Any:
    sensitive_tokens = (
        "name",
        "phone",
        "mobile",
        "identity",
        "id_number",
        "address",
        "plate_number",
        "applicant",
    )
    if any(token in key.lower() for token in sensitive_tokens):
        return "***"
    if isinstance(value, dict):
        return {
            item_key: redact_sensitive(item, item_key)
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item, key) for item in value]
    return value


def _summary(value: dict[str, Any]) -> str:
    keys: list[str] = [
        key
        for key in (
            "route",
            "branch_reason",
            "approval_status",
            "document_status",
            "classification",
            "compensation_regime",
        )
        if key in value
    ]
    if not keys:
        keys = list(value)[:4]
    return "; ".join(f"{key}={value.get(key)}" for key in keys)


def _phase(label: str, index: int, total: int) -> str:
    if "碰撞前" in label:
        return "碰撞前"
    if "碰撞时" in label or "碰撞点" in label:
        return "碰撞时"
    if "碰撞后" in label:
        return "碰撞后"
    if total >= 3:
        if index == 0:
            return "碰撞前"
        if index == total - 1:
            return "碰撞后"
        return "碰撞时"
    return "阶段不确定"


def _collect_ids(value: Any, key_name: str) -> list[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == key_name and isinstance(item, list):
                result.update(str(identifier) for identifier in item)
            result.update(_collect_ids(item, key_name))
    elif isinstance(value, list):
        for item in value:
            result.update(_collect_ids(item, key_name))
    return sorted(result)


def _related_ids(payload: dict[str, Any]) -> str:
    found: set[str] = set()
    for key, value in payload.items():
        if key.endswith("_id") and value:
            found.add(str(value))
        elif key.endswith("_ids") and isinstance(value, list):
            found.update(str(item) for item in value)
    return ", ".join(sorted(found))


def _enum_value(value: Any) -> str:
    return str(value.value if hasattr(value, "value") else value)
