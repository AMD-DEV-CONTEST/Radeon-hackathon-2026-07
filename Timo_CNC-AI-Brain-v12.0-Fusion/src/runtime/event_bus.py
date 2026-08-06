"""
进程内事件总线 — 轻量级发布/订阅。
支持多频道，零外部依赖。
所有消息为标准 JSON dict。
"""
import json
from datetime import datetime
from typing import Dict, Callable, List, Any


class EventBus:
    """轻量级进程内事件总线。"""

    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}
        self._history: List[Dict[str, Any]] = []

    def subscribe(self, channel: str, callback: Callable[[Dict[str, Any]], None]):
        """订阅频道。"""
        if channel not in self._subscribers:
            self._subscribers[channel] = []
        self._subscribers[channel].append(callback)

    def unsubscribe(self, channel: str, callback: Callable):
        """取消订阅。"""
        if channel in self._subscribers:
            self._subscribers[channel] = [cb for cb in self._subscribers[channel] if cb != callback]

    def publish(self, channel: str, data: Dict[str, Any]):
        """发布消息到频道。data 必须是 JSON 可序列化 dict。"""
        event = {
            "channel": channel,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }
        self._history.append(event)
        # 保留最近 1000 条
        if len(self._history) > 1000:
            self._history = self._history[-500:]

        if channel in self._subscribers:
            for cb in self._subscribers[channel]:
                try:
                    cb(data)
                except Exception:
                    pass  # 回调异常不中断

    def history(self, channel: str = None, limit: int = 50) -> List[Dict[str, Any]]:
        """查询历史事件。"""
        if channel:
            filtered = [e for e in self._history if e["channel"] == channel]
            return filtered[-limit:]
        return self._history[-limit:]

    def to_json(self, channel: str = None) -> str:
        """标准 JSON 历史输出。"""
        return json.dumps(self.history(channel), ensure_ascii=False, indent=2)
