"""知识管道适配器（下手能力的防腐层）。

引擎 / 大脑只依赖 `Adapter` 抽象（core/adapters/base.py），不 import kb 实现细节。
所有知识操作经 `execute({"op": ...})` 分派，结果统一为 `AdapterResult`。

这是 ARCHITECTURE_GUARDRAILS.md R3 的落地：三双手之一（知识管道）经 Adapter 接入，
上游升级只动本文件，不动引擎。
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from .base import Adapter, AdapterResult
from ..kb import KnowledgeBase


class KnowledgeAdapter(Adapter):
    """知识管道适配器：文档摄入 / 混合检索 / 统计 / 清空。"""

    def __init__(self, db_path: Optional[str] = None):
        self._kb = KnowledgeBase(db_path) if db_path else KnowledgeBase()
        self._name = "knowledge"

    @property
    def name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        try:
            return os.path.exists(self._kb.db_path) or True  # 无 DB 也能建
        except Exception:
            return False

    def health_check(self) -> AdapterResult:
        try:
            st = self._kb.stats()
            return AdapterResult(ok=True, output="知识管道就绪",
                                 meta={"stats": st})
        except Exception as e:
            return AdapterResult(ok=False, error=str(e))

    def execute(self, action: dict) -> AdapterResult:
        op = (action or {}).get("op", "")
        try:
            if op == "ingest":
                paths = action.get("paths") or []
                n = self._kb.ingest(paths)
                return AdapterResult(ok=True, output=f"已摄入 {n} 块",
                                     meta={"ingested": n})
            if op == "search":
                q = action.get("query", "")
                top_k = int(action.get("top_k", 5))
                hits = self._kb.search(q, top_k)
                return AdapterResult(ok=True, output=f"命中 {len(hits)} 条",
                                     meta={"hits": hits})
            if op == "stats":
                return AdapterResult(ok=True, output="统计",
                                     meta={"stats": self._kb.stats()})
            if op == "clear":
                n = self._kb.clear()
                return AdapterResult(ok=True, output=f"已清空 {n} 块",
                                     meta={"cleared": n})
            return AdapterResult(ok=False, error=f"未知 op: {op}")
        except Exception as e:
            return AdapterResult(ok=False, error=str(e))

    def close(self):
        self._kb.close()
