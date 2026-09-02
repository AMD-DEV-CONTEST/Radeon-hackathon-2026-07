"""LLM 输出 JSON 抽取（零依赖，单一事实源）。

背景（2026-08-04）：
    多处 NL→DAG / NL→工作流生成都用 `re.search(r'\\{[\\s\\S]*\\}', raw)` 抓 JSON。
    这个贪婪正则有两个致命缺陷：
      1. 模型先输出一段推演文字（"We need answer in Chinese? ... config（空对象即可）"），
         里面随便一个 `{}` 就会被抓中，json.loads 必炸 → 接口 500。
      2. 模型用 ```json 围栏 / 输出多段 JSON 时，贪婪匹配会跨段吞进非 JSON 文本。
    结果是"模型稍微不听话 → 功能直接不可用"，属于典型脆性实现。

本模块提供括号配对扫描（字符串/转义感知）的稳健抽取：
    - 先剥 ```json 围栏
    - 整体直解
    - 扫描所有 **平衡** 的 {...} / [...] 片段，逐个尝试，取第一个解析成功且结构合规的

对外只暴露 extract_json / extract_dag，避免各处各写一份。
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*([\s\S]*?)```")


def _strip_fences(raw: str) -> str:
    """有 ``` 围栏时取围栏内内容（取最长的一段，通常就是正文 JSON）。"""
    blocks = _FENCE_RE.findall(raw or "")
    if blocks:
        return max(blocks, key=len).strip()
    return (raw or "").strip()


def _balanced_spans(s: str) -> list[tuple[int, int]]:
    """扫描出所有顶层平衡的 {...} / [...] 区间（字符串与转义感知）。

    返回 [(start, end_exclusive), ...]，按出现顺序。
    """
    spans: list[tuple[int, int]] = []
    stack: list[str] = []
    start = -1
    in_str = False
    quote = ""
    esc = False
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                in_str = False
            continue
        if ch in ('"', "'"):
            in_str = True
            quote = ch
            continue
        if ch in "{[":
            if not stack:
                start = i
            stack.append(ch)
        elif ch in "}]":
            if not stack:
                continue
            opener = stack.pop()
            if (opener == "{" and ch != "}") or (opener == "[" and ch != "]"):
                stack.clear()
                start = -1
                continue
            if not stack and start >= 0:
                spans.append((start, i + 1))
                start = -1
    return spans


def extract_json(raw: str) -> Optional[Any]:
    """从模型自由文本里抽出第一个可解析的 JSON 值；失败返回 None。"""
    if not raw:
        return None
    text = _strip_fences(raw)

    # 1) 整体直解（模型听话时的快路径）
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # 2) 平衡区间逐个尝试：优先长的（更可能是完整结构，而非推演里的零星 {}）
    spans = _balanced_spans(text)
    for start, end in sorted(spans, key=lambda sp: sp[1] - sp[0], reverse=True):
        frag = text[start:end]
        try:
            return json.loads(frag)
        except (json.JSONDecodeError, ValueError):
            # 常见小瑕疵：尾随逗号 / 单引号，做一次保守修补再试
            patched = re.sub(r",\s*([}\]])", r"\1", frag)
            try:
                return json.loads(patched)
            except (json.JSONDecodeError, ValueError):
                continue
    return None


def extract_dag(raw: str) -> Optional[dict]:
    """抽取 {"nodes": [...], "edges": [...]} 形态的 DAG。

    只接受"看起来真的是 DAG"的结果 —— 必须含非空 nodes 列表；
    否则返回 None，让调用方走重试/诚实报错，而不是把垃圾结构塞给前端。
    """
    obj = extract_json(raw)
    if isinstance(obj, list):
        obj = {"nodes": obj, "edges": []}
    if not isinstance(obj, dict):
        return None
    # 容忍模型把 DAG 包一层（{"dag": {...}} / {"workflow": {...}}）
    for wrapper in ("dag", "workflow", "graph", "result", "data"):
        inner = obj.get(wrapper)
        if isinstance(inner, dict) and "nodes" in inner:
            obj = inner
            break
    nodes = obj.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return None
    edges = obj.get("edges")
    if not isinstance(edges, list):
        obj["edges"] = []
    return obj
