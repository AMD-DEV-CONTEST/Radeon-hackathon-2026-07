"""适配器基类

所有外部能力适配器实现此接口。
引擎只依赖 Adapter/AdapterResult，不依赖具体适配器实现。
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class AdapterResult:
    """适配器返回的统一结果"""
    ok: bool
    output: str = ""
    error: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "output": self.output,
            "error": self.error,
            "meta": self.meta,
        }


class Adapter(ABC):
    """所有外部能力适配器的抽象基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """适配器短标识（如 'openclaw', 'hermes', 'memory'）"""

    @abstractmethod
    def is_available(self) -> bool:
        """返回 True 如果真实外部服务可用"""

    @abstractmethod
    def health_check(self) -> AdapterResult:
        """健康检查"""

    def execute(self, action: Dict[str, Any]) -> AdapterResult:
        """执行一个动作（默认实现：子类覆盖）"""
        raise NotImplementedError(f"{self.name} 不支持 execute")
