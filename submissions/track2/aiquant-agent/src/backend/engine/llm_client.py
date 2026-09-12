"""
llm_client.py — RD-Agent 统一模型调用封装层

设计原则：
- 与机器人服务共用完全一致的 BaseLLMAdapter 抽象基类
- 当前默认实例化 DeepSeek 适配器，所有智能体推理走 DeepSeek
- 底层预留 OpenAI、通义千问适配入口，后期仅新增适配器即可切换
- RD-Agent 因子挖掘、代码生成、反馈校验逻辑完全禁止修改

使用方式：
    from backend.engine.llm_client import get_llm_client
    client = get_llm_client()
    result = client.chat_completion(messages=[...])
"""
import sys
import os
from pathlib import Path
from typing import Optional
from loguru import logger

# 导入统一适配器层（与机器人服务共享同一套抽象）
# 添加 quant_system/robot_service 到 path
_robot_svc = Path(os.path.expanduser("~/quant_system/robot_service"))
if str(_robot_svc) not in sys.path:
    sys.path.insert(0, str(_robot_svc))

from model_adapter import (
    BaseLLMAdapter,
    DeepSeekAdapter,
    OpenAIAdapter,
    QwenAdapter,
    ADAPTER_REGISTRY,
    get_llm_adapter,
    ACTIVE_PROVIDER,
)

# ═══════════════════════════════════════════════════════════════
# RD-Agent 专用 LLM 客户端
# ═══════════════════════════════════════════════════════════════

class RDAgentLLMClient:
    """
    RD-Agent 专用 LLM 客户端封装。
    
    在统一适配器基础上，增加 RD-Agent 特有的配置读取和错误处理。
    底层适配器逻辑与机器人服务完全一致。
    """

    def __init__(self, provider: str = None):
        # 优先从项目 .env 读取配置
        from backend.shared.config import settings

        config = {
            "api_key": settings.llm_api_key,
            "api_base": settings.llm_api_base,
            "model": settings.llm_model,
        }

        provider = provider or ACTIVE_PROVIDER
        try:
            self._adapter = get_llm_adapter(provider, config)
            logger.info(f"RD-Agent LLM 客户端初始化: {self._adapter.provider_name()} / {self._adapter.model}")
        except Exception as e:
            logger.error(f"LLM 客户端初始化失败: {e}")
            self._adapter = None

    @property
    def is_ready(self) -> bool:
        return self._adapter is not None

    @property
    def provider_name(self) -> str:
        return self._adapter.provider_name() if self._adapter else "none"

    @property
    def model_name(self) -> str:
        return self._adapter.model if self._adapter else "none"

    def chat(self, messages: list[dict], **kwargs) -> dict:
        """
        RD-Agent 标准对话接口。
        
        参数与 BaseLLMAdapter.chat_completion 一致。
        """
        if self._adapter is None:
            raise RuntimeError("LLM 客户端未初始化，请检查 API Key 配置")

        temperature = kwargs.pop("temperature", 0.7)
        max_tokens = kwargs.pop("max_tokens", 2048)

        return self._adapter.chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def check_connectivity(self) -> dict:
        """检测 LLM 连通性"""
        if self._adapter is None:
            return {"ok": False, "message": "LLM 客户端未初始化", "latency_ms": 0}
        return self._adapter.check_connectivity()


# 全局单例
_llm_client: Optional[RDAgentLLMClient] = None


def get_llm_client() -> RDAgentLLMClient:
    """获取 RD-Agent LLM 客户端全局单例"""
    global _llm_client
    if _llm_client is None:
        _llm_client = RDAgentLLMClient()
    return _llm_client


def reload_llm_client():
    """重新加载 LLM 客户端（配置变更后调用）"""
    global _llm_client
    _llm_client = RDAgentLLMClient()
    return _llm_client
