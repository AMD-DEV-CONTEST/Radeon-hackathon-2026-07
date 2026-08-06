"""Canvas-as-Context —— 把当前画布序列化为对话系统提示词上下文。

设计目标（对齐 Buzz 的「Canvas 作为一等公民、可被 Agent 读写」理念）：
- 让对话模型「看见」用户正在编辑的画布（节点 / 连线 / 状态），作为共享工作空间上下文。
- 零依赖、纯标准库；与 XAI 的本地私有、单进程架构一致。
- 预算保护：估算 token 超预算时截断（保留结构，跳过冗长细节），绝不撑爆上下文。

用法：
    from core.canvas.context import build_canvas_context
    ctx = build_canvas_context(session_id, budget_tokens=600)
    # ctx 为空串表示该会话无画布内容（不注入）
"""

from __future__ import annotations

import sys

try:
    from ...core.app_store import canvas_peek
except ImportError:  # 从包内相对导入失败时用绝对导入兜底
    from core.app_store import canvas_peek  # type: ignore

__all__ = ["build_canvas_context"]


def _est_tokens(text: str) -> int:
    """极简 token 估算：中文约 1 token/字，英文约 0.3 token/词。
    粗估即可，目的是预算保护而非精确计费。"""
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    other = len(text) - cjk
    return int(cjk + other / 3)


def build_canvas_context(cid: str, budget_tokens: int = 600) -> str:
    """序列化画布为系统提示词上下文块。

    - cid: 画布 ID（通常等于会话 ID，因为前端按 session 存画布）。
    - budget_tokens: 上下文预算上限；超出则截断（保留结构，省略细节）。
    - 返回 "" 表示该画布不存在或无任何节点（调用方据此不注入）。
    """
    if not cid:
        return ""
    try:
        data = canvas_peek(cid)
    except Exception as e:  # 读画布失败不应阻断对话
        sys.stderr.write(f"[xai:canvas_context] peek failed for {cid}: {e}\n")
        sys.stderr.flush()
        return ""

    if not data:
        return ""
    nodes = data.get("nodes") or []
    edges = data.get("edges") or []
    if not nodes:
        return ""

    # ---- 节点描述 ----
    def _node_summary(n: dict) -> str:
        nd = n.get("data") or {}
        nid = n.get("id") or "?"
        label = nd.get("label") or nid
        ntype = nd.get("nodeType") or nd.get("type") or "node"
        bits = [f"节点 {nid}（{ntype}）"]
        if nd.get("status") and nd["status"] != "idle":
            bits.append(f"状态={nd['status']}")
        if nd.get("assignee"):
            bits.append(f"负责人={nd['assignee']}")
        return " · ".join(bits) + f"：{label}"

    lines = [f"[共享画布 {cid}] 当前 {len(nodes)} 个节点 / {len(edges)} 条连线——你可在回复中引用或推进这些节点："]
    for n in nodes:
        lines.append("  - " + _node_summary(n))

    # ---- 连线描述 ----
    edge_lines = [f"  - 连线 {e.get('source')} → {e.get('target')}" for e in edges]
    if edge_lines:
        lines.append("  [连线]")
        lines.extend(edge_lines)

    text = "\n".join(lines)

    # ---- 预算保护：超预算则逐步截断节点，保留画布结构概览 ----
    if _est_tokens(text) > budget_tokens:
        # 先保留头部（结构与连线），再尽量保留前若干节点
        header = lines[0]
        kept = [header]
        used = _est_tokens(header)
        # 连线保留在末尾，先塞节点
        node_block = lines[1:1 + len(nodes)]
        tail = lines[1 + len(nodes):]
        for ln in node_block:
            t = _est_tokens(ln)
            if used + t > budget_tokens:
                kept.append(f"  …（画布过大，已省略部分节点，共 {len(nodes)} 个）")
                break
            kept.append(ln)
            used += t
        for ln in tail:
            t = _est_tokens(ln)
            if used + t > budget_tokens:
                break
            kept.append(ln)
            used += t
        text = "\n".join(kept)

    return text
