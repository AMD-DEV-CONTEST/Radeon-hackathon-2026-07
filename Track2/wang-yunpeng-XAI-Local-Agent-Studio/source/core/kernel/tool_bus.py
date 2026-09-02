"""工具调度总线 (ToolBus) —— 防腐层注册表。

设计依据（市面主流调研 2025-07）：
- LangChain: "tools-first"，工具即函数/类，注册进 agent（单进程内嵌）。
- MCP: 工具即独立 server（跨 agent/框架分发）；主流建议"先把工具写成独立函数，
  再用注册表包一层"。
- XAI 定位 = 单机单进程私有操作台 + 零外部依赖铁律 → 采用【内嵌防腐层注册表】：
  每个工具本就是独立 adapter 模块（openclaw/hermes/knowledge/grok_build），
  ToolBus 在进程内统一注册 + 统一分发 + 统一返回结构，不另起进程、不引外部依赖。
  未来若需跨框架分发，可把同一批 handler 原样暴露为 MCP server，零改造。

统一返回结构遵循 XAI 工程铁律 {status, data, error, meta}。
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

_logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# 统一返回结构
# ---------------------------------------------------------------------------
@dataclass
class ToolResult:
    """所有工具统一返回结构（与 XAI 结构化输出铁律一致）。"""
    status: str = "ok"          # ok | empty | error
    data: Any = None
    error: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 联网搜索（修复版，纯标准库，多后端降级）
#   主链路: html.duckduckgo.com POST（ddgs 库同款可用端点，已实测本机通）
#   兜底:   DuckDuckGo Instant Answer API（仅摘要）
#   全失败: 诚实返回 []，绝不假装联网
# ---------------------------------------------------------------------------
def _strip_tags(s: str) -> str:
    return re.sub(r"<.*?>", "", s or "").strip()


def _decode_ddg_url(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    if "uddg=" in href:
        enc = href.split("uddg=")[1].split("&")[0]
        try:
            return urllib.parse.unquote(enc)
        except Exception:
            return href
    return href


def _parse_ddg_html(html: str, max_results: int) -> List[Dict[str, str]]:
    link_re = re.compile(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
    snip_re = re.compile(r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', re.S)
    links = link_re.findall(html)
    snips = snip_re.findall(html)
    results: List[Dict[str, str]] = []
    for i, (href, title_html) in enumerate(links[:max_results]):
        url = _decode_ddg_url(href)
        if not url:
            continue
        title = _strip_tags(title_html)
        snippet = _strip_tags(snips[i]) if i < len(snips) else ""
        results.append({"title": title, "url": url, "snippet": snippet})
    return results


def _ddg_html_search(query: str, max_results: int, timeout: int) -> List[Dict[str, str]]:
    url = "https://html.duckduckgo.com/html"
    data = urllib.parse.urlencode({"q": query}).encode()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": _UA}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        html = resp.read().decode("utf-8", "ignore")
    return _parse_ddg_html(html, max_results)


def _ddg_instant_answer(query: str, timeout: int) -> str:
    url = (
        "https://api.duckduckgo.com/?q="
        + urllib.parse.quote(query)
        + "&format=json&no_html=1&skip_disambig=1"
    )
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": _UA}), timeout=timeout
        ) as r:
            d = json.loads(r.read().decode("utf-8", "ignore"))
        return (d.get("Abstract") or "").strip()
    except Exception as e:
        _logger.warning("DDG Instant Answer 失败: %s", e)
        return ""


def web_search(query: str, max_results: int = 5, timeout: int = 12) -> List[Dict[str, str]]:
    """真实联网搜索。返回 [{title, url, snippet}, ...]；无结果返回 []。

    已修复：旧实现用 lite.duckduckgo.com GET（已被反爬 anomaly 拦截，恒空）。
    现改用 html.duckduckgo.com POST + Instant Answer 兜底。
    """
    query = (query or "").strip()
    if not query:
        return []
    try:
        results = _ddg_html_search(query, max_results, timeout)
        if results:
            return results
    except Exception as e:
        _logger.warning("DDG HTML 搜索失败: %s", e)
    # 兜底：Instant Answer 摘要
    ans = _ddg_instant_answer(query, timeout)
    if ans:
        return [{"title": "DuckDuckGo Instant Answer", "url": "", "snippet": ans}]
    return []


# ---------------------------------------------------------------------------
# 工具总线
# ---------------------------------------------------------------------------
class ToolBus:
    """进程内工具注册表 + 统一分发。handler 返回原始数据，异常由 dispatch 包裹。"""

    def __init__(self) -> None:
        self._tools: Dict[str, Dict[str, Any]] = {}

    def register(
        self, name: str, handler: Callable[..., Any], desc: str = "", kind: str = "tool"
    ) -> "ToolBus":
        self._tools[name] = {"handler": handler, "desc": desc, "kind": kind}
        return self

    def dispatch(self, name: str, **kwargs: Any) -> ToolResult:
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(
                status="error",
                error=f"未知工具: {name}",
                meta={"available": list(self._tools)},
            )
        try:
            data = tool["handler"](**kwargs)
            if data is None or (isinstance(data, (list, dict, str)) and len(data) == 0):
                return ToolResult(status="empty", data=data, meta={"tool": name})
            return ToolResult(status="ok", data=data, meta={"tool": name})
        except Exception as e:  # noqa: BLE001 - 总线兜底，不向上抛
            _logger.warning("工具 %s 执行异常: %s", name, e)
            return ToolResult(status="error", error=str(e)[:200], meta={"tool": name})

    def list_tools(self) -> List[Dict[str, str]]:
        return [
            {"name": n, "desc": t["desc"], "kind": t["kind"]}
            for n, t in self._tools.items()
        ]


# ---------------------------------------------------------------------------
# 默认总线工厂（接线真实后端）
# ---------------------------------------------------------------------------
def _kb_search(kb: Any, query: str, top_k: int) -> List[Any]:
    r = kb.execute({"op": "search", "query": query, "top_k": top_k})
    if getattr(r, "ok", False):
        return getattr(r, "meta", {}).get("hits", [])
    return []


def build_tool_bus(engine: Optional[Any] = None) -> ToolBus:
    """构建预接线的工具总线。

    - search: 联网搜索（纯标准库，已修复）
    - exec:   OpenClaw 执行网关（文件/终端/浏览器）
    - grok:   Grok Build 编程执行
    - kb:     本地知识库检索（server_runtime 单例）
    """
    bus = ToolBus()
    bus.register(
        "search",
        lambda query, max_results=5: web_search(query, max_results),
        desc="实时联网搜索 (DuckDuckGo HTML + Instant Answer 兜底)",
        kind="search",
    )
    if engine is not None:
        oc = getattr(engine, "openclaw", None)
        gb = getattr(engine, "grok_build", None)
        if oc is not None:
            bus.register(
                "exec",
                lambda **kw: oc.execute(kw),
                desc="OpenClaw 执行网关 (文件读写/终端/浏览器)",
                kind="exec",
            )
        if gb is not None:
            bus.register(
                "grok",
                lambda task, model=None, **kw: gb.run(task, model=model, **kw),
                desc="Grok Build 编程任务执行",
                kind="code",
            )
        # 知识库（server_runtime 模块级单例，延迟导入避免循环依赖）
        try:
            from server_runtime import get_knowledge_adapter

            kb = get_knowledge_adapter()
            bus.register(
                "kb",
                lambda query, top_k=5: _kb_search(kb, query, top_k),
                desc="本地知识库检索 (BM25)",
                kind="kb",
            )
        except Exception as e:  # noqa: BLE001
            _logger.warning("KB 工具未注册: %s", e)
    return bus
