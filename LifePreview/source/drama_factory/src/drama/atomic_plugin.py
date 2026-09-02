from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from functools import lru_cache

from atomic_runtime import (
    CapabilityPlugin,
    CapabilityRegistration,
    SafeErrorMapper,
    SafeErrorTemplate,
    UpcasterRegistry,
)
from shared_contracts import (
    CacheMode,
    CachePolicy,
    DeterminismClass,
    ImplementationManifest,
    InfrastructureRetryPolicy,
    OperationSpec,
    ProviderState,
    ReplayClass,
    ResourceClass,
    ResourceRequirement,
    RetryClass,
    SchemaRevision,
    TimeoutPolicy,
    build_implementation_digest,
    build_operation_spec_digest,
)

from .atomic_factory import (
    FACTORY_OPERATION_TYPES,
    NONDETERMINISTIC_OPERATION_TYPES,
    SEEDED_OPERATION_TYPES,
)


_QWEN_CUSTOM_VOICE_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"


@dataclass(frozen=True, slots=True)
class KeyframeProfile:
    provider_identity: str
    model_label: str
    workflow_label: str
    custom_node_environment_label: str


_KEYFRAME_PROFILES = {
    "qwen-image": KeyframeProfile(
        provider_identity="local-qwen-image-comfy",
        model_label="keyframe.generate:model-set:v1",
        workflow_label="keyframe.generate:workflow:v1",
        custom_node_environment_label="factory-comfy-custom-nodes:v1",
    ),
    "sdxl-core": KeyframeProfile(
        provider_identity="local-sdxl-comfy",
        model_label="sdxl-core:sd_xl_base_1.0.safetensors:model-set:v1",
        workflow_label="sdxl-core:keyframe_flux_api.json:workflow:v1",
        custom_node_environment_label=(
            "sdxl-core:comfy-core-only:no-custom-nodes:v1"
        ),
    ),
}


@lru_cache(maxsize=1)
def keyframe_profile() -> KeyframeProfile:
    selected = os.getenv("FACTORY_KEYFRAME_PROFILE", "qwen-image")
    try:
        return _KEYFRAME_PROFILES[selected]
    except KeyError:
        raise RuntimeError(
            "FACTORY_KEYFRAME_PROFILE must be qwen-image or sdxl-core"
        ) from None


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def comfy_operation_spec() -> OperationSpec:
    requirement = ResourceRequirement(
        device_type="cuda",
        minimum_vram_mb=12_000,
        target_vram_mb=24_000,
        model_digest=_digest("wan2.2-ti2v-5b:model-set:v1"),
        workflow_digest=_digest("wan2.2-ti2v-5b:workflow-family:v1"),
        custom_node_environment_digest=_digest("comfy-custom-nodes:v1"),
        estimated_duration_seconds=300,
        warm_model_affinity=("wan2.2-ti2v-5b",),
    )
    spec_values = {
        "op_type": "drama.comfy_video_generate",
        "op_version": SchemaRevision(major=1, minor=0),
        "input_schema_version": SchemaRevision(major=1, minor=0),
        "output_schema_version": SchemaRevision(major=1, minor=0),
        "resource_class": ResourceClass.LOCAL_GPU,
        "resource_requirement": requirement,
        "determinism_class": DeterminismClass.SEEDED,
        "cache_policy": CachePolicy(mode=CacheMode.DISABLED),
        "timeout_policy": TimeoutPolicy(
            execution_timeout_seconds=3600,
            heartbeat_timeout_seconds=30,
            reconciliation_timeout_seconds=600,
        ),
        "infrastructure_retry_policy": InfrastructureRetryPolicy(
            maximum_attempts=1,
            initial_backoff_seconds=0,
            maximum_backoff_seconds=0,
        ),
        "supported_defect_codes": (
            "provider_output_invalid",
            "provider_outcome_unknown",
        ),
        "supported_repair_actions": (
            "reconcile_provider",
            "rerun_generation",
        ),
        "implementation_entrypoint": (
            "drama.atomic_provider:create_durable_provider_executor"
        ),
    }
    return OperationSpec(
        **spec_values,
        spec_digest=build_operation_spec_digest(**spec_values),
    )


@lru_cache(maxsize=1)
def comfy_implementation_manifest() -> ImplementationManifest:
    manifest_values = {
        "manifest_schema_version": SchemaRevision(major=1, minor=0),
        "replay_class": ReplayClass.REPLAYABLE,
        "code_image_digest": _digest("douyin-drama-factory:image:v1"),
        "adapter_digest": _digest("generalized-durable-provider-atomic-adapter:v1"),
        "comfy_workflow_digest": _digest("wan2.2-ti2v-5b:workflow-family:v1"),
        "custom_node_set_digest": _digest("comfy-custom-nodes:v1"),
        "model_weight_digests": (_digest("wan2.2-ti2v-5b:model-set:v1"),),
        "upcaster_digest": UpcasterRegistry().registry_digest(),
        "provider_identity": "local-wan-comfy",
    }
    return ImplementationManifest(
        **manifest_values,
        implementation_digest=build_implementation_digest(**manifest_values),
    )


def _error_mapper() -> SafeErrorMapper:
    contract = SafeErrorTemplate(
        error_code="provider_contract_invalid",
        retry_class=RetryClass.NEVER,
        public_message="The durable provider contract was rejected.",
        operator_detail=(
            "The generalized provider invocation did not match the pinned operation."
        ),
        provider_state=ProviderState.NOT_APPLICABLE,
    )
    unknown = SafeErrorTemplate(
        error_code="provider_outcome_unknown",
        retry_class=RetryClass.RECONCILE_PROVIDER,
        public_message="The provider outcome is not yet known.",
        operator_detail="Reconcile by persisted nonce and client identity; do not resubmit.",
        provider_state=ProviderState.OUTCOME_UNKNOWN,
    )
    rejected = SafeErrorTemplate(
        error_code="provider_submit_rejected",
        retry_class=RetryClass.NEVER,
        public_message="The provider rejected the generation request.",
        operator_detail="A terminal provider rejection was persisted without provider payload.",
        provider_state=ProviderState.OBSERVED_TERMINAL,
    )
    invalid = SafeErrorTemplate(
        error_code="provider_output_invalid",
        retry_class=RetryClass.NEVER,
        public_message="The generated media did not pass validation.",
        operator_detail="The provider artifact failed the pinned output verifier.",
        provider_state=ProviderState.OBSERVED_TERMINAL,
    )
    human = SafeErrorTemplate(
        error_code="provider_reconciliation_human_required",
        retry_class=RetryClass.HUMAN_REQUIRED,
        public_message="The provider invocation requires operator review.",
        operator_detail=(
            "The generalized durable provider authority cannot reconcile safely."
        ),
        provider_state=ProviderState.OUTCOME_UNKNOWN,
    )
    return SafeErrorMapper(
        {
            (
                "drama.v3.durable_comfy:"
                "ComfySubmissionOutcomeUnknown"
            ): unknown,
            "drama.v3.provider_adapter:DramaProviderRejected": rejected,
            "drama.v3.durable_comfy:ComfySubmitRejected": rejected,
            "drama.v3.durable_comfy:ComfyOutputInvalid": invalid,
            "drama.v3.durable_provider:ProviderResponseLost": unknown,
            "drama.v3.durable_provider:ProviderRejected": rejected,
            "drama.v3.durable_provider:ProviderStateConflict": invalid,
            "drama.v3.durable_provider:ProviderHumanRequired": human,
            "drama.atomic_provider:DurableProviderAtomicContractError": contract,
        },
        outcome_unknown_types=(
            (
                "drama.v3.durable_comfy:"
                "ComfySubmissionOutcomeUnknown"
            ),
            "drama.v3.durable_provider:ProviderResponseLost",
        ),
    )


_FACTORY_LOCAL_GPU_OPERATIONS = frozenset(
    {
        "asset.character.generate",
        "asset.scene.generate",
        "asset.prop.generate",
        "keyframe.generate",
        "video.generate",
    }
)

_FACTORY_LLM_OPERATIONS = frozenset(
    {
        "chapter.enrich",
        "bible.story.generate",
        "bible.character.generate",
        "bible.world.generate",
        "asset.plan",
        "storyboard.generate",
    }
)


def _factory_resource_class(op_type: str) -> ResourceClass:
    if op_type in _FACTORY_LOCAL_GPU_OPERATIONS:
        return ResourceClass.LOCAL_GPU
    if op_type in _FACTORY_LLM_OPERATIONS:
        return ResourceClass.LLM
    return ResourceClass.CPU


def _factory_determinism(op_type: str) -> DeterminismClass:
    if op_type in SEEDED_OPERATION_TYPES:
        return DeterminismClass.SEEDED
    if op_type in NONDETERMINISTIC_OPERATION_TYPES:
        return DeterminismClass.NONDETERMINISTIC
    return DeterminismClass.DETERMINISTIC


def _factory_provider(op_type: str) -> str:
    if op_type == "video.generate":
        return "local-wan-comfy"
    if op_type == "keyframe.generate":
        return keyframe_profile().provider_identity
    if op_type.startswith("asset.") and op_type.endswith(".generate"):
        return "local-qwen-image-comfy"
    if op_type == "speech.synthesize":
        return "qwen3-tts-custom-voice-mcp"
    if op_type in _FACTORY_LLM_OPERATIONS:
        return "factory-llm-router"
    return "factory-local-core"


def _factory_resource_requirement(op_type: str) -> ResourceRequirement | None:
    if op_type not in _FACTORY_LOCAL_GPU_OPERATIONS:
        return None
    profile = keyframe_profile() if op_type == "keyframe.generate" else None
    model_digest = _digest(
        profile.model_label if profile is not None else f"{op_type}:model-set:v1"
    )
    workflow_digest = _digest(
        profile.workflow_label if profile is not None else f"{op_type}:workflow:v1"
    )
    return ResourceRequirement(
        device_type="cuda",
        minimum_vram_mb=12_000,
        target_vram_mb=24_000,
        model_digest=model_digest,
        workflow_digest=workflow_digest,
        custom_node_environment_digest=_digest(
            profile.custom_node_environment_label
            if profile is not None
            else "factory-comfy-custom-nodes:v1"
        ),
        estimated_duration_seconds=(
            600 if op_type == "video.generate" else 180
        ),
        warm_model_affinity=(_factory_provider(op_type),),
    )


@lru_cache(maxsize=1)
def factory_operation_specs() -> tuple[OperationSpec, ...]:
    specs: list[OperationSpec] = []
    for op_type in FACTORY_OPERATION_TYPES:
        resource_class = _factory_resource_class(op_type)
        requirement = _factory_resource_requirement(op_type)
        spec_values = {
            "op_type": op_type,
            "op_version": SchemaRevision(major=1, minor=0),
            "input_schema_version": SchemaRevision(major=1, minor=0),
            "output_schema_version": SchemaRevision(major=1, minor=0),
            "resource_class": resource_class,
            "resource_requirement": requirement,
            "determinism_class": _factory_determinism(op_type),
            "cache_policy": CachePolicy(
                mode=(
                    CacheMode.INPUT_DIGEST
                    if op_type not in NONDETERMINISTIC_OPERATION_TYPES
                    else CacheMode.DISABLED
                )
            ),
            "timeout_policy": TimeoutPolicy(
                execution_timeout_seconds=(
                    3600 if resource_class is ResourceClass.LOCAL_GPU else 900
                ),
                heartbeat_timeout_seconds=30,
                reconciliation_timeout_seconds=(
                    600 if resource_class is ResourceClass.LOCAL_GPU else None
                ),
            ),
            # Retry ownership stays in the orchestration runtime. Wrappers do
            # not introduce a second retry loop.
            "infrastructure_retry_policy": InfrastructureRetryPolicy(
                maximum_attempts=1,
                initial_backoff_seconds=0,
                maximum_backoff_seconds=0,
            ),
            "supported_defect_codes": (
                "factory_contract_invalid",
                "factory_core_rejected",
                "provider_outcome_unknown",
            ),
            "supported_repair_actions": (
                "reconcile_provider",
                "rerun_with_new_attempt",
            ),
            "implementation_entrypoint": (
                "drama.atomic_provider:create_factory_video_provider_executor"
                if op_type == "video.generate"
                else "drama.atomic_factory:create_atomic_factory_executor"
            ),
        }
        specs.append(
            OperationSpec(
                **spec_values,
                spec_digest=build_operation_spec_digest(**spec_values),
            )
        )
    return tuple(specs)


@lru_cache(maxsize=1)
def factory_implementation_manifests() -> tuple[ImplementationManifest, ...]:
    upcaster_digest = UpcasterRegistry().registry_digest()
    manifests: list[ImplementationManifest] = []
    for op_type in FACTORY_OPERATION_TYPES:
        requirement = _factory_resource_requirement(op_type)
        replay_class = (
            ReplayClass.IDENTIFIABLE_ONLY
            if op_type in NONDETERMINISTIC_OPERATION_TYPES
            else ReplayClass.REPLAYABLE
        )
        manifest_values = {
            "manifest_schema_version": SchemaRevision(major=1, minor=0),
            "replay_class": replay_class,
            "code_image_digest": _digest("douyin-drama-factory:image:v1"),
            "adapter_digest": _digest(f"factory-atomic-adapter:{op_type}:v1"),
            "comfy_workflow_digest": (
                requirement.workflow_digest if requirement is not None else None
            ),
            "custom_node_set_digest": (
                requirement.custom_node_environment_digest
                if requirement is not None
                else None
            ),
            "model_weight_digests": (
                (_digest(_QWEN_CUSTOM_VOICE_MODEL_ID),)
                if op_type == "speech.synthesize"
                else (requirement.model_digest,)
                if requirement is not None
                else ()
            ),
            "prompt_digest": (
                _digest(f"factory-prompt:{op_type}:v1")
                if op_type in NONDETERMINISTIC_OPERATION_TYPES
                else None
            ),
            "upcaster_digest": upcaster_digest,
            "provider_identity": _factory_provider(op_type),
        }
        manifests.append(
            ImplementationManifest(
                **manifest_values,
                implementation_digest=build_implementation_digest(
                    **manifest_values
                ),
            )
        )
    return tuple(manifests)


def _factory_error_mapper() -> SafeErrorMapper:
    contract = SafeErrorTemplate(
        error_code="factory_contract_invalid",
        retry_class=RetryClass.NEVER,
        public_message="The Factory operation contract was rejected.",
        operator_detail=(
            "The atomic Factory adapter rejected identity, seed, mode, or "
            "ArtifactRef validation without exposing request payloads."
        ),
        provider_state=ProviderState.NOT_APPLICABLE,
    )
    rejected = SafeErrorTemplate(
        error_code="factory_core_rejected",
        retry_class=RetryClass.NEVER,
        public_message="The Factory core could not produce the requested artifact.",
        operator_detail=(
            "The wrapped legacy or V3 Factory core failed after contract validation."
        ),
        provider_state=ProviderState.OBSERVED_TERMINAL,
    )
    unknown = SafeErrorTemplate(
        error_code="provider_outcome_unknown",
        retry_class=RetryClass.RECONCILE_PROVIDER,
        public_message="The provider outcome is not yet known.",
        operator_detail=(
            "Reconcile the persisted provider identity before any resubmission."
        ),
        provider_state=ProviderState.OUTCOME_UNKNOWN,
    )
    return SafeErrorMapper(
        {
            "drama.atomic_factory:FactoryAtomicContractError": contract,
            "drama.atomic_factory:FactoryCoreError": rejected,
            "drama.atomic_factory:FactoryProviderOutcomeUnknown": unknown,
            (
                "drama.atomic_provider:"
                "DurableProviderAtomicContractError"
            ): contract,
        },
        outcome_unknown_types=(
            "drama.atomic_factory:FactoryProviderOutcomeUnknown",
        ),
    )


@lru_cache(maxsize=1)
def factory_registrations() -> tuple[CapabilityRegistration, ...]:
    error_mapper = _factory_error_mapper()
    return tuple(
        CapabilityRegistration(
            spec=spec,
            implementation_manifest=manifest,
            error_mapper=error_mapper,
        )
        for spec, manifest in zip(
            factory_operation_specs(),
            factory_implementation_manifests(),
            strict=True,
        )
    )


@lru_cache(maxsize=1)
def build_plugin() -> CapabilityPlugin:
    return CapabilityPlugin(
        name="douyin-drama-factory",
        registrations=(
            CapabilityRegistration(
                spec=comfy_operation_spec(),
                implementation_manifest=comfy_implementation_manifest(),
                error_mapper=_error_mapper(),
            ),
            *factory_registrations(),
        ),
    )
