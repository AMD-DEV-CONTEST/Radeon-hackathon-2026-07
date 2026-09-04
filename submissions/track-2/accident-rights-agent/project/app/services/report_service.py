"""Traceable Markdown/HTML case-report export."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.schemas.ui import ReportArtifact
from app.services.case_service import CaseService

SHANGHAI = ZoneInfo("Asia/Shanghai")
DISCLAIMER = (
    "本报告由本地辅助分析系统生成，仅供案件材料整理、风险提示和人工复核使用；"
    "不构成交通事故责任认定、法律意见、胜诉承诺或保险理赔承诺。"
    "任何对外提交、发送、复核、鉴定或诉讼行为均须由具备权限的人员人工确认。"
)


class ReportService:
    def __init__(
        self,
        case_service: CaseService,
        output_root: Path | str = Path("artifacts/demo_reports"),
    ):
        self.case_service = case_service
        self.output_root = Path(output_root).resolve()

    def export(
        self,
        case_id: str,
        state: dict[str, Any],
    ) -> ReportArtifact:
        case = self.case_service.export_case(case_id)
        self.output_root.mkdir(parents=True, exist_ok=True)
        version = self._next_version(case_id)
        generated_at = datetime.now(SHANGHAI)
        timestamp = generated_at.strftime("%Y%m%dT%H%M%S%z")
        stem = f"{case_id}_v{version}_{timestamp}"
        markdown_path = (self.output_root / f"{stem}.md").resolve()
        html_path = (self.output_root / f"{stem}.html").resolve()
        markdown = self.render_markdown(case, state, version, generated_at)
        html_document = self.render_html(markdown, case_id)
        markdown_path.write_text(markdown, encoding="utf-8")
        html_path.write_text(html_document, encoding="utf-8")
        audit_event_id = self.case_service.workspace.store(case_id).audit(
            case_id,
            "case_report_exported",
            {
                "version": version,
                "generated_at": generated_at.isoformat(),
                "markdown_path": str(markdown_path),
                "html_path": str(html_path),
                "thread_id": state.get("thread_id"),
                "document_status": self._document_status(state),
            },
            "report_service",
        )
        return ReportArtifact(
            case_id=case_id,
            version=version,
            generated_at=generated_at,
            markdown_path=markdown_path,
            html_path=html_path,
            audit_event_id=audit_event_id,
        )

    def render_markdown(
        self,
        case: dict[str, Any],
        state: dict[str, Any],
        version: int,
        generated_at: datetime,
    ) -> str:
        metadata = case.get("metadata", {})
        sources = case.get("sources", [])
        facts = case.get("facts", [])
        timeline = case.get("timeline", [])
        vehicle = state.get("vehicle_nature_result") or state.get(
            "vehicle_classification", {}
        )
        liability = state.get("liability_result", {})
        deadlines = state.get("deadlines", [])
        tasks = state.get("rights_tasks", [])
        gaps = state.get("evidence_collection_plan", [])
        draft = state.get("review_application_draft", {})
        gate = state.get("policy_gate", {})
        approval = state.get("approval_state", {})
        citations = _deduplicate_citations(
            [
                *state.get("legal_citations", []),
                *draft.get("legal_basis", []),
            ]
        )
        lines = [
            f"# 交通事故责任预测与权益保护案件报告 — {case['case']['case_id']}",
            "",
            f"- 报告版本：v{version}",
            f"- 生成时间：{generated_at.isoformat()}",
            f"- 工作流线程：{state.get('thread_id', '未运行')}",
            f"- 文书状态：{self._document_status(state)}",
            "",
            "## 一、案件摘要",
            "",
            f"- 事故时间：{metadata.get('accident_time') or '未提供'}",
            f"- 地点：{metadata.get('location') or '未提供'}",
            f"- 管辖地区：{metadata.get('jurisdiction') or 'CN'}",
            f"- 当事人角色：{metadata.get('party_role') or '未提供'}",
            f"- Case Capsule：{_json_inline(_capsule_summary(state.get('case_capsule', {})))}",
            "",
            "## 二、材料清单",
            "",
            "| Evidence ID | 文件 | 类型 | 分类 | SHA256 | 状态 |",
            "|---|---|---|---|---|---|",
        ]
        lines.extend(
            f"| {item['source_id']} | {_cell(item['original_name'])} | "
            f"{_enum_value(item['kind'])} | {_enum_value(item['role'])} | "
            f"`{item['sha256']}` | {_enum_value(item['status'])} |"
            for item in sources
        )
        lines.extend(["", "## 三、证据时间线与事实", ""])
        if timeline:
            for event in timeline:
                lines.append(
                    f"- **{event['event_id']}** · {event['label']} · "
                    f"t={event.get('timestamp_seconds') if event.get('timestamp_seconds') is not None else '文档'} · "
                    f"Evidence: {', '.join(event.get('source_node_ids', []))}"
                )
        else:
            lines.append("- 暂无可验证时间线。")
        lines.extend(["", "### 事实表", ""])
        if facts:
            for fact in facts:
                lines.append(
                    f"- **{fact['fact_id']}** [{fact['status']}] "
                    f"{fact['statement']}（置信度 {fact['confidence']:.2f}；"
                    f"Evidence: {', '.join(fact.get('source_node_ids', []))}）"
                )
        else:
            lines.append("- 无结构化事实；责任结论应保持证据不足。")
        lines.extend(
            [
                "",
                "## 四、车辆属性",
                "",
                f"- 四分类结果：{vehicle.get('classification', 'insufficient_evidence')}",
                f"- 置信度：{vehicle.get('confidence', '未提供')}",
                f"- 警告：{vehicle.get('warning') or vehicle.get('warnings') or '无'}",
                f"- 支持证据：{_ids(vehicle, 'supporting_facts', 'supporting_evidence')}",
                f"- 反证：{_ids(vehicle, 'contradicting_facts', 'contradicting_evidence')}",
                f"- 缺失证据：{_json_inline(vehicle.get('missing_evidence', []))}",
                "",
                "### 参数逐项比较",
                "",
                _json_block(
                    state.get("parameter_comparison")
                    or vehicle.get("parameter_comparison", [])
                ),
                "",
                "## 五、责任分析与赔偿路径",
                "",
                "### 事故责任",
                "",
                _json_block(
                    liability.get("accident_responsibility")
                    or state.get("accident_responsibility", {})
                ),
                "",
                "### 民事赔偿责任区间/路径",
                "",
                _json_block(
                    liability.get("civil_compensation_allocation")
                    or state.get("civil_compensation_allocation", {})
                ),
                "",
                "### 保险赔付",
                "",
                _json_block(
                    liability.get("insurance_payment_estimate")
                    or state.get(
                        "insurance_payment_estimate",
                        {"status": "insufficient_data"},
                    )
                ),
                "",
                f"- compensation_regime：`{liability.get('compensation_regime') or state.get('compensation_route_result', {}).get('compensation_regime') or 'pending_vehicle_classification'}`",
                "",
                "### 多责任假设、违法与原因力",
                "",
                _json_block(
                    {
                        "responsibility_probabilities": state.get(
                            "responsibility_probabilities", {}
                        ),
                        "liability_hypotheses": state.get(
                            "liability_hypotheses", []
                        ),
                        "violation_matrix": state.get("violation_matrix", []),
                        "causation_matrix": state.get("causation_matrix", []),
                        "counterfactual_analysis": state.get(
                            "counterfactual_analysis", []
                        ),
                    }
                ),
                "",
                "## 六、权益期限与任务",
                "",
                "### 送达日期",
                "",
                _json_block(state.get("delivery_date_result", {})),
                "",
                "### Deadlines",
                "",
                _json_block(deadlines),
                "",
                "### 任务清单",
                "",
                _json_block(tasks),
                "",
                "## 七、证据缺口与反事实影响",
                "",
                _json_block(gaps),
                "",
                "## 八、复核申请草稿",
                "",
                f"- 文书 ID：{draft.get('document_id', '未生成')}",
                f"- 文书版本：{draft.get('document_version', '未生成')}",
                f"- 状态：{draft.get('status', 'draft')}",
                f"- blocking_fields：{_json_inline(draft.get('blocking_fields', []))}",
                f"- 不可提交原因：{_json_inline(draft.get('not_submittable_reasons', []))}",
                "",
                _json_block(draft),
                "",
                "## 九、Verifier / Policy Gate / 审批",
                "",
                f"- Policy Gate：`{gate.get('decision', '未执行')}`",
                f"- Blocking issues：{_json_inline(gate.get('blocking_issues', []))}",
                f"- Warnings：{_json_inline(gate.get('warnings', []))}",
                f"- 审批状态：`{approval.get('state', state.get('approval_status', 'pending'))}`",
                f"- 审批记录：{_json_inline(approval.get('record'))}",
                "",
                "## 十、法律引用",
                "",
            ]
        )
        if citations:
            for citation in citations:
                lines.append(
                    f"- **{citation.get('law_id') or citation.get('document_id') or citation.get('citation_id', 'LAW-UNKNOWN')}** "
                    f"{citation.get('title') or citation.get('document_title') or ''} "
                    f"{citation.get('article') or citation.get('locator') or ''} "
                    f"（版本/生效：{citation.get('version') or citation.get('effective_from') or '见语料库'}）"
                )
        else:
            lines.append("- 未检索到可验证法律引用；不得据此形成确定性法律结论。")
        lines.extend(["", "## 十一、审计摘要", ""])
        for event in case.get("audit_events", [])[-60:]:
            lines.append(
                f"- {event['created_at']} · {event['actor']} · "
                f"{event['event_type']} · AUDIT-{event['id']} · "
                f"{_json_inline(_redact(event.get('payload', {})))}"
            )
        lines.extend(["", "## 十二、免责声明", "", DISCLAIMER, ""])
        return "\n".join(lines)

    @staticmethod
    def render_html(markdown: str, case_id: str) -> str:
        escaped = html.escape(markdown)
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(case_id)} · 案件报告</title>
  <style>
    body {{ margin: 0; background: #f3f4ef; color: #17211e;
      font: 15px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif; }}
    main {{ max-width: 1040px; margin: 36px auto; padding: 36px 44px;
      background: white; border: 1px solid #dfe4dc; border-radius: 20px;
      box-shadow: 0 18px 60px rgba(22,45,36,.08); }}
    pre {{ white-space: pre-wrap; word-break: break-word; font: inherit; }}
    @media (max-width: 720px) {{ main {{ margin: 0; border-radius: 0; padding: 22px; }} }}
  </style>
</head>
<body><main><pre>{escaped}</pre></main></body>
</html>
"""

    def _next_version(self, case_id: str) -> int:
        pattern = re.compile(rf"^{re.escape(case_id)}_v(\d+)_")
        versions = [
            int(match.group(1))
            for path in self.output_root.glob(f"{case_id}_v*_*.md")
            if (match := pattern.match(path.name))
        ]
        return max(versions, default=0) + 1

    @staticmethod
    def _document_status(state: dict[str, Any]) -> str:
        decision = state.get("approval_state", {}).get("state")
        if decision == "approved":
            return "approved_for_manual_submission"
        return "draft"


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _enum_value(value: Any) -> str:
    return str(value.value if isinstance(value, Enum) else value)


def _capsule_summary(capsule: dict[str, Any]) -> dict[str, Any]:
    """Keep reports readable without discarding protected memory from storage."""
    return {
        "version": capsule.get("version"),
        "summary": capsule.get("summary"),
        "confirmed_fact_count": len(capsule.get("confirmed_facts", [])),
        "disputed_fact_count": len(capsule.get("disputed_facts", [])),
        "legal_issue_count": len(capsule.get("legal_issues", [])),
        "liability_hypothesis_count": len(
            capsule.get("liability_hypotheses", [])
        ),
        "missing_evidence_count": len(capsule.get("missing_evidence", [])),
        "updated_at": capsule.get("updated_at"),
    }


def _json_inline(value: Any) -> str:
    return json.dumps(
        _json_ready(value), ensure_ascii=False, sort_keys=True, default=str
    )


def _json_block(value: Any) -> str:
    return "```json\n" + json.dumps(
        _json_ready(value),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=str,
    ) + "\n```"


def _json_ready(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, str):
        enum_repr = re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_]*\.([A-Z][A-Z0-9_]*)", value
        )
        if enum_repr:
            return enum_repr.group(1).lower()
        return value
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(item) for item in value]
    return value


def _ids(value: dict[str, Any], *keys: str) -> str:
    items: list[Any] = []
    for key in keys:
        items.extend(value.get(key, []) or [])
    return _json_inline(items)


def _deduplicate_citations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        key = _json_inline(item)
        if key not in seen:
            result.append(item)
            seen.add(key)
    return result


SENSITIVE_KEYS = {
    "name",
    "applicant",
    "phone",
    "mobile",
    "id_number",
    "identity",
    "address",
    "plate_number",
}


def _redact(value: Any, key: str = "") -> Any:
    normalized = key.lower()
    if any(token in normalized for token in SENSITIVE_KEYS):
        return "***"
    if isinstance(value, dict):
        return {item_key: _redact(item, item_key) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    return value
