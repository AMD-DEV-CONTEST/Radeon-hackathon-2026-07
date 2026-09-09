"""
Layer 3: 领域工头层（Foreman）

三个专职工头：
- LLMForeman: 管理 3 个 LLM 实例（推理/创意/快速）
- ImageForeman: 管理 1 个生图引擎
- SpeechForeman: 管理 2 个引擎（主 TTS/STT + 备用）

共有特性：策略缓存、工作区隔离、重试降级、经验写入
"""

from .base_foreman import BaseForeman, Workspace
from .llm_foreman import LLMForeman
from .image_foreman import ImageForeman
from .speech_foreman import SpeechForeman
