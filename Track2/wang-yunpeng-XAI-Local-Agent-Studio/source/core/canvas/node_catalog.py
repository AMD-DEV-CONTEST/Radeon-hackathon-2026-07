"""画布节点注册表（Node Catalog）。

Phase 0 收敛版：4 类节点（agent / tool / memory / text）。
Tool 类下挂真实实例（ToolBus 工具 + Skills + MCP），供前端 NodePalette
拖拽实例化。注册表驱动，前端不写死。
"""
from __future__ import annotations

from typing import Any, Dict, List

# 4 类基础节点（类型级定义：渲染色/图标/默认 data schema）
NODE_TYPES: List[Dict[str, Any]] = [
    {
        "type": "agent",
        "label": "Agent 节点",
        "icon": "bot",
        "color": "violet",
        "description": "调用 LLM 推理（走 engine 推理链，含降级）",
        "defaultData": {"prompt": "", "model": ""},
        "configSchema": [
            {"key": "prompt", "label": "提示词", "kind": "textarea", "required": True},
            {"key": "model", "label": "模型（留空=当前激活）", "kind": "text"},
        ],
    },
    {
        "type": "tool",
        "label": "工具节点",
        "icon": "wrench",
        "color": "cyan",
        "description": "调用真实工具（ToolBus / Skill / MCP）",
        "defaultData": {"tool": "", "args": {}},
        "configSchema": [
            {"key": "tool", "label": "工具", "kind": "select", "required": True},
            {"key": "args", "label": "参数(JSON)", "kind": "json"},
        ],
    },
    {
        "type": "memory",
        "label": "记忆节点",
        "icon": "database",
        "color": "amber",
        "description": "读写 8 层记忆（memory_core）",
        "defaultData": {"op": "search", "layer": "long_term", "query": ""},
        "configSchema": [
            {"key": "op", "label": "操作", "kind": "select",
             "options": ["search", "add", "list"], "required": True},
            {"key": "layer", "label": "记忆层", "kind": "text"},
            {"key": "query", "label": "查询/内容", "kind": "textarea"},
        ],
    },
    {
        "type": "text",
        "label": "文本节点",
        "icon": "file-text",
        "color": "slate",
        "description": "静态文本/说明/中间产物",
        "defaultData": {"content": ""},
        "configSchema": [
            {"key": "content", "label": "内容", "kind": "textarea"},
        ],
    },
]


def _tool_instances(engine=None, capabilities=None) -> List[Dict[str, Any]]:
    """Tool 类下的真实可拖实例（ToolBus 工具 + capabilities 里的 skill/mcp）。"""
    items: List[Dict[str, Any]] = []
    # 1) ToolBus 注册工具
    try:
        bus = getattr(engine, "tool_bus", None)
        if bus is not None:
            for t in bus.list_tools():
                items.append({
                    "nodeType": "tool",
                    "id": f"toolbus:{t['name']}",
                    "label": t["name"],
                    "source": "toolbus",
                    "description": t.get("description", ""),
                    "data": {"tool": t["name"], "args": {}},
                })
    except Exception:
        pass
    # 2) capabilities（兼容两种结构：kind/label/desc 与 type/name/description）
    try:
        for c in (capabilities or []):
            ctype = (c.get("type") or c.get("kind") or "").lower()
            name = c.get("name") or c.get("label") or ""
            desc = c.get("description") or c.get("desc") or ""
            if ctype in ("skill", "mcp", "tool", "openclaw", "grok_build", "code", "kb"):
                items.append({
                    "nodeType": "tool",
                    "id": f"{ctype}:{name}",
                    "label": name,
                    "source": ctype,
                    "description": str(desc)[:80],
                    "data": {"tool": name, "args": {}, "via": ctype},
                })
    except Exception:
        pass
    return items


def build_catalog(engine=None, capabilities=None) -> Dict[str, Any]:
    """完整目录：4 类节点 + tool 实例清单。供 /api/canvas/node-catalog。"""
    return {
        "status": "ok",
        "nodeTypes": NODE_TYPES,
        "toolInstances": _tool_instances(engine, capabilities),
    }
