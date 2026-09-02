"""[遗留] XAI 全局统一记忆池 `xai-grok-memory`（吸收 Hermes 四层 + OpenClaw 文件约定）。

> ⚠️ 遗留组件（Phase E #11 收敛）：自第二刀记忆单核（#192）起，引擎运行时记忆的
> 单一事实源已统一为 `core/memory_core`（`default_memory_core()`，7 层元认知）。
> 本 `MemorySystem` 内存池不再被引擎主链路写入，仅保留给 test_xai_v2 / test_xai_v3
> 作为独立内存池实现测试，以及历史 import 兼容。新代码请勿再依赖本类。

层级与升迁路径（Hermes 风格）：
  用户输入/执行结果
    → 短期记忆(会话级循环缓冲, 语义 top-k 召回)
    → 中期记忆(任务级归档, LLM 价值评估后沉淀)
    → 长期记忆(MEMORY.md + USER.md, 可 Git 版本化)
    → 技能库(SkillRegistry, 走 Distill 注册)

统一记忆池（痛点1：消除引擎间记忆割裂）：
- 每条记忆带 `engine` 标签（openclaw/grok_build/hermes/orchestrator/reason/meta/global）。
- `engine=None` 的查询 = 跨引擎全局共享；指定 engine = 该引擎私有视图。
- `UnifiedMemoryPool = MemorySystem` 是所有引擎共享读写的单一事实源。

设计纪律：
- 短期：容量受限循环缓冲，不无脑灌 prompt；语义编码后 top-k 召回。
- 长期：落盘为 Markdown 文件（SOUL/IDENTITY/USER/MEMORY），可版本化、可迁移。
- 技能层不直接写，交给 Distill（边界：memory 不越权改技能库）。
"""

from __future__ import annotations

import os
import re
from collections import deque
from dataclasses import dataclass, field


def _embed(text: str) -> set[str]:
    """极简语义单元（词袋），用于 top-k 召回。

    混合分词：拉丁词 + 中文单字 + 二元组（避免 CJK 与拉丁连写被当成一个 token）。
    """
    words = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    cjk_runs = re.findall(r"[\u4e00-\u9fff]+", text)
    toks: list[str] = list(words)
    for run in cjk_runs:
        toks.extend(run)  # 单字
        for i in range(len(run) - 1):
            toks.append(run[i:i + 2])  # 二元组
    return set(toks)


@dataclass
class MemoryItem:
    text: str
    score: float = 0.0
    engine: str = "global"  # 写入方引擎标签：openclaw/grok_build/hermes/orchestrator/reason/meta/global


class MemorySystem:
    def __init__(self, workspace: str = ".xai_memory", short_capacity: int = 1000):
        self.workspace = workspace
        self.short_capacity = short_capacity
        self.short_term: deque = deque(maxlen=short_capacity)
        self.medium_term: list[MemoryItem] = []
        self.long_term: list[MemoryItem] = []
        os.makedirs(workspace, exist_ok=True)

    # ---- 短期 ----
    def add_short(self, text: str, engine: str = "global") -> None:
        self.short_term.append(MemoryItem(text=text, engine=engine))

    def recall_short(self, query: str, k: int = 5, engine: str | None = None) -> list[str]:
        q = _embed(query)
        if not q:
            return []
        scored = []
        for item in self.short_term:
            if engine is not None and item.engine != engine:
                continue
            overlap = len(q & _embed(item.text))
            if overlap:
                scored.append((overlap, item.text))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored[:k]]

    # ---- 中期（任务级沉淀） ----
    def add_medium(self, text: str, value: float = 1.0, engine: str = "global") -> None:
        self.medium_term.append(MemoryItem(text=text, score=value, engine=engine))

    # ---- 长期（落盘 Markdown） ----
    def persist_long(self, text: str, filename: str = "MEMORY.md", engine: str = "global") -> str:
        path = os.path.join(self.workspace, filename)
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n" + text + "\n")
        self.long_term.append(MemoryItem(text=text, engine=engine))
        return path

    def read_long(self, filename: str = "MEMORY.md") -> str:
        path = os.path.join(self.workspace, filename)
        if not os.path.exists(path):
            return ""
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    # ---- 巩固：短期 → 长期（LLM 价值评估由调用方注入） ----
    def consolidate(self, value_fn, on_persist=None) -> list[str]:
        """对短期缓冲做价值评估，值得长期记住的落盘。

        value_fn(text)->float；超过阈值则 persist_long 并回调 on_persist(path)。
        """
        promoted: list[str] = []
        for item in list(self.short_term):
            try:
                v = value_fn(item.text)
            except Exception:
                v = 0.0
            if v >= 0.6:
                path = self.persist_long(item.text)
                promoted.append(path)
                if on_persist:
                    on_persist(path)
        return promoted

    # ---- 统一记忆池（痛点1：消除引擎间记忆割裂） ----
    def recall(self, query: str, k: int = 5, engine: str | None = None) -> list[str]:
        """跨短期+中期统一召回；engine=None 时跨引擎（全局共享）。"""
        out: list[str] = []
        out.extend(self.recall_short(query, k=k, engine=engine))
        q = _embed(query)
        if q:
            scored = []
            for item in self.medium_term:
                if engine is not None and item.engine != engine:
                    continue
                overlap = len(q & _embed(item.text))
                if overlap:
                    scored.append((overlap, item.text))
            scored.sort(key=lambda x: x[0], reverse=True)
            out.extend(t for _, t in scored[:k])
        # 去重保序
        seen, uniq = set(), []
        for t in out:
            if t not in seen:
                seen.add(t)
                uniq.append(t)
        return uniq[:k]

    def query_cross_engine(self, query: str, k: int = 5) -> list[tuple[str, str]]:
        """跨引擎查询：返回 [(engine, text)]，实现全局共享记忆池去割裂。"""
        q = _embed(query)
        if not q:
            return []
        scored: list[tuple[int, str, str]] = []
        for item in list(self.short_term) + self.medium_term:
            overlap = len(q & _embed(item.text))
            if overlap:
                scored.append((overlap, item.engine, item.text))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [(e, t) for _, e, t in scored[:k]]

    def engines(self) -> set[str]:
        """当前记忆池中出现的引擎标签集合。"""
        return {i.engine for i in list(self.short_term) + self.medium_term + self.long_term}


# 全局统一记忆池别名（单一事实源，所有引擎共享读写）
UnifiedMemoryPool = MemorySystem
