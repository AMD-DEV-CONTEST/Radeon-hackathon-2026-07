from __future__ import annotations

import argparse
from pathlib import Path

from agent_factory.model_pool.schema import (
    ExternalInferenceConfig,
    LlamaCppInferenceConfig,
    LlamaCppMtpConfig,
    LlamaCppSpeculativeDecodingDisabledConfig,
    LocalModelArtifact,
    ModelContextExtensionCapability,
    ModelPoolCapabilities,
    ModelPoolLimits,
    ModelPoolProfile,
    StableDiffusionCppInferenceConfig,
    TransformersInferenceConfig,
)
from agent_factory.model_pool.store import ModelPoolStore


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    if not args.only_image:
        required_full = (
            "chat_profile_id",
            "chat_served_model_name",
            "chat_native_context_tokens",
            "context_size",
            "max_output_tokens",
            "compression_threshold",
            "gpu_layers",
            "parallel_slots",
            "cache_type_k",
            "cache_type_v",
            "embedding_profile_id",
            "embedding_served_model_name",
            "embedding_dimensions",
        )
        missing = [name for name in required_full if getattr(args, name) in {None, ""}]
        if missing:
            parser.error("full configuration requires: " + ", ".join(missing))
    if args.mode == "node" and args.image_model_path is None:
        parser.error("node mode requires an image model path")
    if args.mode == "node" and not args.only_image and (
        args.chat_model_path is None or args.embedding_model_path is None
    ):
        parser.error("full node configuration requires chat and embedding model paths")
    store = ModelPoolStore(path=args.store_path)
    if args.only_image:
        image_profile = _upsert_image_profile(store, args)
        if args.prune_unconfigured_models:
            store.prune_catalog(
                kinds={"image_generation"},
                keep_profile_ids={image_profile.profile_id},
                keep_artifact_ids={image_profile.artifact_id},
            )
        if image_profile.enabled:
            store.disable_other_profiles("image_generation", image_profile.profile_id)
            store.set_default_profile_id("image_generation", image_profile.profile_id)
        store.set_active_profile_id(
            "image_generation",
            image_profile.profile_id if image_profile.enabled else None,
        )
        return
    chat_inference = LlamaCppInferenceConfig(
        gpu_layers=args.gpu_layers,
        parallel_slots=args.parallel_slots,
        cache_type_k=args.cache_type_k,
        cache_type_v=args.cache_type_v,
        flash_attention=args.flash_attention,
        mmproj_path=str(args.chat_mmproj_path) if args.chat_mmproj_path else None,
        speculative_decoding=(
            LlamaCppMtpConfig(
                max_draft_tokens=args.chat_mtp_max_draft_tokens,
                min_draft_tokens=args.chat_mtp_min_draft_tokens,
                min_acceptance_probability=args.chat_mtp_min_acceptance_probability,
                backend_sampling=args.chat_mtp_backend_sampling,
            )
            if args.chat_mtp_enabled
            else LlamaCppSpeculativeDecodingDisabledConfig()
        ),
    )
    chat_context_extension = (
        ModelContextExtensionCapability(
            method="yarn",
            max_context_tokens=args.chat_yarn_max_context_tokens,
        )
        if args.chat_yarn_max_context_tokens is not None
        else None
    )
    embedding_inference = TransformersInferenceConfig(
        trust_remote_code=args.embedding_trust_remote_code,
    )
    if args.mode == "node":
        chat_artifact = LocalModelArtifact(
            artifact_id=args.chat_artifact_id,
            display_name=args.chat_served_model_name,
            kind="chat",
            source="local_storage",
            local_path=str(args.chat_model_path),
            model_format="llama_cpp",
            revision=args.chat_revision,
            checksum=args.chat_checksum,
            native_context_tokens=args.chat_native_context_tokens,
            context_extension=chat_context_extension,
        )
        embedding_artifact = LocalModelArtifact(
            artifact_id=args.embedding_artifact_id,
            display_name=args.embedding_served_model_name,
            kind="embedding",
            source="local_storage",
            local_path=str(args.embedding_model_path),
            model_format="transformers",
            revision=args.embedding_revision,
        )
        chat_engine = "llama_cpp_rocm"
        embedding_engine = "transformers_rocm"
        chat_profile_inference = chat_inference
        embedding_profile_inference = embedding_inference
    else:
        chat_artifact = LocalModelArtifact(
            artifact_id=args.chat_artifact_id,
            display_name=args.chat_served_model_name,
            kind="chat",
            source="external_endpoint",
            external_model_id=args.chat_served_model_name,
            model_format="llama_cpp",
            revision=args.chat_revision,
            checksum=args.chat_checksum,
            native_context_tokens=args.chat_native_context_tokens,
            context_extension=chat_context_extension,
        )
        embedding_artifact = LocalModelArtifact(
            artifact_id=args.embedding_artifact_id,
            display_name=args.embedding_served_model_name,
            kind="embedding",
            source="external_endpoint",
            external_model_id=args.embedding_served_model_name,
            model_format="transformers",
            revision=args.embedding_revision,
        )
        chat_engine = "external"
        embedding_engine = "external"
        chat_profile_inference = ExternalInferenceConfig(remote_inference=chat_inference)
        embedding_profile_inference = ExternalInferenceConfig(remote_inference=embedding_inference)

    store.upsert_artifact(chat_artifact)
    store.upsert_artifact(embedding_artifact)
    chat_profile = store.upsert_profile(
        ModelPoolProfile(
            profile_id=args.chat_profile_id,
            display_name=args.chat_served_model_name,
            description=_profile_description(store, args.chat_profile_id, args.chat_description),
            kind="chat",
            artifact_id=chat_artifact.artifact_id,
            engine=chat_engine,
            served_model_name=args.chat_served_model_name,
            capabilities=ModelPoolCapabilities(
                input_modalities=["text", "image"] if args.chat_mmproj_path else ["text"],
                output_modalities=["text"],
                tool_calling=True,
                structured_output_methods=["function_calling", "json_mode"],
                reasoning_supported=args.reasoning_supported,
                reasoning_content=args.reasoning_supported,
            ),
            limits=ModelPoolLimits(
                max_input_tokens=args.context_size,
                max_output_tokens=args.max_output_tokens,
                context_compression_threshold_tokens=args.compression_threshold,
            ),
            inference=chat_profile_inference,
        )
    )
    embedding_profile = store.upsert_profile(
        ModelPoolProfile(
            profile_id=args.embedding_profile_id,
            display_name=args.embedding_served_model_name,
            description=_profile_description(store, args.embedding_profile_id, args.embedding_description),
            kind="embedding",
            artifact_id=embedding_artifact.artifact_id,
            engine=embedding_engine,
            served_model_name=args.embedding_served_model_name,
            capabilities=ModelPoolCapabilities(
                input_modalities=["text"],
                output_modalities=["text"],
                tool_calling=False,
                structured_output_methods=[],
            ),
            limits=ModelPoolLimits(),
            inference=embedding_profile_inference,
            embedding_dimensions=args.embedding_dimensions,
            normalize_embeddings=True,
        )
    )
    image_profile = _upsert_image_profile(store, args)
    if args.prune_unconfigured_models:
        store.prune_catalog(
            kinds={"chat", "embedding", "image_generation"},
            keep_profile_ids={
                chat_profile.profile_id,
                embedding_profile.profile_id,
                image_profile.profile_id,
            },
            keep_artifact_ids={
                chat_profile.artifact_id,
                embedding_profile.artifact_id,
                image_profile.artifact_id,
            },
        )
    store.disable_other_profiles("chat", chat_profile.profile_id)
    store.disable_other_profiles("embedding", embedding_profile.profile_id)
    if image_profile.enabled:
        store.disable_other_profiles("image_generation", image_profile.profile_id)
    for role in ("main", "task", "compression"):
        store.set_default_profile_id(role, chat_profile.profile_id)
    store.set_default_profile_id("embedding", embedding_profile.profile_id)
    if image_profile.enabled:
        store.set_default_profile_id("image_generation", image_profile.profile_id)
    store.set_active_profile_id("chat", chat_profile.profile_id)
    store.set_active_profile_id("embedding", embedding_profile.profile_id)
    store.set_active_profile_id(
        "image_generation",
        image_profile.profile_id if image_profile.enabled else None,
    )


def _upsert_image_profile(store: ModelPoolStore, args: argparse.Namespace) -> ModelPoolProfile:
    inference = StableDiffusionCppInferenceConfig(
        vae_path=str(args.image_vae_path),
        clip_l_path=str(args.image_clip_l_path),
        t5xxl_path=str(args.image_t5xxl_path),
        diffusion_flash_attention=args.image_diffusion_flash_attention,
        eager_load=args.image_eager_load,
        clip_on_cpu=args.image_clip_on_cpu,
        vae_tiling=args.image_vae_tiling,
        offload_to_cpu=args.image_offload_to_cpu,
        max_vram_gib=args.image_max_vram_gib,
        stream_layers=args.image_stream_layers,
        default_width=args.image_default_width,
        default_height=args.image_default_height,
        default_steps=args.image_default_steps,
        default_cfg_scale=args.image_default_cfg_scale,
        residency_policy=args.image_residency_policy,
    )
    if args.mode == "node":
        artifact = LocalModelArtifact(
            artifact_id=args.image_artifact_id,
            display_name=args.image_served_model_name,
            kind="image_generation",
            source="local_storage",
            local_path=str(args.image_model_path),
            model_format="stable_diffusion_cpp",
            revision=args.image_revision,
            checksum=args.image_checksum,
            license=args.image_license,
        )
        engine = "stable_diffusion_cpp_rocm"
        profile_inference = inference
    else:
        artifact = LocalModelArtifact(
            artifact_id=args.image_artifact_id,
            display_name=args.image_served_model_name,
            kind="image_generation",
            source="external_endpoint",
            external_model_id=args.image_served_model_name,
            model_format="stable_diffusion_cpp",
            revision=args.image_revision,
            checksum=args.image_checksum,
            license=args.image_license,
        )
        engine = "external"
        profile_inference = ExternalInferenceConfig(remote_inference=inference)
    store.upsert_artifact(artifact)
    return store.upsert_profile(
        ModelPoolProfile(
            profile_id=args.image_profile_id,
            display_name=args.image_served_model_name,
            description=_profile_description(store, args.image_profile_id, args.image_description),
            kind="image_generation",
            artifact_id=artifact.artifact_id,
            engine=engine,
            served_model_name=args.image_served_model_name,
            enabled=args.image_enabled,
            capabilities=ModelPoolCapabilities(
                input_modalities=["text"],
                output_modalities=["image"],
                tool_calling=False,
                structured_output_methods=[],
                text_to_image=True,
                async_job=True,
            ),
            limits=ModelPoolLimits(timeout_seconds=args.image_timeout_seconds),
            inference=profile_inference,
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create deterministic chat and embedding profiles")
    parser.add_argument("--mode", choices=("node", "client"), required=True)
    parser.add_argument("--store-path", type=Path, required=True)
    parser.add_argument("--only-image", action="store_true")
    parser.add_argument("--prune-unconfigured-models", action="store_true")
    parser.add_argument("--chat-artifact-id", default="qwen3_6_35b_a3b_apex_i_quality_gguf")
    parser.add_argument("--chat-profile-id")
    parser.add_argument("--chat-served-model-name")
    parser.add_argument("--chat-model-path", type=Path)
    parser.add_argument("--chat-mmproj-path")
    parser.add_argument("--chat-revision", default="")
    parser.add_argument("--chat-checksum", default="")
    parser.add_argument("--chat-native-context-tokens", type=int)
    parser.add_argument("--chat-yarn-max-context-tokens", type=int)
    parser.add_argument("--context-size", type=int)
    parser.add_argument("--max-output-tokens", type=int)
    parser.add_argument("--compression-threshold", type=int)
    parser.add_argument("--gpu-layers", type=int)
    parser.add_argument("--parallel-slots", type=int)
    parser.add_argument("--cache-type-k")
    parser.add_argument("--cache-type-v")
    parser.add_argument("--flash-attention", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--chat-mtp-enabled", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--chat-mtp-max-draft-tokens", type=int, default=3)
    parser.add_argument("--chat-mtp-min-draft-tokens", type=int, default=0)
    parser.add_argument("--chat-mtp-min-acceptance-probability", type=float, default=0.0)
    parser.add_argument("--chat-mtp-backend-sampling", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--reasoning-supported",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--embedding-artifact-id", default="bge_m3_transformers")
    parser.add_argument("--embedding-profile-id")
    parser.add_argument("--embedding-served-model-name")
    parser.add_argument("--chat-description")
    parser.add_argument("--embedding-description")
    parser.add_argument("--embedding-model-path", type=Path)
    parser.add_argument("--embedding-revision", default="")
    parser.add_argument("--embedding-dimensions", type=int)
    parser.add_argument(
        "--embedding-trust-remote-code",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument("--image-artifact-id", default="flux1_dev_q4_0")
    parser.add_argument("--image-profile-id", required=True)
    parser.add_argument("--image-served-model-name", required=True)
    parser.add_argument("--image-description")
    parser.add_argument("--image-model-path", type=Path)
    parser.add_argument("--image-vae-path", required=True)
    parser.add_argument("--image-clip-l-path", required=True)
    parser.add_argument("--image-t5xxl-path", required=True)
    parser.add_argument("--image-revision", default="")
    parser.add_argument("--image-checksum", default="")
    parser.add_argument("--image-license", default="FLUX.1-dev Non-Commercial License")
    parser.add_argument("--image-enabled", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--image-diffusion-flash-attention", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--image-eager-load", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--image-clip-on-cpu", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--image-vae-tiling", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--image-offload-to-cpu", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--image-max-vram-gib", type=float)
    parser.add_argument("--image-stream-layers", type=int)
    parser.add_argument("--image-default-width", type=int, default=1024)
    parser.add_argument("--image-default-height", type=int, default=1024)
    parser.add_argument("--image-default-steps", type=int, default=20)
    parser.add_argument("--image-default-cfg-scale", type=float, default=1.0)
    parser.add_argument("--image-residency-policy", choices=("coexist_if_fit", "exclusive"), default="coexist_if_fit")
    parser.add_argument("--image-timeout-seconds", type=float, default=900.0)
    return parser


def _profile_description(store: ModelPoolStore, profile_id: str, configured: str | None) -> str:
    if configured is not None:
        return configured.strip()
    existing = store.get_profile(profile_id)
    return existing.description if existing is not None else ""


if __name__ == "__main__":
    main()
