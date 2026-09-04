"""Gradio Blocks UI for the local accident-rights workflow."""

from __future__ import annotations

import argparse
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Generator

from app.demo.business_cases import seed_experience_case
from app.demo.golden_case import seed_golden_case
from app.evidence.errors import EvidenceError
from app.schemas.evidence import SourceRole
from app.schemas.ui import PartyRole, WorkflowMode
from app.services.case_service import CaseService
from app.services.report_service import ReportService
from app.services.workflow_service import WorkflowService
from app.ui.owner_view_models import (
    insurer_review_html,
    insurer_summary_html,
    insurer_task_rows,
    owner_action_html,
    owner_appraisal_guidance_html,
    owner_communication_script,
    owner_material_rows,
    owner_material_sources,
    owner_overview_html,
    owner_task_choices,
    owner_task_rows,
)
from app.ui.view_models import (
    approval_summary_html,
    approval_view,
    audit_rows,
    evidence_preview_choices,
    evidence_timeline_html,
    liability_summary_html,
    progress_overview,
    progress_overview_html,
    progress_table_html,
    rights_summary_html,
)

SOURCE_HEADERS = [
    "Evidence ID",
    "文件名",
    "类型",
    "材料分类",
    "大小",
    "SHA256",
    "处理状态",
    "质量问题",
]
PROGRESS_HEADERS = [
    "节点",
    "状态",
    "开始时间",
    "结束时间",
    "重试",
    "简要输出",
    "失败原因",
]
TIMELINE_HEADERS = [
    "阶段",
    "Fact ID",
    "Source ID",
    "Evidence Node ID",
    "时间戳/页码",
    "事实",
    "置信度",
    "状态",
    "冲突",
]
AUDIT_HEADERS = [
    "时间",
    "actor",
    "事件",
    "case_id",
    "node",
    "inputs_hash",
    "result",
    "duration",
    "related IDs",
    "脱敏详情",
]
OWNER_TASK_HEADERS = [
    "优先级",
    "状态",
    "权益行动",
    "建议完成时间",
    "为什么要做",
    "建议步骤",
    "谁来协助",
]
OWNER_MATERIAL_HEADERS = ["材料（点击查看）", "分类", "提供方", "文件情况"]
INSURER_TASK_HEADERS = [
    "协助车主完成",
    "建议什么时候完成",
    "理赔员现在怎么做",
    "做到什么算完成",
]

CSS = """
:root { --brand: #0d6b4f; --paper: #f6f7f3; --ink: #17221e;
  --muted: #61706a; --orange: #e96d23; }
html, body { max-width: 100%; overflow-x: hidden; background: var(--paper); }
.gradio-container { width: 100% !important; max-width: none !important;
  margin: 0 auto !important; padding: 18px clamp(16px, 2.2vw, 44px) !important;
  box-sizing: border-box; background: var(--paper); }
.gradio-container > main { width: 100% !important; max-width: none !important; }
.hero { padding: 28px 32px; border-radius: 22px; color: white;
  background: linear-gradient(125deg, #124f41, #1b8060); margin-bottom: 14px; }
.hero, .hero * { color: white !important; }
.hero h1 { margin: 0 0 7px; font-size: 32px; }
.hero p { margin: 0; opacity: .9; font-size: 16px; }
.safety { border-left: 4px solid #d99a32; padding: 12px 16px;
  background: #fff3d9; border-radius: 8px; }
.case-home { background: white; border: 2px solid #0d6b4f; border-radius: 18px;
  padding: 18px 20px; margin-bottom: 12px; box-shadow: 0 5px 18px #163b2c12; }
.case-home h3 { margin: 0 0 5px; color: var(--brand); font-size: 22px; }
.case-home p { margin: 0; color: var(--muted); }
.owner-case-picker { background: white; border: 2px solid #8bb6a7;
  border-radius: 15px; padding: 12px 14px; }
.key-action button { min-height: 50px; font-weight: 750; font-size: 15px; }
.material-help { background: #edf6f1; border-radius: 10px; padding: 10px 13px; }
.owner-overview { display: grid; gap: 16px; }
.owner-status, .next-action { background: white; border: 1px solid #dfe6e1;
  border-radius: 18px; padding: 22px 24px; box-shadow: 0 8px 22px rgba(25,58,47,.05); }
.owner-status { border-left: 6px solid var(--brand); }
.owner-status h2, .next-action h2 { margin: 6px 0 8px; color: var(--ink); }
.owner-status p, .next-action p { color: var(--muted); }
.eyebrow { color: var(--brand); font-weight: 700; font-size: 13px;
  letter-spacing: .08em; text-transform: uppercase; }
.owner-summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.owner-summary-grid article { background: white; border: 1px solid #e1e7e2;
  border-radius: 15px; padding: 18px; min-height: 112px; }
.owner-summary-grid span { display: block; color: var(--muted); font-size: 13px; }
.owner-summary-grid strong { display: block; color: var(--ink); margin: 8px 0;
  line-height: 1.4; }
.owner-summary-grid small { color: var(--muted); line-height: 1.45; }
.owner-evidence { background: #edf6f1; border-radius: 15px; padding: 16px 20px; }
.owner-evidence h3 { margin: 0 0 8px; }
.owner-evidence li { margin: 6px 0; }
.next-action { border-top: 6px solid var(--orange); }
.next-action ol { padding-left: 22px; }
.next-action li { margin: 8px 0; }
.priority-pill, .due-pill { display: inline-block; padding: 5px 10px;
  border-radius: 999px; font-size: 13px; font-weight: 700; margin-right: 6px; }
.priority-pill { background: #fff0e6; color: #a3430d; }
.due-pill { background: #eef3f0; color: #3f544c; }
.action-note { font-size: 13px; border-top: 1px solid #e6e9e7; padding-top: 12px; }
.appraisal-action, .insurer-summary, .insurer-review {
  background: white; border: 1px solid #dfe6e1; border-radius: 18px;
  padding: 22px 24px; margin-bottom: 14px;
}
.appraisal-action { border-left: 6px solid #315e8e; }
.appraisal-action h2, .insurer-summary h2, .insurer-review h2 {
  margin: 6px 0 10px; color: var(--ink);
}
.appraisal-action li { margin: 6px 0; }
.legal-basis { background: #edf3fa; border-radius: 10px; padding: 11px 13px; }
.supplement-note { color: #75500d; background: #fff4dd;
  border-radius: 10px; padding: 11px 13px; }
.insurer-summary-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.insurer-summary-grid article { background: #f5f7f5; border-radius: 13px; padding: 15px; }
.insurer-summary-grid span, .insurer-summary-grid small {
  display: block; color: var(--muted); font-size: 13px;
}
.insurer-summary-grid strong { display: block; margin: 7px 0; }
.advanced-workbench { opacity: .92; margin-top: 14px; }
.primary-cta button { min-height: 48px; font-size: 16px; font-weight: 700; }
.professional { margin-top: 18px; opacity: .96; }
.professional summary { font-weight: 700; color: #45544f; }
.status-card { border: 1px solid #dce3dc; border-radius: 14px; padding: 12px; }
.diagnostic-summary { display: grid; gap: 14px; color: var(--ink); }
.diagnostic-heading { display: flex; justify-content: space-between; align-items: end;
  gap: 14px; padding-top: 4px; }
.diagnostic-heading h3 { margin: 4px 0 0; }
.diagnostic-verdict { display: grid; justify-items: end; gap: 3px; }
.diagnostic-verdict strong { color: var(--brand); font-size: 20px; }
.diagnostic-verdict span, .diagnostic-note { color: var(--muted); font-size: 13px; }
.diagnostic-table-wrap { overflow-x: auto; border: 1px solid #dfe6e1;
  border-radius: 14px; background: white; }
.diagnostic-table { border-collapse: collapse; min-width: 760px; }
.diagnostic-table th, .diagnostic-table td { text-align: left; vertical-align: top;
  padding: 11px 12px; border-bottom: 1px solid #edf0ed; line-height: 1.45; }
.diagnostic-table th { color: var(--muted); background: #f5f7f5; font-size: 13px; }
.diagnostic-pill { display: inline-block; padding: 4px 8px; border-radius: 999px;
  background: #eef3f0; font-size: 12px; font-weight: 700; white-space: nowrap; }
.status-compliant { background: #e4f4ec; color: #146b4c; }
.status-unknown { background: #fff1d8; color: #8a5b00; }
.status-conflicting, .status-non_compliant { background: #fde6e3; color: #9c2f25; }
.diagnostic-missing { background: #fff8e8; border-left: 4px solid #d99a32;
  border-radius: 10px; padding: 12px 16px; }
.diagnostic-missing h4 { margin: 0 0 8px; }
.diagnostic-missing ul { margin: 0; padding-left: 20px; }
.diagnostic-missing li { margin: 5px 0; }
.diagnostic-grid, .hypothesis-grid { display: grid; gap: 12px;
  grid-template-columns: repeat(3, minmax(0, 1fr)); }
.diagnostic-card { display: grid; gap: 7px; background: white; border: 1px solid #dfe6e1;
  border-radius: 14px; padding: 15px 16px; min-width: 0; }
.diagnostic-card > span, .diagnostic-card > small { color: var(--muted); }
.diagnostic-card > strong { line-height: 1.4; }
.hypothesis-card { position: relative; border-top: 4px solid #315e8e; }
.hypothesis-card h4, .hypothesis-card p { margin: 0; }
.diagnostic-rank { color: #315e8e; font-size: 12px; font-weight: 750; }
.probability { color: var(--brand); font-size: 25px; font-weight: 800; }
.diagnostic-footer { background: #edf6f1; border-radius: 10px; padding: 12px 14px;
  color: #42564e; }
.gradio-container table { width: 100%; }
.gradio-container textarea, .gradio-container input, .gradio-container select {
  max-width: 100%; box-sizing: border-box;
}
@media (max-width: 900px) {
  .owner-summary-grid { grid-template-columns: 1fr 1fr; }
  .insurer-summary-grid { grid-template-columns: 1fr; }
  .diagnostic-grid, .hypothesis-grid { grid-template-columns: 1fr; }
  .gradio-container { padding: 12px 14px !important; }
  .hero { padding: 24px; }
}
@media (max-width: 680px) {
  .gradio-container { padding: 8px !important; }
  .gradio-container .gr-row { flex-direction: column !important; flex-wrap: nowrap !important; }
  .gradio-container .gr-row > * { width: 100% !important; min-width: 0 !important;
    flex: 1 1 auto !important; }
  .owner-summary-grid { grid-template-columns: 1fr; }
  .hero { padding: 20px 18px; border-radius: 16px; }
  .hero h1 { font-size: 26px; }
  .hero p { font-size: 15px; line-height: 1.6; }
  .case-home { padding: 15px 16px; border-radius: 14px; }
  .case-home h3 { font-size: 20px; }
  .owner-status, .next-action, .appraisal-action, .insurer-summary,
  .insurer-review { padding: 17px 16px; border-radius: 14px; }
  .owner-summary-grid article { min-height: auto; padding: 15px; }
  .gradio-container button { width: 100% !important; min-height: 48px; }
  .gradio-container input, .gradio-container textarea, .gradio-container select {
    font-size: 16px !important;
  }
  .gradio-container [role="tablist"] { overflow-x: auto; flex-wrap: nowrap !important;
    -webkit-overflow-scrolling: touch; }
  .gradio-container [role="tab"] { white-space: nowrap; }
  .gradio-container .table-wrap, .gradio-container .dataframe {
    overflow-x: auto !important; -webkit-overflow-scrolling: touch;
  }
}
footer { display: none !important; }
"""


class GradioController:
    def __init__(
        self,
        case_service: CaseService,
        workflow_service: WorkflowService,
        report_service: ReportService,
    ):
        self.cases = case_service
        self.workflows = workflow_service
        self.reports = report_service
        self._fresh_fixture_cases: set[str] = set()

    def case_choices(
        self, *, include_case_id: str | None = None
    ) -> list[tuple[str, str]]:
        choices: list[tuple[str, str]] = []
        for item in self.cases.list_cases():
            case_id = item.metadata.case_id
            is_experience_case = case_id == "CASE-GOLDEN-DEMO" or case_id.startswith(
                "CASE-EXP-"
            )
            if is_experience_case and case_id != include_case_id:
                continue
            if (
                case_id == "CASE-ORCHESTRATOR-DEMO"
                and not item.metadata.location
                and item.metadata.accident_time is None
            ):
                continue
            location = (
                "合成体验 · 主演示（Golden Demo）"
                if case_id == "CASE-GOLDEN-DEMO"
                else item.metadata.location or _case_location_fallback(case_id)
            )
            accident_date = (
                f"{item.metadata.accident_time:%m月%d日}"
                if item.metadata.accident_time
                else "时间待补充"
            )
            choices.append((f"{location} · {accident_date}", case_id))
        return choices

    def create_case(
        self,
        accident_time: str,
        location: str,
        jurisdiction: str,
        party_role: str,
        delivery_date: str,
        files: Any,
        default_role: str,
    ) -> tuple[Any, ...]:
        paths = _file_paths(files)
        summary = self.cases.create_case(
            accident_time=_parse_datetime(accident_time),
            location=location,
            jurisdiction=jurisdiction or "CN",
            party_role=party_role,
            manual_delivery_date=_parse_date(delivery_date),
            files=paths,
            default_role=default_role,
        )
        case_id = summary.metadata.case_id
        return (
            case_id,
            "",
            self._source_rows(case_id),
            self._case_dropdown(case_id),
            "新事故已保存；您可以先补充材料，也可以直接开始分析。",
        )

    def seed_fixture(self, fixture: str) -> tuple[Any, ...]:
        if fixture == "golden":
            case_id = seed_golden_case(self.cases.workspace)
        else:
            case_id, _ = seed_experience_case(self.cases.workspace, fixture)
        # Opening a fixture means starting a new Demo view, not silently
        # restoring a completed run from an earlier recording attempt.  The
        # historical thread and checkpoints remain intact for audit/recovery.
        self._fresh_fixture_cases.add(case_id)
        return (
            case_id,
            "",
            self._source_rows(case_id),
            self._case_dropdown(case_id),
            "体验案例已载入；其中材料均为明确标记的合成数据。",
        )

    def load_case(self, case_id: str, mode: str) -> tuple[Any, ...]:
        if not case_id:
            raise ValueError("请选择案件。")
        case = self.cases.export_case(case_id)
        metadata = self.cases.metadata(case_id)
        latest = (
            {}
            if case_id in self._fresh_fixture_cases
            else self.cases.latest_thread(case_id) or {}
        )
        thread_id = str(latest.get("thread_id") or "")
        state: dict[str, Any] = {}
        overview: dict[str, Any] = {
            "case_id": case_id,
            "thread_id": thread_id or None,
            "progress_percent": 0,
            "current_node": "未运行",
            "recoverable": False,
        }
        if thread_id:
            try:
                status = self.workflows.status(thread_id, mode=mode)
                state = status["state"]
                overview = progress_overview(
                    state,
                    recoverable=status["recoverable"],
                    next_nodes=status["next"],
                )
            except Exception as exc:
                overview["restore_warning"] = str(exc)
        return (
            case_id,
            thread_id,
            (
                metadata.accident_time.isoformat()
                if metadata.accident_time is not None
                else ""
            ),
            metadata.location,
            metadata.jurisdiction,
            metadata.party_role.value,
            (
                metadata.manual_delivery_date.isoformat()
                if metadata.manual_delivery_date is not None
                else ""
            ),
            owner_overview_html(case, state),
            owner_action_html(case, state),
            owner_appraisal_guidance_html(state),
            owner_task_rows(case, state),
            self._owner_task_dropdown(state, case),
            owner_material_rows(case),
            insurer_summary_html(case, state),
            insurer_task_rows(case, state),
            owner_material_rows(case),
            insurer_review_html(state),
            self._source_rows(case_id),
            progress_table_html(state),
            progress_overview_html(overview),
            evidence_timeline_html(case),
            self._evidence_dropdown(case),
            liability_summary_html(state),
            rights_summary_html(state),
            approval_summary_html(state),
            [],
            state,
            None,
            "尚未选择材料。点击上方表格中的材料名称查看原文件。",
            None,
            "尚未选择材料。点击上方表格中的材料名称查看原文件。",
            "",
            ("尚未生成文书。请选择沟通对象和车辆鉴定阶段后，点击 **“生成可用文书”**。"),
            ("已打开当前事故。可直接查看已有结果；只有补充了新材料时才需要重新分析。"),
        )

    def add_collaboration_files(
        self,
        case_id: str,
        files: Any,
        role: str,
        provider: str,
    ) -> tuple[list[list[Any]], list[list[Any]], list[list[Any]], str]:
        if not case_id:
            return [], [], [], "请先创建或选择事故，再补充材料。"
        case = self.cases.export_case(case_id)
        material_rows = owner_material_rows(case)
        source_rows = self._source_rows(case_id)
        paths = _file_paths(files)
        if not paths:
            return (
                material_rows,
                material_rows,
                source_rows,
                "尚未选择文件，现有事故材料保持不变。请先上传视频、照片或 PDF。",
            )
        before = {item.source_id for item in self.cases.sources(case_id)}
        try:
            sources = self.cases.ingest_files(case_id, paths, role=role)
        except (EvidenceError, OSError, ValueError) as exc:
            return (
                material_rows,
                material_rows,
                source_rows,
                f"材料未加入，现有记录未改变：{exc}",
            )
        added = [item.source_id for item in sources if item.source_id not in before]
        self.cases.record_collaboration_materials(
            case_id,
            added,
            provider=provider,
        )
        case = self.cases.export_case(case_id)
        material_rows = owner_material_rows(case)
        return (
            material_rows,
            material_rows,
            self._source_rows(case_id),
            f"已接收 {len(added)} 份{provider}材料；原文件和提供方记录均已保留。",
        )

    def complete_owner_task(
        self,
        case_id: str,
        task_id: str,
        state: dict[str, Any],
    ) -> tuple[list[list[Any]], Any, str, list[list[Any]], str]:
        if not case_id or not task_id:
            raise ValueError("请选择要完成的权益行动。")
        self.cases.record_owner_task_status(
            case_id,
            task_id,
            status="completed",
        )
        case = self.cases.export_case(case_id)
        return (
            owner_task_rows(case, state or {}),
            self._owner_task_dropdown(state or {}, case),
            owner_action_html(case, state or {}),
            insurer_task_rows(case, state or {}),
            "已标记为完成，并写入案件记录。",
        )

    def generate_communication(
        self,
        target: str,
        procedure_stage: str,
        state: dict[str, Any],
        case_id: str | None = None,
    ) -> tuple[str, str]:
        current_state = dict(state or {})
        if case_id:
            case = self.cases.export_case(case_id)
            capsule = dict(current_state.get("case_capsule") or {})
            capsule["confirmed_facts"] = [
                fact
                for fact in case.get("facts", [])
                if str(fact.get("status") or "").lower() in {"verified", "confirmed"}
            ]
            current_state["case_capsule"] = capsule
        document = owner_communication_script(
            current_state,
            target,
            procedure_stage=procedure_stage,
        )
        title = next(
            (line.strip() for line in document.splitlines() if line.strip()),
            "沟通文书",
        )
        generated_at = datetime.now().astimezone().isoformat(timespec="milliseconds")
        status = (
            f"✅ 已生成 **{title}**  ·  沟通对象：**{target}**  ·  "
            f"当前阶段：**{procedure_stage}**  ·  生成时间：`{generated_at}`\n\n"
            "请核对正文后自行当面提交并使用 EMS 留存递送证据；系统不会自动发送。"
        )
        return document, status

    @staticmethod
    def mark_communication_stale(
        target: str,
        procedure_stage: str,
    ) -> tuple[str, str]:
        return (
            "",
            f"⚠️ 已切换为 **{target} / {procedure_stage}**。"
            "原文书已清空，请点击 **“生成可用文书”** 生成与当前条件一致的新版本。",
        )

    def record_communication(
        self,
        case_id: str,
        target: str,
        result: str,
    ) -> str:
        if not case_id:
            raise ValueError("请先选择事故。")
        if not result.strip():
            raise ValueError("请填写对方的答复或本次沟通结果。")
        self.cases.record_owner_communication(
            case_id,
            target=target,
            result=result,
        )
        return "沟通结果已保存到案件记录；系统未向任何外部机构自动发送内容。"

    def add_files(
        self, case_id: str, files: Any, role: str
    ) -> tuple[list[list[Any]], str]:
        if not case_id:
            raise ValueError("请先创建或选择案件。")
        paths = _file_paths(files)
        self.cases.ingest_files(case_id, paths, role=role)
        return self._source_rows(case_id), f"已加入 {len(paths)} 份材料。"

    def change_role(
        self, case_id: str, source_id: str, role: str
    ) -> tuple[list[list[Any]], str]:
        self.cases.update_source_role(case_id, source_id, role)
        return self._source_rows(case_id), (
            f"{source_id} 的材料分类已修正为 {role}；原文件未被修改。"
        )

    def reconstruct(self, case_id: str, mode: str) -> tuple[list[list[Any]], str]:
        result = self.cases.reconstruct(case_id, mode=mode)
        return self._source_rows(case_id), (
            f"证据还原状态：{result['status']}；"
            f"cache_hit={result.get('cache_hit', False)}；"
            f"高成本解析重跑={result.get('high_cost_parser_reexecuted', False)}。"
        )

    def start(self, case_id: str, mode: str) -> Generator[tuple[Any, ...], None, None]:
        if not case_id:
            raise ValueError("请先创建或选择案件。")
        self._fresh_fixture_cases.discard(case_id)
        yield from self._workflow_updates(
            self.workflows.run_incremental(case_id, mode=mode)
        )

    def resume(
        self, thread_id: str, mode: str
    ) -> Generator[tuple[Any, ...], None, None]:
        if not thread_id:
            raise ValueError("当前案件没有可恢复 thread_id。")
        yield from self._workflow_updates(
            self.workflows.resume_incremental(thread_id, mode=mode)
        )

    def pause(self, thread_id: str) -> str:
        if not thread_id:
            return "没有正在运行的 thread_id。"
        self.workflows.request_stop(thread_id)
        return "已请求安全停止；当前节点完成并写入 checkpoint 后暂停。"

    def retry(self, thread_id: str, mode: str) -> tuple[Any, ...]:
        if not thread_id:
            raise ValueError("没有可重试的 thread_id。")
        envelope = self.workflows.retry_failed(thread_id, mode=mode)
        return self._render_workflow(envelope)

    def filter_timeline(
        self,
        case_id: str,
        phase: str,
        source_filter: str,
        status_filter: str,
    ) -> str:
        case = self.cases.export_case(case_id)
        return evidence_timeline_html(
            case,
            phase=phase,
            source_filter=source_filter,
            status_filter=status_filter,
        )

    def preview_source(
        self, case_id: str, source_id: str
    ) -> tuple[str | None, str | None, str | None, dict[str, Any]]:
        if not case_id or not source_id:
            return None, None, None, {}
        source = self.cases.workspace.store(case_id).get_source(source_id)
        path = self.cases.workspace.resolve_source(source)
        image = str(path) if source.kind.value == "image" else None
        video = str(path) if source.kind.value == "video" else None
        return str(path), image, video, source.to_dict()

    def preview_material_row(
        self,
        case_id: str,
        selected_index: Any,
    ) -> tuple[str | None, str]:
        if not case_id:
            return None, "请先选择事故。"
        row_index = (
            selected_index[0]
            if isinstance(selected_index, (list, tuple))
            else selected_index
        )
        try:
            case = self.cases.export_case(case_id)
            selected = owner_material_sources(case)[int(row_index)]
            source = self.cases.workspace.store(case_id).get_source(
                str(selected["source_id"])
            )
        except (IndexError, TypeError, ValueError):
            return None, "没有找到这份材料，请刷新当前事故后重试。"
        path = self.cases.workspace.resolve_source(source)
        return (
            str(path),
            f"已选中 **{source.original_name}**。"
            "点击下方文件卡片或右侧下载箭头，即可查看或保存原文件。",
        )

    def decide(
        self,
        thread_id: str,
        mode: str,
        decision: str,
        approver: str,
        comments: str,
    ) -> tuple[str, str, dict[str, Any], str]:
        try:
            result = self.workflows.decide_approval(
                thread_id,
                decision=decision,
                approver=approver,
                comments=comments,
                mode=mode,
            )
            state = result["state"]
            return (
                approval_summary_html(state),
                insurer_review_html(state),
                state,
                "审批已记录。批准仅代表 approved_for_manual_submission，"
                "系统不会自动标记 submitted/sent。",
            )
        except Exception as exc:
            try:
                state = self.workflows.state(thread_id, mode=mode)
            except Exception:
                state = {}
            return (
                approval_summary_html(state),
                insurer_review_html(state),
                state,
                f"审批未生效：{exc}",
            )

    @staticmethod
    def approval_button_state(decision: str, state: dict[str, Any]):
        import gradio as gr

        enabled = decision != "approved" or approval_view(state or {})["can_approve"]
        return gr.Button(interactive=enabled)

    def export_report(
        self, case_id: str, state: dict[str, Any]
    ) -> tuple[str, str, str]:
        if not case_id:
            raise ValueError("请选择案件。")
        artifact = self.reports.export(case_id, state or {})
        return (
            str(artifact.markdown_path),
            str(artifact.html_path),
            f"报告 v{artifact.version} 已生成并写入审计日志 "
            f"{artifact.audit_event_id}。",
        )

    def refresh_audit(
        self,
        case_id: str,
        node_filter: str,
        event_filter: str,
        result_filter: str,
    ) -> list[list[Any]]:
        rows = audit_rows(
            self.cases.export_case(case_id),
            node_filter=node_filter,
            event_filter=event_filter,
            result_filter=result_filter,
        )
        return rows[-20:][::-1]

    def _workflow_updates(
        self, updates: Generator[dict[str, Any], None, None]
    ) -> Generator[tuple[Any, ...], None, None]:
        for envelope in updates:
            yield self._render_workflow(envelope)

    def _render_workflow(self, envelope: dict[str, Any]) -> tuple[Any, ...]:
        state = envelope["state"]
        case = self.cases.export_case(envelope["case_id"])
        overview = progress_overview(
            state,
            recoverable=envelope["recoverable"],
            next_nodes=envelope["next"],
        )
        overview.update(
            {
                "elapsed_seconds": envelope["elapsed_seconds"],
                "node_durations_ms": envelope["node_durations_ms"],
                "paused": envelope["paused"],
            }
        )
        return (
            envelope["thread_id"],
            owner_overview_html(case, state),
            owner_action_html(case, state),
            owner_appraisal_guidance_html(state),
            owner_task_rows(case, state),
            self._owner_task_dropdown(state, case),
            owner_material_rows(case),
            insurer_summary_html(case, state),
            insurer_task_rows(case, state),
            owner_material_rows(case),
            insurer_review_html(state),
            progress_table_html(state),
            progress_overview_html(overview),
            state,
            liability_summary_html(state),
            rights_summary_html(state),
            approval_summary_html(state),
            [],
            (
                f"当前节点 `{envelope['current_node']}`；"
                f"总进度 {float(envelope['progress']) * 100:.0f}%；"
                f"可恢复={envelope['recoverable']}；"
                f"失败={envelope['failure_count']}，警告={envelope['warning_count']}。"
            ),
        )

    def _source_rows(self, case_id: str) -> list[list[Any]]:
        return [
            [
                item.source_id,
                item.original_name,
                item.kind,
                item.role,
                _human_bytes(item.size_bytes),
                item.sha256,
                item.processing_status,
                "; ".join(item.quality_issues),
            ]
            for item in self.cases.sources(case_id)
        ]

    def _case_dropdown(self, case_id: str):
        import gradio as gr

        choices = self.case_choices(include_case_id=case_id)
        if not any(value == case_id for _, value in choices):
            choices.insert(0, (f"当前事故 · {case_id}", case_id))
        return gr.Dropdown(choices=choices, value=case_id)

    @staticmethod
    def _evidence_dropdown(case: dict[str, Any]):
        import gradio as gr

        choices = evidence_preview_choices(case)
        return gr.Dropdown(
            choices=choices,
            value=choices[0][1] if choices else None,
        )

    @staticmethod
    def _owner_task_dropdown(state: dict[str, Any], case: dict[str, Any]):
        import gradio as gr

        choices = owner_task_choices(state, case)
        return gr.Dropdown(
            choices=choices,
            value=choices[0][1] if choices else None,
        )


def build_app(
    *,
    case_root: Path | str | None = None,
    checkpoint_path: Path | str | None = None,
    report_root: Path | str | None = None,
):
    try:
        import gradio as gr
    except ImportError as exc:
        raise RuntimeError(
            "Gradio is required. Install requirements.lock before launch."
        ) from exc

    selected_case_root = Path(case_root or os.getenv("CASE_ROOT") or "data/cases")
    selected_checkpoint = Path(
        checkpoint_path
        or os.getenv(
            "ORCHESTRATOR_CHECKPOINT_DB",
        )
        or "data/checkpoints/orchestrator.sqlite3"
    )
    selected_report_root = Path(
        report_root or os.getenv("REPORT_ROOT") or "artifacts/demo_reports"
    )
    cases = CaseService(selected_case_root)
    workflows = WorkflowService(
        cases,
        checkpoint_path=selected_checkpoint,
        legal_corpus_path=os.getenv(
            "LEGAL_CORPUS_DB", "data/laws/legal_corpus.sqlite3"
        ),
        qdrant_path=os.getenv("QDRANT_PATH", "data/qdrant/legal"),
    )
    controller = GradioController(
        cases, workflows, ReportService(cases, selected_report_root)
    )
    real_case_choices = controller.case_choices()
    initial_case_id = _select_initial_case(real_case_choices)
    if initial_case_id is None and "CASE-GOLDEN-DEMO" in cases.case_ids():
        initial_case_id = "CASE-GOLDEN-DEMO"
    initial_case_choices = controller.case_choices(include_case_id=initial_case_id)
    default_mode = os.getenv("MODEL_MODE", "mock")
    if default_mode not in {item.value for item in WorkflowMode}:
        default_mode = "mock"

    with gr.Blocks(
        title="事故权益助手 · 车主责任分析与行动指引",
        delete_cache=(86400, 86400),
    ) as app:
        gr.HTML(
            """<section class="hero"><h1>事故权益助手</h1>
            <p>帮车主看清责任、抓住期限，并一步步完成取证、沟通与复核准备。
            保险公司可协助补充材料，所有对外行动都由车主本人确认。</p></section>"""
        )
        gr.HTML(
            """<section class="case-home"><h3>我的事故</h3>
            <p>这里是您正在处理的事故。下方只显示真实事故和当前打开的体验案例；
            新事故可在“案件材料”中创建。</p></section>"""
        )
        with gr.Row():
            selected_case = gr.Dropdown(
                label="我的事故（当前打开）",
                choices=initial_case_choices,
                value=initial_case_id,
                allow_custom_value=False,
                scale=7,
                elem_classes=["owner-case-picker"],
            )
            case_id_state = gr.Textbox(
                value=initial_case_id,
                interactive=False,
                visible=False,
            )
            thread_id_state = gr.Textbox(interactive=False, visible=False)
            owner_refresh = gr.Button(
                "刷新当前事故",
                variant="primary",
                scale=1,
                elem_classes=["key-action"],
            )
        with gr.Accordion(
            "还没有真实事故？使用合成案例快速体验",
            open=False,
            elem_classes=["experience-entry"],
        ):
            gr.Markdown("请选择一个合成案例体验完整流程。合成材料不会修改真实事故。")
            with gr.Row():
                owner_fixture = gr.Dropdown(
                    [
                        ("主演示：完整走通分析与行动", "golden"),
                        ("边界案例：证据不足", "demo_b"),
                        ("边界案例：事实冲突", "demo_c"),
                    ],
                    value="golden",
                    label="选择一个合成案例",
                    scale=5,
                )
                owner_load_fixture = gr.Button(
                    "加入“我的事故”并打开",
                    variant="primary",
                    scale=1,
                    elem_classes=["key-action"],
                )
        notice = gr.Markdown("请选择上方事故继续处理。")
        workflow_state = gr.State({})

        with gr.Tabs():
            with gr.Tab("案件概览", id="owner-overview"):
                owner_next_action = gr.HTML()
                owner_overview = gr.HTML()
                with gr.Row():
                    owner_start = gr.Button(
                        "分析 / 更新当前事故",
                        variant="primary",
                        elem_classes=["primary-cta"],
                    )
                gr.Markdown(
                    "首次使用或补充新材料后点击；材料没有变化时，无需重复运行。"
                )
                gr.Markdown(
                    "分析结果用于协助车主与保险理赔员核对事实和准备行动，"
                    "不替代交管部门认定、司法裁判或律师意见。"
                )

            with gr.Tab("权益行动", id="owner-actions"):
                owner_appraisal_guidance = gr.HTML()
                owner_task_table = gr.Dataframe(
                    headers=OWNER_TASK_HEADERS,
                    datatype=["str"] * len(OWNER_TASK_HEADERS),
                    interactive=False,
                    wrap=True,
                    label="我的行动清单",
                )
                with gr.Row():
                    owner_task_choice = gr.Dropdown(
                        label="已完成哪一项？",
                        scale=5,
                    )
                    owner_complete_task = gr.Button(
                        "标记为已完成",
                        variant="secondary",
                        scale=1,
                    )
                gr.Markdown("### 沟通助手")
                with gr.Row():
                    communication_target = gr.Dropdown(
                        ["交管部门", "事故相对方", "保险理赔员"],
                        value="交管部门",
                        label="准备与谁沟通？",
                        scale=3,
                    )
                    procedure_stage = gr.Dropdown(
                        [
                            "交管部门尚未委托鉴定",
                            "已收到鉴定意见并有异议",
                            "原鉴定遗漏事项或取得新材料",
                            "已进入法院诉讼",
                        ],
                        value="交管部门尚未委托鉴定",
                        label="车辆鉴定进行到哪一步？",
                        scale=4,
                    )
                    generate_communication = gr.Button(
                        "生成可用文书", variant="primary", scale=1
                    )
                communication_status = gr.Markdown(
                    "尚未生成文书。请选择沟通对象和车辆鉴定阶段后，"
                    "点击 **“生成可用文书”**。"
                )
                communication_script = gr.Textbox(
                    label="申请书 / 沟通草稿（核对后由您本人使用）",
                    lines=16,
                )
                communication_result = gr.Textbox(
                    label="沟通后记录对方答复或下一步",
                    lines=3,
                    placeholder="例如：承办民警告知明天下午可申请查阅案卷……",
                )
                save_communication = gr.Button("保存本次沟通结果")

            with gr.Tab("案件材料", id="owner-materials"):
                gr.Markdown(
                    "车主与保险公司可以共同补充材料。系统会保留文件原件、"
                    "材料分类和提供方记录。"
                )
                owner_material_table = gr.Dataframe(
                    headers=OWNER_MATERIAL_HEADERS,
                    datatype=["str"] * len(OWNER_MATERIAL_HEADERS),
                    interactive=False,
                    wrap=True,
                    label="已收到的材料",
                )
                gr.Markdown(
                    "显示“已保存，可查看”即代表原文件已经存入当前事故。"
                    "点击表格中的材料名称，下方会出现原文件。",
                    elem_classes=["material-help"],
                )
                owner_material_preview_note = gr.Markdown(
                    "尚未选择材料。点击上方表格中的材料名称查看原文件。"
                )
                owner_material_preview = gr.File(
                    label="查看或下载所选材料",
                    interactive=False,
                )
                with gr.Row():
                    material_provider = gr.Dropdown(
                        ["车主上传", "保险公司补充"],
                        value="车主上传",
                        label="谁提供的？",
                    )
                    owner_material_role = gr.Dropdown(
                        [
                            ("事故认定书", "accident_determination"),
                            ("送达材料", "delivery_information"),
                            ("行车记录仪", "dashcam_video"),
                            ("现场照片", "scene_photo"),
                            ("车辆登记 / 号牌", "vehicle_registration"),
                            ("合格证 / CCC", "vehicle_certificate_ccc"),
                            ("鉴定报告", "appraisal_report"),
                            ("询问笔录", "inquiry_record"),
                            ("保险材料", "insurance_policy"),
                            ("其他材料", "other"),
                        ],
                        value="other",
                        label="这批材料是什么？",
                    )
                owner_upload_files = gr.File(
                    label="上传视频、照片或 PDF",
                    file_count="multiple",
                    file_types=[
                        ".mp4",
                        ".mov",
                        ".avi",
                        ".jpg",
                        ".jpeg",
                        ".png",
                        ".webp",
                        ".pdf",
                    ],
                    type="filepath",
                )
                owner_add_files = gr.Button("加入当前事故材料", variant="primary")
                with gr.Accordion("这是一起新事故？", open=False):
                    gr.Markdown("填写三项基本信息即可创建，其他材料可以稍后补充。")
                    with gr.Row():
                        owner_accident_time = gr.Textbox(
                            label="事故时间",
                            placeholder="2026-07-20T08:30:00+08:00",
                        )
                        owner_location = gr.Textbox(label="事故地点")
                        owner_delivery_date = gr.Textbox(
                            label="认定书送达日期（可稍后补充）",
                            placeholder="2026-07-28",
                        )
                    owner_create_case = gr.Button("创建这起事故", variant="secondary")

        with gr.Accordion(
            "保险公司协作台",
            open=False,
            elem_classes=["professional"],
        ):
            gr.Markdown(
                "理赔人员只需完成三件事：提醒车主处理最紧急事项、协助补齐材料、"
                "核对文书是否具备人工提交条件。"
            )
            insurer_summary = gr.HTML()
            with gr.Tabs():
                with gr.Tab("协助车主"):
                    insurer_task_table = gr.Dataframe(
                        headers=INSURER_TASK_HEADERS,
                        datatype=["str"] * len(INSURER_TASK_HEADERS),
                        interactive=False,
                        wrap=True,
                        label="当前协助清单",
                    )
                with gr.Tab("补充材料"):
                    gr.Markdown(
                        "理赔员可在这里直接补充当前事故材料；文件仍写入同一案件目录"
                        "和证据图谱，不会形成第二套存储。"
                    )
                    insurer_material_table = gr.Dataframe(
                        headers=OWNER_MATERIAL_HEADERS,
                        datatype=["str"] * len(OWNER_MATERIAL_HEADERS),
                        interactive=False,
                        wrap=True,
                        label="材料协作情况",
                    )
                    gr.Markdown(
                        "显示“已保存，可查看”即代表材料已加入同一事故。"
                        "点击表格中的材料名称，下方会出现原文件。",
                        elem_classes=["material-help"],
                    )
                    insurer_material_preview_note = gr.Markdown(
                        "尚未选择材料。点击上方表格中的材料名称查看原文件。"
                    )
                    insurer_material_preview = gr.File(
                        label="查看或下载所选材料",
                        interactive=False,
                    )
                    insurer_material_role = gr.Dropdown(
                        [
                            ("事故认定书", "accident_determination"),
                            ("送达材料", "delivery_information"),
                            ("行车记录仪", "dashcam_video"),
                            ("现场照片 / 监控", "scene_photo"),
                            ("车辆登记 / 号牌", "vehicle_registration"),
                            ("合格证 / CCC", "vehicle_certificate_ccc"),
                            ("鉴定报告", "appraisal_report"),
                            ("保险材料", "insurance_policy"),
                            ("其他材料", "other"),
                        ],
                        value="other",
                        label="材料类型",
                    )
                    insurer_upload_files = gr.File(
                        label="选择保险公司补充的照片、视频或 PDF",
                        file_count="multiple",
                        file_types=[
                            ".mp4",
                            ".mov",
                            ".avi",
                            ".jpg",
                            ".jpeg",
                            ".png",
                            ".webp",
                            ".pdf",
                        ],
                        type="filepath",
                    )
                    insurer_material_provider = gr.State("保险公司补充")
                    insurer_add_files = gr.Button(
                        "补充到当前事故",
                        variant="primary",
                    )
                with gr.Tab("审核文书"):
                    insurer_review_summary = gr.HTML()
                    with gr.Row():
                        insurer_approval_decision = gr.Radio(
                            [
                                ("批准供人工提交", "approved"),
                                ("拒绝", "rejected"),
                                ("要求修改", "changes_requested"),
                            ],
                            value="changes_requested",
                            label="审核结论（仅针对上方这份复核申请草稿）",
                        )
                        insurer_approver = gr.Textbox(label="审核人姓名")
                    insurer_comments = gr.Textbox(
                        label="审核意见",
                        lines=3,
                        placeholder="请说明需补充的事实、证据或修改内容。",
                    )
                    insurer_decide_button = gr.Button(
                        "保存文书审核意见",
                        variant="primary",
                    )

        with gr.Accordion(
            "高级详情与技术诊断（仅在异常时展开）",
            open=False,
            elem_classes=["professional", "advanced-workbench"],
        ):
            gr.Markdown(
                "以下区域供法律审核人员和技术演示使用，普通车主与理赔人员无需操作。"
                "所有对外文书默认 `draft`；批准后也只允许人工提交，系统不会自动发送。",
                elem_classes=["safety"],
            )
            with gr.Row():
                professional_case_id = gr.Textbox(
                    label="case_id",
                    value=initial_case_id,
                    interactive=False,
                )
                professional_thread_id = gr.Textbox(
                    label="thread_id", interactive=False
                )
                mode = gr.Radio(
                    [(item.value, item.value) for item in WorkflowMode],
                    value=default_mode,
                    label="运行模式",
                )
                refresh_case = gr.Button("刷新 / 恢复案件")

            with gr.Tabs():
                with gr.Tab("案件创建", id="case"):
                    with gr.Row():
                        accident_time = gr.Textbox(
                            label="事故时间（ISO，可选）",
                            placeholder="2026-07-20T08:30:00+08:00",
                        )
                        location = gr.Textbox(label="事故地点")
                        jurisdiction = gr.Textbox(label="管辖地区", value="CN")
                    with gr.Row():
                        party_role = gr.Dropdown(
                            [(item.value, item.value) for item in PartyRole],
                            value=PartyRole.INSURED_DRIVER.value,
                            label="当事人角色",
                        )
                        delivery_date = gr.Textbox(
                            label="送达日期（可选）",
                            placeholder="2026-07-28",
                        )
                        default_role = gr.Dropdown(
                            [(item.value, item.value) for item in SourceRole],
                            value=SourceRole.OTHER.value,
                            label="本批材料默认分类",
                        )
                    upload_files = gr.File(
                        label="批量上传视频、图片、PDF",
                        file_count="multiple",
                        file_types=[
                            ".mp4",
                            ".mov",
                            ".avi",
                            ".jpg",
                            ".jpeg",
                            ".png",
                            ".webp",
                            ".pdf",
                        ],
                        type="filepath",
                    )
                    with gr.Row():
                        save_case = gr.Button("保存案件但暂不运行")
                        save_and_start = gr.Button("保存并开始分析", variant="primary")
                        add_files = gr.Button("向当前案件追加材料")
                        reconstruct = gr.Button("执行/复用证据还原")
                    with gr.Row():
                        fixture = gr.Dropdown(
                            [
                                ("Golden Case（主演示）", "golden"),
                                ("证据不足", "demo_b"),
                                ("事实冲突", "demo_c"),
                            ],
                            value="golden",
                            label="合成演示案件",
                        )
                        load_fixture = gr.Button("载入合成案件", variant="primary")
                    source_table = gr.Dataframe(
                        headers=SOURCE_HEADERS,
                        datatype=["str"] * len(SOURCE_HEADERS),
                        interactive=False,
                        wrap=True,
                        label="材料清单（真实 Evidence Graph）",
                    )
                    with gr.Row():
                        correction_source_id = gr.Textbox(label="待修正 Evidence ID")
                        correction_role = gr.Dropdown(
                            [(item.value, item.value) for item in SourceRole],
                            value=SourceRole.OTHER.value,
                            label="修正后的分类",
                        )
                        correct_role = gr.Button("记录分类修正")

                with gr.Tab("执行进度", id="progress"):
                    with gr.Row():
                        start_button = gr.Button("开始分析", variant="primary")
                        pause_button = gr.Button("安全停止")
                        resume_button = gr.Button("从 checkpoint 恢复")
                        retry_button = gr.Button("仅重试失败节点")
                    progress_overview_json = gr.HTML(label="总体进度 / checkpoint")
                    progress_table = gr.HTML(label="节点执行摘要")

                with gr.Tab("证据时间线", id="evidence"):
                    with gr.Row():
                        phase_filter = gr.Dropdown(
                            ["全部", "碰撞前", "碰撞时", "碰撞后", "阶段不确定"],
                            value="全部",
                            label="阶段",
                        )
                        source_filter = gr.Dropdown(
                            ["全部", *[item.value for item in SourceRole]],
                            value="全部",
                            label="来源分类",
                        )
                        fact_status_filter = gr.Dropdown(
                            [
                                "全部",
                                "confirmed",
                                "unverified",
                                "disputed",
                                "rejected",
                            ],
                            value="全部",
                            label="事实状态",
                        )
                        apply_timeline_filter = gr.Button("应用筛选")
                    timeline_table = gr.HTML(label="证据时间线与冲突摘要")
                    evidence_choice = gr.Dropdown(label="查看原始证据")
                    with gr.Row():
                        original_file = gr.File(label="安全下载 / 打开")
                        image_preview = gr.Image(label="图片/关键帧", interactive=False)
                        video_preview = gr.Video(label="视频", interactive=False)
                    evidence_metadata = gr.JSON(label="证据元数据")

                with gr.Tab("责任分析", id="liability"):
                    liability_json = gr.HTML(label="车辆属性 / 责任 / 赔偿摘要")

                with gr.Tab("权益任务", id="rights"):
                    rights_json = gr.HTML(
                        label="送达日期、Deadlines、任务与复核草稿摘要"
                    )

                with gr.Tab("人工批准", id="approval"):
                    approval_json = gr.HTML(label="待审批文书 / Policy Gate 摘要")
                    with gr.Row():
                        approval_decision = gr.Radio(
                            [
                                ("批准供人工提交", "approved"),
                                ("拒绝", "rejected"),
                                ("要求修改", "changes_requested"),
                            ],
                            value="changes_requested",
                            label="决定",
                        )
                        approver = gr.Textbox(label="审批人")
                    approval_comments = gr.Textbox(label="审批意见", lines=3)
                    decide_button = gr.Button("记录人工决定", variant="primary")

                with gr.Tab("审计日志", id="audit"):
                    with gr.Row():
                        audit_node = gr.Dropdown(
                            [
                                "全部",
                                "intake",
                                "evidence",
                                "legal_retrieval",
                                "vehicle_nature",
                                "liability",
                                "rights_workflow",
                                "verifier",
                                "human_approval",
                            ],
                            value="全部",
                            label="节点",
                        )
                        audit_event = gr.Textbox(
                            value="全部",
                            label="事件类型（全部或精确值）",
                        )
                        audit_result = gr.Textbox(
                            value="全部",
                            label="结果（全部或精确值）",
                        )
                        audit_refresh = gr.Button("刷新审计")
                    audit_table = gr.Dataframe(
                        headers=AUDIT_HEADERS,
                        datatype=["str"] * len(AUDIT_HEADERS),
                        interactive=False,
                        wrap=True,
                        label="按需加载；点击刷新后最多显示 20 条筛选结果",
                    )

                with gr.Tab("导出报告", id="report"):
                    gr.Markdown(
                        "报告包含案件摘要、证据链、责任与赔偿分层、权益期限、"
                        "复核草稿、Verifier/Policy Gate、审批、法律引用、审计与免责声明。"
                    )
                    export_button = gr.Button(
                        "生成 Markdown + HTML 完整报告",
                        variant="primary",
                    )
                    with gr.Row():
                        markdown_report = gr.File(label="Markdown")
                        html_report = gr.File(label="HTML")
                    raw_state = gr.JSON(label="当前真实 CaseState（调试/验收）")

        load_outputs = [
            case_id_state,
            thread_id_state,
            accident_time,
            location,
            jurisdiction,
            party_role,
            delivery_date,
            owner_overview,
            owner_next_action,
            owner_appraisal_guidance,
            owner_task_table,
            owner_task_choice,
            owner_material_table,
            insurer_summary,
            insurer_task_table,
            insurer_material_table,
            insurer_review_summary,
            source_table,
            progress_table,
            progress_overview_json,
            timeline_table,
            evidence_choice,
            liability_json,
            rights_json,
            approval_json,
            audit_table,
            workflow_state,
            owner_material_preview,
            owner_material_preview_note,
            insurer_material_preview,
            insurer_material_preview_note,
            communication_script,
            communication_status,
            notice,
        ]

        def preview_selected_material(
            selected_case_id: str,
            event: gr.SelectData,
        ) -> tuple[str | None, str]:
            return controller.preview_material_row(selected_case_id, event.index)

        # Gradio detects event parameters from the runtime type.  This module
        # postpones annotations, so make the local Gradio type explicit.
        preview_selected_material.__annotations__["event"] = gr.SelectData
        owner_material_table.select(
            preview_selected_material,
            [case_id_state],
            [owner_material_preview, owner_material_preview_note],
        )
        insurer_material_table.select(
            preview_selected_material,
            [case_id_state],
            [insurer_material_preview, insurer_material_preview_note],
        )
        refresh_case.click(
            controller.load_case,
            [selected_case, mode],
            load_outputs,
        )
        owner_refresh.click(
            controller.load_case,
            [selected_case, mode],
            load_outputs,
        )
        if initial_case_id:
            app.load(
                controller.load_case,
                [selected_case, mode],
                load_outputs,
            )
        selected_case.input(
            controller.load_case,
            [selected_case, mode],
            load_outputs,
        )
        case_id_state.change(
            lambda case_id: case_id,
            [case_id_state],
            [professional_case_id],
        )
        thread_id_state.change(
            lambda thread_id: thread_id,
            [thread_id_state],
            [professional_thread_id],
        )
        case_create_inputs = [
            accident_time,
            location,
            jurisdiction,
            party_role,
            delivery_date,
            upload_files,
            default_role,
        ]
        case_create_outputs = [
            case_id_state,
            thread_id_state,
            source_table,
            selected_case,
            notice,
        ]
        save_case.click(
            controller.create_case,
            case_create_inputs,
            case_create_outputs,
        )
        save_and_start_event = save_and_start.click(
            controller.create_case,
            case_create_inputs,
            case_create_outputs,
        )
        load_fixture_event = load_fixture.click(
            controller.seed_fixture,
            [fixture],
            [
                case_id_state,
                thread_id_state,
                source_table,
                selected_case,
                notice,
            ],
        )
        load_fixture_event.then(
            controller.load_case,
            [case_id_state, mode],
            load_outputs,
        )
        owner_load_fixture_event = owner_load_fixture.click(
            controller.seed_fixture,
            [owner_fixture],
            [
                case_id_state,
                thread_id_state,
                source_table,
                selected_case,
                notice,
            ],
        )
        owner_load_fixture_event.then(
            controller.load_case,
            [case_id_state, mode],
            load_outputs,
        )
        owner_create_event = owner_create_case.click(
            controller.create_case,
            [
                owner_accident_time,
                owner_location,
                gr.State("CN"),
                gr.State(PartyRole.INSURED_DRIVER.value),
                owner_delivery_date,
                owner_upload_files,
                owner_material_role,
            ],
            case_create_outputs,
        )
        owner_create_event.then(
            controller.load_case,
            [case_id_state, mode],
            load_outputs,
        )
        add_files.click(
            controller.add_files,
            [case_id_state, upload_files, default_role],
            [source_table, notice],
        )
        owner_add_files.click(
            controller.add_collaboration_files,
            [
                case_id_state,
                owner_upload_files,
                owner_material_role,
                material_provider,
            ],
            [
                owner_material_table,
                insurer_material_table,
                source_table,
                notice,
            ],
        )
        insurer_add_files.click(
            controller.add_collaboration_files,
            [
                case_id_state,
                insurer_upload_files,
                insurer_material_role,
                insurer_material_provider,
            ],
            [
                owner_material_table,
                insurer_material_table,
                source_table,
                notice,
            ],
        )
        owner_complete_task.click(
            controller.complete_owner_task,
            [case_id_state, owner_task_choice, workflow_state],
            [
                owner_task_table,
                owner_task_choice,
                owner_next_action,
                insurer_task_table,
                notice,
            ],
        )
        generate_communication.click(
            controller.generate_communication,
            [communication_target, procedure_stage, workflow_state, case_id_state],
            [communication_script, communication_status],
        )
        communication_target.change(
            controller.mark_communication_stale,
            [communication_target, procedure_stage],
            [communication_script, communication_status],
        )
        procedure_stage.change(
            controller.mark_communication_stale,
            [communication_target, procedure_stage],
            [communication_script, communication_status],
        )
        save_communication.click(
            controller.record_communication,
            [case_id_state, communication_target, communication_result],
            [notice],
        )
        correct_role.click(
            controller.change_role,
            [case_id_state, correction_source_id, correction_role],
            [source_table, notice],
        )
        reconstruct.click(
            controller.reconstruct,
            [case_id_state, mode],
            [source_table, notice],
        )

        workflow_outputs = [
            thread_id_state,
            owner_overview,
            owner_next_action,
            owner_appraisal_guidance,
            owner_task_table,
            owner_task_choice,
            owner_material_table,
            insurer_summary,
            insurer_task_table,
            insurer_material_table,
            insurer_review_summary,
            progress_table,
            progress_overview_json,
            workflow_state,
            liability_json,
            rights_json,
            approval_json,
            audit_table,
            notice,
        ]
        owner_start.click(
            controller.start,
            [case_id_state, mode],
            workflow_outputs,
            concurrency_limit=1,
            concurrency_id="workflow",
        )
        start_button.click(
            controller.start,
            [case_id_state, mode],
            workflow_outputs,
            concurrency_limit=1,
            concurrency_id="workflow",
        )
        save_and_start_event.then(
            controller.start,
            [case_id_state, mode],
            workflow_outputs,
            concurrency_limit=1,
            concurrency_id="workflow",
        )
        resume_button.click(
            controller.resume,
            [thread_id_state, mode],
            workflow_outputs,
            concurrency_limit=1,
            concurrency_id="workflow",
        )
        retry_button.click(
            controller.retry,
            [thread_id_state, mode],
            workflow_outputs,
            concurrency_limit=1,
            concurrency_id="workflow",
        )
        pause_button.click(
            controller.pause,
            [thread_id_state],
            [notice],
            concurrency_limit=4,
        )

        apply_timeline_filter.click(
            controller.filter_timeline,
            [
                case_id_state,
                phase_filter,
                source_filter,
                fact_status_filter,
            ],
            [timeline_table],
        )
        evidence_choice.change(
            controller.preview_source,
            [case_id_state, evidence_choice],
            [original_file, image_preview, video_preview, evidence_metadata],
        )
        decide_button.click(
            controller.decide,
            [
                thread_id_state,
                mode,
                approval_decision,
                approver,
                approval_comments,
            ],
            [
                approval_json,
                insurer_review_summary,
                workflow_state,
                notice,
            ],
        )
        approval_decision.change(
            controller.approval_button_state,
            [approval_decision, workflow_state],
            [decide_button],
        )
        insurer_decide_button.click(
            controller.decide,
            [
                thread_id_state,
                mode,
                insurer_approval_decision,
                insurer_approver,
                insurer_comments,
            ],
            [
                approval_json,
                insurer_review_summary,
                workflow_state,
                notice,
            ],
        )
        insurer_approval_decision.change(
            controller.approval_button_state,
            [insurer_approval_decision, workflow_state],
            [insurer_decide_button],
        )
        audit_refresh.click(
            controller.refresh_audit,
            [case_id_state, audit_node, audit_event, audit_result],
            [audit_table],
        )
        export_button.click(
            controller.export_report,
            [case_id_state, workflow_state],
            [markdown_report, html_report, notice],
        ).then(lambda state: state, [workflow_state], [raw_state])

    return app


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.getenv("GRADIO_SERVER_NAME", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
    )
    parser.add_argument("--case-root", default=os.getenv("CASE_ROOT"))
    parser.add_argument("--checkpoint", default=os.getenv("ORCHESTRATOR_CHECKPOINT_DB"))
    parser.add_argument("--report-root", default=os.getenv("REPORT_ROOT"))
    args = parser.parse_args()
    app = build_app(
        case_root=args.case_root,
        checkpoint_path=args.checkpoint,
        report_root=args.report_root,
    )
    allowed = [
        str(Path(args.case_root or "data/cases").resolve()),
        str(Path(args.report_root or "artifacts/demo_reports").resolve()),
    ]
    app.queue(max_size=16, default_concurrency_limit=4).launch(
        server_name=args.host,
        server_port=args.port,
        share=False,
        show_error=True,
        allowed_paths=allowed,
        css=CSS,
    )
    return 0


def _file_paths(value: Any) -> list[Path]:
    if not value:
        return []
    values = value if isinstance(value, list) else [value]
    result: list[Path] = []
    for item in values:
        if isinstance(item, (str, Path)):
            result.append(Path(item))
        elif hasattr(item, "path"):
            result.append(Path(item.path))
        elif isinstance(item, dict) and item.get("path"):
            result.append(Path(item["path"]))
        else:
            raise ValueError(f"不支持的上传对象：{type(item).__name__}")
    return result


def _parse_datetime(value: str) -> datetime | None:
    return datetime.fromisoformat(value) if value.strip() else None


def _parse_date(value: str) -> date | None:
    return date.fromisoformat(value) if value.strip() else None


def _human_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _case_location_fallback(case_id: str) -> str:
    experience_labels = {
        "CASE-EXP-A-": "合成体验 · 材料较完整",
        "CASE-EXP-B-": "合成体验 · 车辆属性证据不足",
        "CASE-EXP-C-": "合成体验 · 材料相互冲突",
    }
    for prefix, label in experience_labels.items():
        if case_id.startswith(prefix):
            return label
    return "新建事故（地点待补充）"


def _select_initial_case(choices: list[tuple[str, str]]) -> str | None:
    real_case = next(
        (
            value
            for _, value in choices
            if value != "CASE-GOLDEN-DEMO" and not value.startswith("CASE-EXP-")
        ),
        None,
    )
    if real_case:
        return real_case
    if any(value == "CASE-GOLDEN-DEMO" for _, value in choices):
        return "CASE-GOLDEN-DEMO"
    return choices[0][1] if choices else None


if __name__ == "__main__":
    raise SystemExit(main())
