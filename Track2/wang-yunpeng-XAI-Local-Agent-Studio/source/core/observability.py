"""真观测 Tracing Pipeline（P1-O2）

Tracer 记录每次工具调用/模型推理的真实耗时与结果，替代模型自报置信度。
提供 span 上下文管理器、统计聚合、查询接口。

用法：
    from core.observability import global_tracer

    with global_tracer.span(tool_name="read_file") as s:
        result = do_something()
        s.ok(output_size=len(str(result)))

    stats = global_tracer.stats()
    spans = global_tracer.get_spans(limit=50)
"""

from __future__ import annotations
import time as _time
import uuid as _uuid
from collections import deque as _deque
from dataclasses import dataclass as _dc, field as _field
from typing import Any, Dict, List


@_dc
class TraceSpan:
    trace_id: str
    tool_name: str
    start_ts: float
    end_ts: float = 0.0
    success: bool = True
    output_size: int = 0
    error_msg: str = ""

    @property
    def duration_ms(self) -> float:
        return round((self.end_ts - self.start_ts) * 1000, 1) if self.end_ts else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "tool_name": self.tool_name,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "success": self.success,
            "output_size": self.output_size,
            "error_msg": self.error_msg,
            "duration_ms": self.duration_ms,
        }


class _SpanContext:
    """span() 上下文管理器：__enter__ 记录 start_ts，__exit__ 计算 end_ts + 耗时"""

    def __init__(self, tracer: "Tracer", tool_name: str):
        self._tracer = tracer
        self._span = TraceSpan(
            trace_id=str(_uuid.uuid4()),
            tool_name=tool_name,
            start_ts=_time.time(),
        )

    def __enter__(self) -> "_SpanContext":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        try:
            self._span.end_ts = _time.time()
            if exc_type is not None:
                self._span.success = False
                self._span.error_msg = str(exc_val)[:500] if exc_val else f"{exc_type.__name__}"
            self._tracer._spans.append(self._span)
        except Exception:
            pass  # 失败不影响主流程
        return False  # 不吞异常

    def ok(self, output_size: int = 0):
        """标记成功并记录输出大小。"""
        self._span.success = True
        self._span.output_size = output_size

    def fail(self, error_msg: str = ""):
        """标记失败并记录错误信息。"""
        self._span.success = False
        self._span.error_msg = error_msg[:500]


class Tracer:
    """真观测追踪器：deque 环形缓冲区存储 span，支持统计与查询。"""

    def __init__(self, maxlen: int = 1000):
        self._spans: _deque[TraceSpan] = _deque(maxlen=maxlen)

    def span(self, tool_name: str) -> _SpanContext:
        """返回上下文管理器，自动记录耗时。"""
        return _SpanContext(self, tool_name)

    def stats(self) -> Dict[str, Any]:
        """返回聚合统计：success_rate, avg_latency_ms, p95_latency_ms。"""
        if not self._spans:
            return {
                "total": 0,
                "success_rate": 0.0,
                "avg_latency_ms": 0.0,
                "p95_latency_ms": 0.0,
            }
        total = len(self._spans)
        ok_count = sum(1 for s in self._spans if s.success)
        latencies = sorted(s.duration_ms for s in self._spans if s.duration_ms > 0)
        avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
        p95_idx = int(len(latencies) * 0.95)
        p95_lat = latencies[p95_idx] if latencies and p95_idx < len(latencies) else latencies[-1] if latencies else 0.0
        return {
            "total": total,
            "success_rate": round(ok_count / total, 4) if total else 0.0,
            "avg_latency_ms": round(avg_lat, 1),
            "p95_latency_ms": round(p95_lat, 1),
        }

    def get_spans(self, limit: int = 50) -> List[Dict[str, Any]]:
        """返回最近 N 条 span（按 end_ts 倒序）。"""
        spans = sorted(self._spans, key=lambda s: s.end_ts or 0, reverse=True)
        return [s.to_dict() for s in spans[:limit]]


# 全局单例
global_tracer = Tracer()
