"""XAI 后端路由处理器（S5-1 自动迁移，按领域拆分）。
方法体原属 server_xai.XAIHandler，统一签名 fn(h)，h 即 XAIHandler 实例。
共享单例经 server_xai import *（惰性，bootstrap 在文件末尾，循环导入安全）+ server_runtime。
"""
from __future__ import annotations
from server_xai import *   # 共享单例 / 辅助（惰性导入，安全）
from server_xai import _EVENT_LOCK, _EVENT_SUBS  # import * 会跳过下划线名，需显式导入
from server_runtime import get_engine, get_knowledge_adapter, _CAPABILITIES

def _handle_events_stream(h):
    import queue as _queue
    q: "queue.Queue" = _queue.Queue()
    with _EVENT_LOCK:
        _EVENT_SUBS.append(q)
    h.send_response(200)
    h.send_header("Content-Type", "text/event-stream; charset=utf-8")
    h.send_header("Cache-Control", "no-cache")
    h.send_header("Connection", "keep-alive")
    h.send_header("Access-Control-Allow-Origin", "*")
    h.end_headers()
    try:
        h.wfile.write(
            f"data: {json.dumps({'type': 'hello', 'ts': int(time.time())}, ensure_ascii=False)}\n\n".encode("utf-8")
        )
        h.wfile.flush()
        while True:
            try:
                ev = q.get(timeout=1)
                h.wfile.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode("utf-8"))
                h.wfile.flush()
            except _queue.Empty:
                h.wfile.write(b": ping\n\n")
                h.wfile.flush()
    except Exception:
        pass
    finally:
        with _EVENT_LOCK:
            if q in _EVENT_SUBS:
                _EVENT_SUBS.remove(q)

def register(router) -> None:
    router.add("GET", "/api/events/stream", _handle_events_stream)
