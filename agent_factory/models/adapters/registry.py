from __future__ import annotations

from agent_factory.models.adapters.anthropic import AnthropicChatAdapter
from agent_factory.models.adapters.base import ChatModelAdapter
from agent_factory.models.adapters.deepseek import DeepSeekChatAdapter
from agent_factory.models.adapters.hunyuan import HunyuanChatAdapter
from agent_factory.models.adapters.kimi import KimiChatAdapter
from agent_factory.models.adapters.mimo import MiMoChatAdapter
from agent_factory.models.adapters.minimax import MiniMaxChatAdapter
from agent_factory.models.adapters.openai_chat import (
    GenericOpenAICompatibleChatAdapter,
    OpenAIChatAdapter,
)
from agent_factory.models.adapters.qwen import QwenChatAdapter
from agent_factory.models.adapters.zhipu import ZhipuChatAdapter
from agent_factory.models.capabilities import ProviderProfile


def adapter_for_profile(profile: ProviderProfile) -> ChatModelAdapter:
    adapter_type = _ADAPTERS.get(profile.adapter_id)
    if adapter_type is None:
        raise ValueError(f"unsupported chat model adapter: {profile.adapter_id}")
    return adapter_type(profile)


_ADAPTERS = {
    "openai_chat": OpenAIChatAdapter,
    "openai_compatible_chat": GenericOpenAICompatibleChatAdapter,
    "anthropic": AnthropicChatAdapter,
    "deepseek": DeepSeekChatAdapter,
    "qwen": QwenChatAdapter,
    "zhipu": ZhipuChatAdapter,
    "kimi": KimiChatAdapter,
    "minimax": MiniMaxChatAdapter,
    "mimo": MiMoChatAdapter,
    "hunyuan": HunyuanChatAdapter,
}
