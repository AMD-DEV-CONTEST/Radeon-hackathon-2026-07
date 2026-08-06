from __future__ import annotations

from typing import Any

from agent_factory.model_pool.resolver import ResolvedChatModelProfile, resolve_chat_model_profile
from agent_factory.model_pool.schema import ModelBindingRuntimeOverrides, ModelProfileBinding
from agent_factory.models.chat_model import (
    ChatModelSettings,
    create_chat_model_from_settings,
    get_main_model_settings,
)
from agent_factory.models.reasoning import (
    RUNTIME_REASONING_INTENSITY_MAX,
    apply_reasoning_intensity,
)


RUNTIME_MODEL_PROFILE_OVERRIDES_KEY = "model_profile_overrides"
RUNTIME_MAIN_MODEL_PROFILE_ID_KEY = "runtime_main_model_profile_id"
RUNTIME_REASONING_INTENSITY_KEY = "reasoning_intensity"


def main_model_profile_id_from_user_config(user_config: Any) -> str | None:
    if not isinstance(user_config, dict):
        return None
    overrides = user_config.get(RUNTIME_MODEL_PROFILE_OVERRIDES_KEY)
    if not isinstance(overrides, dict):
        return None
    profile_id = str(overrides.get("main") or "").strip()
    return profile_id or None


def effective_main_model_profile_id_from_user_config(user_config: Any) -> str | None:
    explicit_profile_id = main_model_profile_id_from_user_config(user_config)
    if explicit_profile_id:
        return explicit_profile_id
    return get_main_model_settings().profile_id


def runtime_main_model_profile_id_from_state(state: Any) -> str | None:
    if isinstance(state, dict):
        profile_id = str(state.get(RUNTIME_MAIN_MODEL_PROFILE_ID_KEY) or "").strip()
        return profile_id or None
    runtime_config = getattr(state, "runtime_config", None)
    user_config = getattr(runtime_config, "user_config", None)
    return main_model_profile_id_from_user_config(user_config)


def resolve_runtime_main_chat_model_from_state(
    state: Any,
    *,
    overrides: ModelBindingRuntimeOverrides | None = None,
) -> ResolvedChatModelProfile | None:
    profile_id = runtime_main_model_profile_id_from_state(state)
    if not profile_id:
        return None
    return resolve_runtime_main_chat_model(profile_id, overrides=overrides)


def resolve_runtime_main_chat_model(
    profile_id: str,
    *,
    overrides: ModelBindingRuntimeOverrides | None = None,
) -> ResolvedChatModelProfile:
    binding = ModelProfileBinding(
        profile_id=profile_id,
        selection_source="manual",
        reason="runtime main model override",
        overrides=overrides or ModelBindingRuntimeOverrides(),
    )
    return resolve_chat_model_profile(binding, role="main")


def runtime_reasoning_intensity_from_state(state: Any) -> int | None:
    user_config = _user_config_from_state(state)
    return runtime_reasoning_intensity_from_user_config(user_config)


def runtime_reasoning_intensity_from_user_config(user_config: Any) -> int | None:
    if not isinstance(user_config, dict):
        return None
    value = user_config.get(RUNTIME_REASONING_INTENSITY_KEY)
    if isinstance(value, bool):
        return None
    try:
        intensity = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, min(RUNTIME_REASONING_INTENSITY_MAX, intensity))


def resolve_runtime_reasoning_model(
    model: Any,
    settings: ChatModelSettings,
    state: Any,
) -> tuple[Any, ChatModelSettings]:
    intensity = runtime_reasoning_intensity_from_state(state)
    if intensity is None:
        return model, settings
    runtime_settings = apply_reasoning_intensity(settings, intensity)
    runtime_model = create_chat_model_from_settings(runtime_settings)
    if runtime_model is None:
        raise RuntimeError("runtime reasoning model is not configured")
    return runtime_model, runtime_settings


def _user_config_from_state(state: Any) -> dict[str, Any]:
    if isinstance(state, dict):
        user_config = state.get("user_config")
        if isinstance(user_config, dict):
            return user_config
        runtime_config = state.get("runtime_config")
        if isinstance(runtime_config, dict) and isinstance(runtime_config.get("user_config"), dict):
            return runtime_config["user_config"]
        if RUNTIME_REASONING_INTENSITY_KEY in state:
            return {RUNTIME_REASONING_INTENSITY_KEY: state.get(RUNTIME_REASONING_INTENSITY_KEY)}
        return {}
    runtime_config = getattr(state, "runtime_config", None)
    user_config = getattr(runtime_config, "user_config", None)
    return user_config if isinstance(user_config, dict) else {}
