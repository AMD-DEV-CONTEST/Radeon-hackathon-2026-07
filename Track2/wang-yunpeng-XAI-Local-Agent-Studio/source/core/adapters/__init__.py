"""XAI 外部适配器层

所有外部能力（OpenClaw/Hermes/MemOS）通过统一 Adapter 接口接入 XAI 引擎。
引擎只依赖接口，不依赖具体实现——实现可在「本地 Stub」与「真实外部进程」之间切换。
"""

from .base import Adapter, AdapterResult
from .openclaw_adapter import OpenClawAdapter
from .hermes_adapter import HermesAdapter

__all__ = [
    "Adapter",
    "AdapterResult",
    "OpenClawAdapter",
    "HermesAdapter",
]
