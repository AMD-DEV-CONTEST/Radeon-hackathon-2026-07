# -*- coding: utf-8 -*-
"""
agent/memory.py — 会话记忆

langgraph 的 checkpointer 已负责保存对话消息历史（按 thread_id 隔离）；
本模块额外保存每个会话的结构化理赔结果，支持两种记忆模式：

- 单张模式（last_claim）：保存「上一张发票的结构化理赔结果」，便于后续追问
  （如「为什么 X 药品被拒？」）直接引用精确金额与明细，无需重复调用工具。
- 批量模式（batch_claim）：保存「批量发票处理的结构化理赔结果」，便于对一批
  发票的汇总结果进行追问与复用。

设计对齐《设计文档.md》4.4 / 8.1：一次处理、多轮复用；按 session_id 隔离。
"""

import threading


class SessionStore:
    """进程内会话存储：session_id -> {"last_claim": {...}, "batch_claim": {...}}。

    其中 ``last_claim`` 保存单张发票的结构化理赔结果，``batch_claim`` 保存批量
    发票处理的结构化理赔结果；两者互不影响，分别服务于单张流程与批量流程。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._sessions = {}

    def set_last_claim(self, session_id: str, result: dict):
        with self._lock:
            self._sessions.setdefault(session_id, {})["last_claim"] = result

    def get_last_claim(self, session_id: str):
        return self._sessions.get(session_id, {}).get("last_claim")

    def set_batch_claim(self, session_id: str, batch_result: dict):
        """保存某个会话的批量发票结构化理赔结果。

        Args:
            session_id: 会话标识。
            batch_result: 批量发票处理的结构化理赔结果。
        """
        with self._lock:
            self._sessions.setdefault(session_id, {})["batch_claim"] = batch_result

    def get_batch_claim(self, session_id: str):
        """获取某个会话的批量发票结构化理赔结果，无则返回 None。"""
        return self._sessions.get(session_id, {}).get("batch_claim")

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
        with self._lock:
            if session_id is None:
                self._sessions.clear()
            else:
                self._sessions.pop(session_id, None)


_store = SessionStore()


def get_store() -> SessionStore:
    """全局会话存储单例。"""
    return _store