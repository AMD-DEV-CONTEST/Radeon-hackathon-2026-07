from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from agent_factory.local_inference.chat_model import LocalLlamaCppChatModel
from agent_factory.local_inference.config import load_local_inference_endpoint
from agent_factory.models.protocol import ModelReasoningSettings, StructuredOutputMethod


@dataclass(frozen=True, slots=True)
class ChatModelSettings:
    role: str
    engine: str
    model: str | None
    profile_id: str | None = None
    source: str = "model_pool"
    temperature: float | None = None
    timeout_seconds: float | None = None
    max_output_tokens: int | None = None
    max_input_tokens: int | None = None
    compression_trigger_tokens: int | None = None
    multimodal: bool = False
    tool_calling: bool = True
    strict_tool_schema: bool = False
    reasoning_supported: bool = False
    reasoning_efforts: tuple[str, ...] = ()
    reasoning: ModelReasoningSettings = field(default_factory=ModelReasoningSettings)
    structured_output_method: StructuredOutputMethod | None = None

    @property
    def available(self) -> bool:
        return self.engine in {"llama_cpp_rocm", "external"} and bool(self.model and self.profile_id)

    @property
    def provider(self) -> str:
        return "external_inference" if self.engine == "external" else "local_llama_cpp_rocm"

    def metadata(self) -> dict[str, Any]:
        return {
            "model_role": self.role,
            "model": self.model or "",
            "model_profile_id": self.profile_id or "",
            "model_source": self.source,
            "engine": self.engine,
            "provider": self.provider,
            "provider_display_name": "Local AMD ROCm",
            "provider_adapter": "local_openai_compatible",
            "transport": "local_llama_cpp",
            "max_input_tokens": self.max_input_tokens,
            "compression_trigger_tokens": self.compression_trigger_tokens,
            "max_output_tokens": self.max_output_tokens,
            "multimodal": self.multimodal,
            "structured_output_method": self.structured_output_method or "",
            "structured_output_methods": ["function_calling", "json_mode", "json_schema"],
            "default_structured_output_method": "function_calling",
            "reasoning": {
                "enabled": self.reasoning.enabled,
                "effort": self.reasoning.effort,
                "summary": self.reasoning.summary,
                "budget_tokens": self.reasoning.budget_tokens,
                "send_history": self.reasoning.send_history,
                "supported": self.reasoning_supported,
                "efforts": list(self.reasoning_efforts),
            },
            "capabilities": {
                "tools": {
                    "tool_calling": self.tool_calling,
                    "strict_tool_schema": self.strict_tool_schema,
                }
            },
        }


def get_main_model() -> BaseChatModel | None:
    return _get_main_model()


def get_task_model() -> BaseChatModel | None:
    return _get_task_model()


def get_compression_model() -> BaseChatModel | None:
    return _get_compression_model()


def get_main_model_settings() -> ChatModelSettings:
    return _settings_for_role("main")


def get_task_model_settings() -> ChatModelSettings:
    return _settings_for_role("task")


def get_compression_model_settings() -> ChatModelSettings:
    return _settings_for_role("compression")


def reset_chat_models() -> None:
    _get_main_model.cache_clear()
    _get_task_model.cache_clear()
    _get_compression_model.cache_clear()


def create_chat_model_from_settings(settings: ChatModelSettings) -> BaseChatModel | None:
    if not settings.available:
        return None
    endpoint = load_local_inference_endpoint(timeout_seconds=settings.timeout_seconds)
    return LocalLlamaCppChatModel(
        model_name=str(settings.model),
        endpoint=endpoint,
        temperature=settings.temperature,
        max_output_tokens=settings.max_output_tokens,
        reasoning_enabled=settings.reasoning.enabled,
        model_role=settings.role,
    )


def settings_from_local_profile(profile: Any, *, role: str) -> ChatModelSettings:
    if str(profile.kind) != "chat":
        raise ValueError(f"local model profile {profile.profile_id} is not a chat profile")
    capabilities = profile.capabilities
    return ChatModelSettings(
        role=role,
        engine=str(profile.engine),
        model=str(profile.served_model_name),
        profile_id=str(profile.profile_id),
        source="model_pool",
        timeout_seconds=profile.limits.timeout_seconds,
        max_output_tokens=profile.limits.max_output_tokens,
        max_input_tokens=profile.limits.max_input_tokens,
        compression_trigger_tokens=profile.limits.context_compression_threshold_tokens,
        multimodal="image" in capabilities.input_modalities,
        tool_calling=bool(capabilities.tool_calling),
        strict_tool_schema=bool(capabilities.strict_tool_schema),
        reasoning_supported=bool(capabilities.reasoning_supported),
        reasoning_efforts=tuple(capabilities.reasoning_efforts),
        reasoning=ModelReasoningSettings(enabled=True if capabilities.reasoning_supported else None),
        structured_output_method=(
            capabilities.structured_output_methods[0]
            if capabilities.structured_output_methods
            else None
        ),
    )


@lru_cache(maxsize=1)
def _get_main_model() -> BaseChatModel | None:
    return create_chat_model_from_settings(get_main_model_settings())


@lru_cache(maxsize=1)
def _get_task_model() -> BaseChatModel | None:
    return create_chat_model_from_settings(get_task_model_settings())


@lru_cache(maxsize=1)
def _get_compression_model() -> BaseChatModel | None:
    return create_chat_model_from_settings(get_compression_model_settings())


def _settings_for_role(role: str) -> ChatModelSettings:
    profile_id = _profile_id_for_role(role)
    if not profile_id:
        return ChatModelSettings(role=role, engine="llama_cpp_rocm", model=None)
    from agent_factory.model_pool.store import ModelPoolStore

    profile = ModelPoolStore().require_profile(profile_id)
    settings = settings_from_local_profile(profile, role=role)
    return settings


def _profile_id_for_role(role: str) -> str | None:
    from agent_factory.model_pool.store import ModelPoolStore

    return ModelPoolStore().resolve_default_profile_id(role)




def list_supported_chat_model_profiles() -> list[dict[str, object]]:
    return [
        {
            "engine": "llama_cpp_rocm",
            "display_name": "llama.cpp on AMD ROCm",
            "transport": "local_llama_cpp",
        },
        {
            "engine": "external",
            "display_name": "External OpenAI-compatible inference",
            "transport": "openai_compatible",
        },
    ]
