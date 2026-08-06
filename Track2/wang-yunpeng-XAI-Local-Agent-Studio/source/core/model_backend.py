"""XAI 模型后端抽象层。

设计要点（模型无关）：所有上层逻辑只依赖 `ModelBackend` 接口，不绑定任何具体
大模型。真实接入时替换为 DeepSeek / 本地 Ollama / Grok 的实现即可；测试时用
`StubBackend` 注入确定性输出，无需联网即可验证整张蓝图的逻辑。

这是"底座模型可替换"的工程落点 —— 与元认知层模型无关的设计一致。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator, Optional

logger = logging.getLogger("xai.model_backend")


@dataclass
class ModelResponse:
    text: str
    confidence: float = 0.5  # 模型自评置信度 [0,1]


class ModelBackend(ABC):
    """所有大模型必须实现的接口。"""

    name: str = "base"

    @abstractmethod
    def complete(self, prompt: str, **kwargs) -> str:
        """给定 prompt，返回文本。"""
        raise NotImplementedError

    @abstractmethod
    def complete_with_confidence(self, prompt: str, **kwargs) -> ModelResponse:
        """给定 prompt，返回文本 + 自评置信度。"""
        raise NotImplementedError

    def stream_complete(self, prompt: str, **kwargs) -> Iterator[str]:
        """流式生成：逐块 yield 文本片段（token）。

        默认实现：把 complete 的结果作为一个块吐出，保证未实现流式的具体
        后端也能被上层以统一方式调用（优雅降级）。
        """
        yield self.complete(prompt, **kwargs)


class StubBackend(ModelBackend):
    """测试用确定性后端。

    行为可预测：
    - complete：返回 prompt 的回声 + 固定后缀，便于断言。
    - complete_with_confidence：置信度由 kwargs.conf 控制（默认 0.7）。
    - 若 prompt 含 'REFUSE'，模拟模型拒绝（用于 guardian 测试）。
    """

    name = "stub"

    def __init__(self, default_conf: float = 0.7):
        self.default_conf = default_conf

    def complete(self, prompt: str, **kwargs) -> str:
        # 显式告警：Stub 是测试替身，并非真实模型输出。静默返回会掩盖
        # 『未注入真实 API Key → 整页假数据』这类部署故障（见 AUDIT_REPORT）。
        logger.warning(
            "[StubBackend] 返回 STUB 假回答（非真实模型输出）。若在生产环境看到此日志，"
            "说明模型后端未正确装配/未注入 API Key。prompt=%r",
            prompt[:60],
        )
        if "REFUSE" in prompt:
            return "[REFUSED]"
        return f"[stub-answer]{prompt[-40:]}"

    def complete_with_confidence(self, prompt: str, **kwargs) -> ModelResponse:
        conf = float(kwargs.get("conf", self.default_conf))
        text = self.complete(prompt, **kwargs)
        return ModelResponse(text=text, confidence=conf)

    def stream_complete(self, prompt: str, **kwargs) -> Iterator[str]:
        """Stub 流式：按字符分块吐出，模拟真实流式体验（便于前端联调）。"""
        text = self.complete(prompt, **kwargs)
        # 每 12 个字符一块，模拟 token 流
        for i in range(0, len(text), 12):
            yield text[i : i + 12]
