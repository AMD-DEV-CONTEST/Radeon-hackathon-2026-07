"""V4 内核子模块（Task #193 引擎解耦）。

Phase A→F 已逐步承载从 engine_xai.py 上帝类外移的职责模块：
- base：斜杠命令元数据 / 意图类型 / 兜底结果
- commands：全部 _cmd_* 斜杠命令处理器
- intents：意图分类 + _execute_* 执行器
- workflow：画布工作流执行（含收编的 orchestrator 双 DAG 能力）
- memory_bridge / guardian_bridge / evolution_bridge：记忆 / 守卫 / 进化桥接
- engine：瘦编排器（原 engine_xai.py，Phase F 迁入）
"""

from .base import (
    SlashCommand,
    Intent,
    _AdapterResultShim,
    SLASH_COMMANDS,
    INTENT_TYPES,
)
from .engine import XAIEngine

__all__ = [
    "SlashCommand",
    "Intent",
    "_AdapterResultShim",
    "SLASH_COMMANDS",
    "INTENT_TYPES",
    "XAIEngine",
]
