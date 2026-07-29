"""Office / enterprise workflow automation — registry-backed, exportable graphs."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.agent.tools import ToolRegistry
from src.agent.workflow_registry import BUILTIN_WORKFLOWS, get_registry
from src.agent.workflow_schema import steps_as_legacy_tuples


@dataclass
class WorkflowStepResult:
    name: str
    detail: str


@dataclass
class WorkflowResult:
    workflow_id: str
    title: str
    steps: list[WorkflowStepResult] = field(default_factory=list)
    summary: str = ""


# Back-compat alias for older imports / demos
WORKFLOWS: dict = BUILTIN_WORKFLOWS


def match_workflow(query: str) -> str | None:
    text = query.lower()
    reg = get_registry().all()
    # prefer longer keyword hits
    best: tuple[int, str] | None = None
    for wid, meta in reg.items():
        for k in meta.get("keywords") or []:
            if k.lower() in text or k in query:
                score = len(k)
                if best is None or score > best[0]:
                    best = (score, wid)
        if wid in query or wid in text:
            best = (max(best[0] if best else 0, len(wid)), wid)
    if best:
        return best[1]
    if "执行工作流" in query or "运行工作流" in query:
        # try trailing token
        parts = query.replace("：", " ").replace(":", " ").split()
        for p in reversed(parts):
            if p in reg:
                return p
    if "工作流" in query or "自动化流程" in query:
        return "leave_request"
    return None


def list_workflows() -> str:
    reg = get_registry().all()
    lines = ["可用办公工作流（本地 YAML，可导出 Dify/LangChain）："]
    for wid, meta in reg.items():
        kws = ", ".join((meta.get("keywords") or [])[:3])
        lines.append(f"- {wid}: {meta.get('title')}（关键词：{kws}）")
    lines.append("提示：说「设计工作流：…」可按需求自动生成并落盘；「导出工作流 <id>」输出多格式。")
    return "\n".join(lines)


def run_workflow(tools: ToolRegistry, workflow_id: str) -> WorkflowResult:
    meta = get_registry().get(workflow_id)
    if not meta:
        return WorkflowResult(
            workflow_id=workflow_id,
            title="unknown",
            summary=f"未知工作流: {workflow_id}\n{list_workflows()}",
        )
    result = WorkflowResult(workflow_id=workflow_id, title=str(meta.get("title") or workflow_id))
    bullets: list[str] = []
    for step_id, label, call in steps_as_legacy_tuples(meta):
        tool_name = call["tool"]
        args = call.get("args") or {}
        # avoid recursive run_workflow via tool if present
        if tool_name == "run_workflow":
            out = f"(skip nested run_workflow)"
        else:
            out = tools.run(tool_name, args).output
        snippet = out.strip().replace("\n", " ")
        if len(snippet) > 280:
            snippet = snippet[:280] + "…"
        result.steps.append(WorkflowStepResult(name=f"{step_id}:{label}", detail=snippet))
        bullets.append(f"- {label}：{snippet}")
    result.summary = (
        f"【{meta.get('title')}】已自动执行 {len(result.steps)} 步：\n"
        + "\n".join(bullets)
        + "\n\n配置文件：data/workflows/"
        + f"{workflow_id}.yaml"
        + "\n可导出：yaml / json / dify / langchain（说「导出工作流 "
        + workflow_id
        + "」）。"
        + "\n请按以上检索结果办理；如需正式制度以知识库原文为准。"
    )
    return result
