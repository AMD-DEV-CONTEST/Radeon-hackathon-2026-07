"""事件总线 — 线程安全的内存消息队列，桥接 agent 同步代码和 WebSocket 异步推送"""
import queue
import json


class EventBus:
    """简单的事件总线: publish (同步) -> Queue -> WebSocket (异步读取)"""

    def __init__(self):
        self._queues = set()

    def subscribe(self) -> queue.Queue:
        q = queue.Queue()
        self._queues.add(q)
        return q

    def unsubscribe(self, q):
        self._queues.discard(q)

    def publish(self, event: dict):
        """同步发布 — 从 agent 任何线程调用"""
        msg = json.dumps(event, ensure_ascii=False)
        for q in list(self._queues):
            q.put(msg)


# 全局单例
bus = EventBus()
