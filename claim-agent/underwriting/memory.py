# -*- coding: utf-8 -*-
"""
underwriting/memory.py — 核保会话记忆

参考 agent/memory.py 的进程内 dict + threading.Lock 模式，按 session_id 隔离。

两种记忆模式（对齐 spec.md「核保 Agent 与流式追问」三级回退）：
- 单份模式（last_report）：保存「上一份核保报告」，便于单份报告的多轮追问。
- 批量模式（batch_report）：保存「批量核保的聚合结果」，便于对一批报告的汇总追问。

Task 7 会扩展为完整三级回退（批量报告 → 单份报告 → 通用 Agent），
当前先放骨架，提供 set/get 接口与模块级单例 get_store()。
"""

import threading


class UnderwritingStore:
    """进程内核保会话存储：session_id -> {"last_report": {...}, "batch_report": {...}}。

    其中 ``last_report`` 保存单份核保报告，``batch_report`` 保存批量核保的聚合结果；
    两者互不影响，分别服务于单份流程与批量流程的追问。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._sessions = {}

    def set_last_report(self, session_id: str, report: dict):
        """保存某个会话的单份核保报告。"""
        with self._lock:
            self._sessions.setdefault(session_id, {})["last_report"] = report

    def get_last_report(self, session_id: str):
        """获取某个会话的单份核保报告，无则返回 None。"""
        return self._sessions.get(session_id, {}).get("last_report")

    def set_batch_report(self, session_id: str, batch: dict):
        """保存某个会话的批量核保聚合结果。"""
        with self._lock:
            self._sessions.setdefault(session_id, {})["batch_report"] = batch

    def get_batch_report(self, session_id: str):
        """获取某个会话的批量核保聚合结果，无则返回 None。"""
        return self._sessions.get(session_id, {}).get("batch_report")

    def add_history(self, session_id: str, role: str, content: str):
        """追加一轮对话历史（role=user/assistant），按 session_id 隔离。

        这是「多轮对话记忆」：stream_followup 每次把历史拼进 messages，
        模型才能记得之前问过什么。保留最近 20 条（约 10 轮），避免 token 膨胀。
        """
        if not session_id or not content:
            return
        with self._lock:
            hist = self._sessions.setdefault(session_id, {}).setdefault("history", [])
            hist.append({"role": role, "content": content})
            if len(hist) > 20:
                del hist[: len(hist) - 20]

    def get_history(self, session_id: str):
        """获取某个会话的对话历史列表，无则返回空列表。"""
        return list(self._sessions.get(session_id, {}).get("history", []))

    def clear(self, session_id: str = None):
        """清空指定会话或全部会话。"""
        with self._lock:
            if session_id is None:
                self._sessions.clear()
            else:
                self._sessions.pop(session_id, None)


_store = UnderwritingStore()


def get_store() -> UnderwritingStore:
    """全局核保会话存储单例。"""
    return _store
