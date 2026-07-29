"""Export workflows to portable formats (generic / Dify-like / LangChain-like)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from src.agent.workflow_registry import get_registry
from src.config import resolve_data_path


def export_dir() -> Path:
    return resolve_data_path("data/exports/workflows")


def export_generic_yaml(workflow: dict[str, Any]) -> str:
    return yaml.safe_dump(workflow, allow_unicode=True, sort_keys=False)


def export_generic_json(workflow: dict[str, Any]) -> str:
    return json.dumps(workflow, ensure_ascii=False, indent=2)


def export_dify_like(workflow: dict[str, Any]) -> str:
    """Dify-style workflow DSL (compatible shape; importable as reference)."""
    nodes = [
        {
            "id": "start",
            "data": {"type": "start", "title": "开始"},
        }
    ]
    edges = []
    prev = "start"
    for i, step in enumerate(workflow.get("steps") or []):
        nid = str(step.get("id") or f"node_{i}")
        tool = step.get("tool") or "kb_search"
        node_type = "knowledge-retrieval" if tool == "kb_search" else "tool"
        nodes.append(
            {
                "id": nid,
                "data": {
                    "type": node_type,
                    "title": step.get("label") or nid,
                    "tool_name": tool,
                    "tool_parameters": step.get("args") or {},
                    "desc": step.get("label") or "",
                },
            }
        )
        edges.append({"id": f"e_{prev}_{nid}", "source": prev, "target": nid})
        prev = nid
    nodes.append({"id": "end", "data": {"type": "end", "title": "结束"}})
    edges.append({"id": f"e_{prev}_end", "source": prev, "target": "end"})
    payload = {
        "app": {
            "name": workflow.get("title") or workflow.get("id"),
            "mode": "workflow",
            "description": workflow.get("description") or workflow.get("requirement") or "",
        },
        "workflow": {
            "graph": {"nodes": nodes, "edges": edges},
            "features": {"file_upload": False},
        },
        "kind": "dify_workflow_dsl_like",
        "version": "0.1.0",
        "source_engine": "PrivateLocalAgent",
    }
    return yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)


def export_langchain_like(workflow: dict[str, Any]) -> str:
    """LangChain-style runnable chain description (YAML + pseudo LCEL)."""
    steps = workflow.get("steps") or []
    chain = []
    lcel_parts = []
    for step in steps:
        tool = step.get("tool") or "kb_search"
        chain.append(
            {
                "name": step.get("id"),
                "runnable": f"ToolNode:{tool}",
                "kwargs": step.get("args") or {},
                "description": step.get("label"),
            }
        )
        lcel_parts.append(f'ToolNode("{tool}")')
    payload = {
        "kind": "langchain_runnable_sequence_like",
        "name": workflow.get("id"),
        "title": workflow.get("title"),
        "description": workflow.get("description") or "",
        "lcel": " | ".join(lcel_parts) if lcel_parts else "RunnablePassthrough()",
        "sequence": chain,
        "entry": "RunnableSequence",
        "source_engine": "PrivateLocalAgent",
        "notes": "Portable description — map ToolNode to langchain_core.tools / langgraph nodes locally.",
    }
    return yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)


EXPORTERS = {
    "yaml": ("workflow.yaml", export_generic_yaml),
    "json": ("workflow.json", export_generic_json),
    "dify": ("dify_workflow.yaml", export_dify_like),
    "langchain": ("langchain_chain.yaml", export_langchain_like),
}


def export_workflow(
    workflow_id: str,
    formats: list[str] | None = None,
    out_dir: Path | None = None,
) -> dict[str, str]:
    """Export a registered workflow to one or more formats; return path map."""
    from src.security.paths import is_under, sanitize_id

    reg = get_registry()
    safe_id = sanitize_id(workflow_id, "workflow")
    wf = reg.get(safe_id) or reg.get(workflow_id)
    if not wf:
        raise KeyError(f"unknown workflow: {workflow_id}")
    fmts = formats or ["yaml", "json", "dify", "langchain"]
    root = export_dir().resolve()
    base = (Path(out_dir).resolve() if out_dir else (root / safe_id))
    if not is_under(base, root):
        base = root / safe_id
    base.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for fmt in fmts:
        key = fmt.lower().strip()
        if key not in EXPORTERS:
            continue
        filename, fn = EXPORTERS[key]
        path = base / filename
        path.write_text(fn(wf), encoding="utf-8")
        written[key] = str(path)
    native = base / f"{safe_id}.native.yaml"
    native.write_text(export_generic_yaml(wf), encoding="utf-8")
    written.setdefault("native", str(native))
    return written


def export_all_formats_text(workflow_id: str) -> str:
    paths = export_workflow(workflow_id)
    lines = [f"已导出工作流 `{workflow_id}`："]
    for k, p in paths.items():
        lines.append(f"- {k}: {p}")
    return "\n".join(lines)
