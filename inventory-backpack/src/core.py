"""
核心抽象层 - 类型定义与接口契约
"""

from dataclasses import dataclass, field
from typing import (
    Any, AsyncIterator, Callable, Coroutine, 
    Optional, Protocol, runtime_checkable,
)
from enum import Enum, auto


class TaskPriority(Enum):
    """任务优先级 - 用于调度"""
    CRITICAL = auto()
    HIGH = auto()
    NORMAL = auto()
    LOW = auto()


@runtime_checkable
class Inferencer(Protocol):
    """推理引擎协议 - 统一接口"""
    
    async def infer(
        self,
        messages: list[dict],
        *,
        stream: bool = False,
        **kwargs
    ) -> dict | AsyncIterator[str]:
        """统一推理入口"""
        ...


@runtime_checkable
class ToolExecutor(Protocol):
    """工具执行器协议"""
    
    async def execute(self, name: str, params: dict) -> dict:
        """执行工具，返回完整结果"""
        ...


@dataclass(frozen=True, slots=True)
class InferenceResult:
    """推理结果 - 不可变，完整保留"""
    content: str
    tokens_used: int = 0
    latency_ms: float = 0.0
    model: str = ""
    raw: dict = field(default_factory=dict, repr=False)