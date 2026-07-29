"""Build workflows from natural-language requirements → local YAML config."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.agent.workflow_export import export_workflow
from src.agent.workflow_registry import get_registry
from src.agent.workflow_schema import normalize_workflow

_BUILD_HINTS = (
    "设计工作流",
    "创建工作流",
    "生成工作流",
    "配置工作流",
    "搭建工作流",
    "新建工作流",
    "build workflow",
    "create workflow",
)
_EXPORT_HINTS = (
    "导出工作流",
    "export workflow",
    "导出为dify",
    "导出langchain",
    "导出 yaml",
    "导出json",
)


def wants_build(query: str) -> bool:
    q = query.lower()
    return any(h.lower() in q or h in query for h in _BUILD_HINTS)


def wants_export(query: str) -> bool:
    q = query.lower()
    return any(h.lower() in q or h in query for h in _EXPORT_HINTS)


def _slug(text: str, fallback: str = "custom_flow") -> str:
    text = text.strip().lower()
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        return fallback
    ascii_id = re.sub(r"[^a-z0-9_]+", "", text)
    if len(ascii_id) >= 8:
        return ascii_id[:48]
    return f"{fallback}_{abs(hash(text)) % 10_000_000}"


def _extract_requirement(query: str) -> str:
    q = query.strip()
    for h in _BUILD_HINTS:
        q = q.replace(h, " ")
    q = re.sub(r"[:：]\s*", " ", q)
    return q.strip() or query.strip()


def heuristic_build(requirement: str) -> dict[str, Any]:
    """Rule-based workflow synthesis (works offline / without LLM)."""
    req = requirement.strip()
    rid = _slug(req[:24], "custom_flow")
    title = req[:40] + ("…" if len(req) > 40 else "")
    keywords = [w for w in re.split(r"[\s,，、]+", req) if len(w) >= 2][:8]
    keywords = list(dict.fromkeys(keywords + ["工作流", rid]))

    steps: list[dict[str, Any]] = [
        {
            "id": "retrieve",
            "label": "检索相关制度/知识",
            "tool": "kb_search",
            "args": {"query": req[:120]},
        }
    ]
    if any(k in req for k in ["入职", "账号", "VPN", "开通"]):
        steps.append({"id": "vpn", "label": "账号/VPN 指引", "tool": "kb_search", "args": {"query": "VPN MFA 账号开通"}})
        steps.append({"id": "save_onboard", "label": "写入开通备忘", "tool": "write_note", "args": {"note": f"自动配置：{req}"}})
    elif any(k in req for k in ["请假", "年假", "审批"]):
        steps.append({"id": "leave_policy", "label": "核对请假政策", "tool": "kb_search", "args": {"query": "请假 提前 审批"}})
        steps.append({"id": "save_leave", "label": "写入请假备忘", "tool": "write_note", "args": {"note": f"请假流程备忘：{req}"}})
    elif any(k in req for k in ["合规", "涉密", "安全", "外发"]):
        steps.append({"id": "security", "label": "合规条款检索", "tool": "kb_search", "args": {"query": "涉密 AI 外发 微信"}})
        steps.append({"id": "save_sec", "label": "写入合规备忘", "tool": "write_note", "args": {"note": f"合规自检：{req}"}})
    elif any(k in req for k in ["开发", "交接", "ROCm", "GPU", "技能"]):
        steps.append({"id": "files", "label": "列出工作文件", "tool": "list_files", "args": {}})
        steps.append({"id": "stats", "label": "知识库状态", "tool": "kb_stats", "args": {}})
        steps.append({"id": "skills", "label": "列出可用技能", "tool": "list_skills", "args": {}})
    else:
        steps.append({"id": "memory", "label": "回忆本地偏好", "tool": "recall_memory", "args": {}})
        steps.append({"id": "note", "label": "写入执行备忘", "tool": "write_note", "args": {"note": f"工作流需求：{req}"}})

    steps.append(
        {
            "id": "fact",
            "label": "固化配置摘要",
            "tool": "save_fact",
            "args": {"fact": f"本地工作流已配置：{title}"},
        }
    )

    return normalize_workflow(
        {
            "id": rid,
            "title": f"自动配置 · {title}",
            "description": f"由需求自动生成：{req}",
            "requirement": req,
            "keywords": keywords,
            "engine": "private_local",
            "steps": steps,
            "exports": ["yaml", "json", "dify", "langchain"],
        },
        rid,
    )


def llm_refine_workflow(llm: Any, requirement: str, draft: dict[str, Any]) -> dict[str, Any]:
    if llm is None:
        return draft
    prompt = [
        {
            "role": "system",
            "content": (
                "You design local private agent workflows. "
                "Reply with ONLY a JSON object: "
                '{"id":"...","title":"...","description":"...","keywords":["..."],'
                '"steps":[{"id":"...","label":"...","tool":"kb_search|write_note|save_fact|list_files|kb_stats|recall_memory|list_skills","args":{...}}]}'
                " Tools must be from the allowed list. Chinese titles OK. Max 6 steps."
            ),
        },
        {
            "role": "user",
            "content": f"Requirement:\n{requirement}\n\nDraft JSON:\n{json.dumps(draft, ensure_ascii=False)}",
        },
    ]
    try:
        raw = llm.chat(prompt, max_tokens=700)
        m = re.search(r"\{.*\}", raw or "", re.DOTALL)
        if not m:
            return draft
        data = json.loads(m.group(0))
        data["requirement"] = requirement
        data.setdefault("id", draft["id"])
        return normalize_workflow(data, draft["id"])
    except Exception:  # noqa: BLE001
        return draft


def build_workflow_from_requirement(
    requirement: str,
    *,
    llm: Any | None = None,
    auto_export: bool = True,
) -> tuple[dict[str, Any], Path, dict[str, str]]:
    req = _extract_requirement(requirement)
    draft = heuristic_build(req)
    wf = llm_refine_workflow(llm, req, draft) if llm is not None else draft
    path = get_registry().save(wf)
    exports: dict[str, str] = {}
    if auto_export:
        try:
            exports = export_workflow(wf["id"])
        except Exception:  # noqa: BLE001
            exports = {}
    return wf, Path(path), exports


def build_and_summarize(requirement: str, llm: Any | None = None) -> str:
    wf, path, exports = build_workflow_from_requirement(requirement, llm=llm, auto_export=True)
    lines = [
        "已根据需求在本地完成工作流配置。",
        f"- id: `{wf['id']}`",
        f"- 标题: {wf['title']}",
        f"- 配置文件: `{path}`",
        f"- 步骤数: {len(wf.get('steps') or [])}",
        "",
        "步骤预览：",
    ]
    for i, s in enumerate(wf.get("steps") or [], 1):
        lines.append(f"  {i}. {s.get('label')} → tool=`{s.get('tool')}`")
    if exports:
        lines.append("")
        lines.append("多格式导出（Dify / LangChain / YAML / JSON）：")
        for k, p in exports.items():
            lines.append(f"- {k}: `{p}`")
    lines.append("")
    lines.append(f"运行：说「执行工作流 {wf['id']}」或在工作流模式直接触发关键词。")
    return "\n".join(lines)


def parse_export_id(query: str) -> str | None:
    reg = get_registry().all()
    for wid in reg:
        if wid in query:
            return wid
    m = re.search(r"(?:导出工作流|export workflow)\s*[：:]?\s*([A-Za-z0-9_\-]+)", query, re.I)
    if m and m.group(1) in reg:
        return m.group(1)
    return None
