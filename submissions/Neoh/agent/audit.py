"""审计日志模块。

记录所有工具调用、审批决策、任务执行事件，写入 JSON Lines 格式的审计日志文件。
用于满足"权限与隐私保护"中的审计日志要求。

日志格式（每行一个 JSON）:
{
    "timestamp": "2026-07-18T12:34:56.789",
    "event": "tool_call|approval|task|chat",
    "tool": "execute_command",
    "arguments": {...},
    "approved": true,
    "success": true,
    "output_summary": "...",
    "step": 1,
    "task": "..."
}
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class AuditLogger:
    """审计日志记录器，单例模式。"""

    _instance: Optional["AuditLogger"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, log_path: str = "./logs/audit.log", enabled: bool = True):
        if self._initialized:
            return
        self.log_path = log_path
        self.enabled = enabled
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        self._initialized = True
        logger.info(f"AuditLogger initialized: {log_path} (enabled={enabled})")

    def _write(self, record: Dict[str, Any]):
        if not self.enabled:
            return
        record["timestamp"] = datetime.now().isoformat(timespec="milliseconds")
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")

    def log_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        success: bool,
        output: Any = None,
        step: Optional[int] = None,
    ):
        """记录工具调用。"""
        output_summary = str(output)
        if len(output_summary) > 500:
            output_summary = output_summary[:500] + "...[truncated]"
        self._write({
            "event": "tool_call",
            "tool": tool_name,
            "arguments": arguments,
            "success": success,
            "output_summary": output_summary,
            "step": step,
        })

    def log_approval(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        approved: bool,
        step: Optional[int] = None,
    ):
        """记录审批决策。"""
        self._write({
            "event": "approval",
            "tool": tool_name,
            "arguments": arguments,
            "approved": approved,
            "step": step,
        })

    def log_task(self, task: str, success: bool, step_count: int, reflection: Optional[Dict] = None):
        """记录任务执行。"""
        self._write({
            "event": "task",
            "task": task,
            "success": success,
            "step_count": step_count,
            "reflection": reflection,
        })

    def log_chat(self, message: str, response: str, used_rag: bool):
        """记录对话（仅记录摘要，不记录完整内容以保护隐私）。"""
        self._write({
            "event": "chat",
            "message_length": len(message),
            "response_length": len(response),
            "used_rag": used_rag,
        })


# 全局单例
audit_logger = AuditLogger()
