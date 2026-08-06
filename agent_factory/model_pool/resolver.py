from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from agent_factory.artifact_system import ArtifactStore
from agent_factory.local_inference.config import load_local_image_endpoint
from agent_factory.model_pool.schema import (
    ExternalInferenceConfig,
    ModelProfileBinding,
    ModelSelectionRequest,
    ModelSelectionRequirement,
    ModelToolBinding,
    ModelToolSelectionRequirement,
    StableDiffusionCppInferenceConfig,
)
from agent_factory.model_pool.selector import ModelPoolSelector
from agent_factory.model_pool.store import ModelPoolStore
from agent_factory.models import ChatModelSettings
from agent_factory.models.chat_model import (
    create_chat_model_from_settings,
    settings_from_local_profile,
)
from agent_factory.models.image_generation import ImageGenerationService, ImageGenerationSettings


@dataclass(frozen=True, slots=True)
class ResolvedChatModelProfile:
    profile_id: str
    model: Any
    settings: ChatModelSettings


@dataclass(frozen=True, slots=True)
class ResolvedImageGenerationProfile:
    profile_id: str
    service: ImageGenerationService
    settings: ImageGenerationSettings


def resolve_chat_model_profile(
    binding: ModelProfileBinding,
    *,
    role: str,
    store: ModelPoolStore | None = None,
) -> ResolvedChatModelProfile:
    model_store = store or ModelPoolStore(setup=False)
    if not binding.profile_id:
        raise ValueError("resolved model_pool binding requires profile_id")
    profile = model_store.require_profile(binding.profile_id)
    if profile.kind != "chat":
        raise ValueError(f"local model profile {profile.profile_id} is {profile.kind}, expected chat")
    if not profile.enabled:
        raise ValueError(f"local model profile is disabled: {profile.profile_id}")
    artifact = model_store.require_artifact(profile.artifact_id)
    if not artifact.enabled:
        raise ValueError(f"local model artifact is disabled: {artifact.artifact_id}")
    overrides = binding.overrides
    settings = settings_from_local_profile(profile, role=role)
    settings = replace(
        settings,
        temperature=(
            overrides.temperature
            if overrides.temperature is not None
            else profile.settings.temperature
        ),
        max_output_tokens=(
            overrides.max_output_tokens
            if overrides.max_output_tokens is not None
            else settings.max_output_tokens
        ),
    )
    model = create_chat_model_from_settings(settings)
    if model is None:
        raise ValueError(f"local model profile is not runnable: {profile.profile_id}")
    return ResolvedChatModelProfile(profile_id=profile.profile_id, model=model, settings=settings)


def resolve_chat_model_binding(
    binding: ModelProfileBinding,
    *,
    role: str,
    store: ModelPoolStore | None = None,
) -> ResolvedChatModelProfile:
    if binding.source == "runtime":
        raise ValueError(f"runtime {role} chat model must be resolved from request state")
    if not binding.profile_id:
        profile_id = _select_chat_profile_id(binding, role=role, store=store)
        binding = binding.model_copy(update={"profile_id": profile_id})
    return resolve_chat_model_profile(binding, role=role, store=store)


def resolve_available_chat_model(
    role: str,
    *,
    store: ModelPoolStore | None = None,
) -> ResolvedChatModelProfile | None:
    try:
        return resolve_chat_model_binding(
            ModelProfileBinding(
                source="model_pool",
                selection_source="auto",
                reason=f"Select an available {role} model from the configured local model pool.",
            ),
            role=role,
            store=store,
        )
    except LookupError:
        return None


def resolve_image_generation_model_profile(
    binding: ModelToolBinding,
    *,
    artifact_store: ArtifactStore,
    store: ModelPoolStore | None = None,
) -> ResolvedImageGenerationProfile:
    resolved = _resolve_image_generation_profile(
        binding,
        artifact_store=artifact_store,
        store=store,
    )
    if resolved is None:
        raise ValueError("required image generation model profile is unavailable")
    return resolved


def resolve_image_generation_binding(
    binding: ModelToolBinding,
    *,
    artifact_store: ArtifactStore,
    store: ModelPoolStore | None = None,
) -> ResolvedImageGenerationProfile | None:
    return _resolve_image_generation_profile(
        binding,
        artifact_store=artifact_store,
        store=store,
    )


def _resolve_image_generation_profile(
    binding: ModelToolBinding,
    *,
    artifact_store: ArtifactStore,
    store: ModelPoolStore | None,
) -> ResolvedImageGenerationProfile | None:
    if binding.source == "runtime":
        raise ValueError(
            f"runtime model tool binding must be resolved from request state: {binding.capability}"
        )
    model_store = store or ModelPoolStore(setup=False)
    profile_id = binding.profile_id
    if not profile_id:
        profile_id = _select_image_profile_id(binding, store=model_store)
    if not profile_id:
        if not binding.required:
            return None
        raise ValueError("image generation binding has no configured profile")
    profile = model_store.get_profile(profile_id)
    if profile is None:
        if not binding.required:
            return None
        raise ValueError(f"unknown local image generation profile: {profile_id}")
    if profile.kind != "image_generation":
        raise ValueError(f"local model profile {profile.profile_id} is {profile.kind}, expected image_generation")
    artifact = model_store.get_artifact(profile.artifact_id)
    if artifact is None:
        if not binding.required:
            return None
        raise ValueError(f"image generation artifact is unavailable: {profile.artifact_id}")
    if not profile.enabled or not artifact.enabled:
        if not binding.required:
            return None
        raise ValueError(f"local image generation profile is disabled: {profile.profile_id}")
    endpoint = load_local_image_endpoint(timeout_seconds=profile.limits.timeout_seconds)
    inference = profile.inference
    if isinstance(inference, ExternalInferenceConfig):
        inference = inference.remote_inference
    if not isinstance(inference, StableDiffusionCppInferenceConfig):
        raise ValueError("image generation profile has no stable-diffusion.cpp runtime configuration")
    settings = ImageGenerationSettings(
        provider="stable_diffusion_cpp",
        model=profile.served_model_name,
        base_url=endpoint.base_url,
        profile_id=profile.profile_id,
        timeout_seconds=endpoint.timeout_seconds,
        default_options={
            "width": inference.default_width,
            "height": inference.default_height,
            "steps": inference.default_steps,
            "cfg_scale": inference.default_cfg_scale,
            "sampler": inference.default_sampler,
        },
    )
    return ResolvedImageGenerationProfile(
        profile_id=profile.profile_id,
        service=ImageGenerationService(settings=settings, artifact_store=artifact_store),
        settings=settings,
    )


def _select_chat_profile_id(
    binding: ModelProfileBinding,
    *,
    role: str,
    store: ModelPoolStore | None,
) -> str:
    model_store = store or ModelPoolStore(setup=False)
    default_role = role if role in {"main", "task", "compression"} else "task"
    assigned_profile_id = model_store.resolve_default_profile_id(default_role)
    requirement = _chat_requirement(binding, role=default_role)
    if assigned_profile_id:
        issues = ModelPoolSelector(store=model_store).profile_match_issues(
            assigned_profile_id,
            requirement,
        )
        if issues:
            raise LookupError(
                f"assigned {default_role} model {assigned_profile_id} does not match "
                f"runtime requirements: {', '.join(issues)}"
            )
        return assigned_profile_id
    selection = ModelPoolSelector(store=model_store).select(
        ModelSelectionRequest(requirements=[requirement])
    )
    recommendation = next(
        (item for item in selection.recommendations if item.role == default_role),
        None,
    )
    if recommendation is None:
        raise LookupError(f"no configured model pool profile matches the {role} model requirements")
    return recommendation.profile_id


def _select_image_profile_id(
    binding: ModelToolBinding,
    *,
    store: ModelPoolStore,
) -> str | None:
    requirement = ModelToolSelectionRequirement(
        tool_id="runtime_model_tool",
        capability=binding.capability,
        purpose=binding.reason,
        optimize_for="balanced",
    )
    default_profile_id = store.resolve_default_profile_id("image_generation")
    if default_profile_id:
        issues = ModelPoolSelector(store=store).profile_match_issues(
            default_profile_id,
            requirement.as_model_requirement(),
        )
        if issues:
            if binding.required:
                raise LookupError(
                    f"assigned image generation model {default_profile_id} does not match "
                    f"runtime requirements: {', '.join(issues)}"
                )
        else:
            return default_profile_id
    selection = ModelPoolSelector(store=store).select(
        ModelSelectionRequest(tool_requirements=[requirement])
    )
    recommendation = next(
        (
            item
            for item in selection.tool_recommendations
            if item.tool_id == requirement.tool_id
        ),
        None,
    )
    return recommendation.profile_id if recommendation is not None else None


def _chat_requirement(
    binding: ModelProfileBinding,
    *,
    role: str,
) -> ModelSelectionRequirement:
    capabilities = binding.required_capabilities
    return ModelSelectionRequirement(
        role=role,
        purpose=binding.reason,
        kind="chat",
        input_modalities=_strings(capabilities.get("input_modalities")) or ["text"],
        output_modalities=_strings(capabilities.get("output_modalities")) or ["text"],
        tool_calling=_optional_bool(capabilities.get("tool_calling")),
        structured_output_methods=_strings(capabilities.get("structured_output_methods")),
        reasoning_required=_optional_bool(capabilities.get("reasoning_required")),
        min_context_window_tokens=_optional_positive_int(
            capabilities.get("min_context_window_tokens")
        ),
        optimize_for="balanced",
    )


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := str(item or "").strip())]


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _optional_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
