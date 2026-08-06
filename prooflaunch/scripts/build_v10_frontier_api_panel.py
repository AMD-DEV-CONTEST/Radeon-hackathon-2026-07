#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.v10_frontier_api_panel import (
    AccessClass,
    CapabilityLane,
    DEFAULT_AGENT_LADDER,
    FrontierModel,
    MiniMaxVideoRequest,
    OpenWeightStatus,
    admitted_candidates,
    request_ceiling,
)
from prooflaunch_remix.v10_supply_chain import stable_sha256


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/cortex_x_v10_frontier_api_panel.json"
EVIDENCE = ROOT / "evidence/v10/frontier-api-panel-preflight.json"


def model(
    candidate_id: str,
    provider: str,
    api_model: str,
    endpoint: str,
    lane: CapabilityLane,
    access_class: AccessClass,
    key_env: str,
    source_url: str,
    catalog_observed: bool,
    open_status: OpenWeightStatus,
    call_cap: float,
) -> FrontierModel:
    return FrontierModel(
        candidate_id,
        provider,
        api_model,
        endpoint,
        lane,
        access_class,
        key_env,
        call_cap,
        source_url,
        "2026-08-02",
        catalog_observed,
        open_status,
    )


def candidates() -> tuple[FrontierModel, ...]:
    amd_endpoint = "https://developer.amd.com.cn/radeon/api/v1/chat/completions"
    amd_source = "https://developer.amd.com.cn/radeon/tokenfactory"
    openrouter_endpoint = "https://openrouter.ai/api/v1/chat/completions"
    openrouter_source = "https://openrouter.ai/docs/guides/routing/model-variants/free"
    groq_endpoint = "https://api.groq.com/openai/v1/chat/completions"
    groq_source = "https://console.groq.com/docs/rate-limits"
    nvidia_endpoint = "https://integrate.api.nvidia.com/v1/chat/completions"
    nvidia_source = "https://build.nvidia.com/explore/discover?api-key=true"
    sambanova_endpoint = "https://api.sambanova.ai/v1/chat/completions"
    sambanova_source = "https://docs.sambanova.ai/docs/en/models/rate-limits"
    mistral_endpoint = "https://api.mistral.ai/v1/chat/completions"
    mistral_source = "https://docs.mistral.ai/getting-started/quickstarts/studio/activate-and-generate-api-key"
    cerebras_endpoint = "https://api.cerebras.ai/v1/chat/completions"
    cerebras_source = "https://inference-docs.cerebras.ai/support/rate-limits"
    gemini_endpoint = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    gemini_source = "https://ai.google.dev/gemini-api/docs/pricing"
    cloudflare_endpoint = "https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/v1/chat/completions"
    cloudflare_source = "https://developers.cloudflare.com/workers-ai/platform/pricing/"
    lightning_endpoint = "https://lightning.ai/api/v1/chat/completions"
    lightning_source = "https://lightning.ai/docs/platform/inference/model-apis"
    cohere_endpoint = "https://api.cohere.ai/compatibility/v1/chat/completions"
    cohere_source = "https://docs.cohere.com/v2/docs/rate-limits"
    huggingface_endpoint = "https://router.huggingface.co/v1/chat/completions"
    huggingface_source = "https://huggingface.co/docs/inference-providers/en/pricing"
    dashscope_endpoint = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    dashscope_source = "https://help.aliyun.com/en/model-studio/new-free-quota"
    return (
        model("amd-deepseek-v4-flash-0731", "amd_radeon_token_factory", "DeepSeek-V4-Flash", amd_endpoint, CapabilityLane.AGENTIC_GTM, AccessClass.AMD_SPONSORED_QUOTA, "RADEON_TOKEN_FACTORY_API_KEY", "https://api-docs.deepseek.com/updates/", True, OpenWeightStatus.ANNOUNCED_NOT_VERIFIED, 0.02),
        model("amd-minimax-m3", "amd_radeon_token_factory", "MiniMax-M3", amd_endpoint, CapabilityLane.AGENTIC_GTM, AccessClass.AMD_SPONSORED_QUOTA, "RADEON_TOKEN_FACTORY_API_KEY", "https://platform.minimax.io/docs/guides/text-generation", True, OpenWeightStatus.ANNOUNCED_NOT_VERIFIED, 0.02),
        model("amd-qwen3.6-35b-a3b", "amd_radeon_token_factory", "Qwen3.6-35B-A3B", amd_endpoint, CapabilityLane.LONG_CONTEXT_CRITIC, AccessClass.AMD_SPONSORED_QUOTA, "RADEON_TOKEN_FACTORY_API_KEY", amd_source, True, OpenWeightStatus.UNKNOWN, 0.02),
        model("amd-minicpm5-1b", "amd_radeon_token_factory", "MiniCPM5-1B", amd_endpoint, CapabilityLane.LONG_CONTEXT_CRITIC, AccessClass.AMD_SPONSORED_QUOTA, "RADEON_TOKEN_FACTORY_API_KEY", amd_source, True, OpenWeightStatus.UNKNOWN, 0.01),
        model("amd-minicpm-v46", "amd_radeon_token_factory", "dynamic-model-minicpm-v46/MiniCPM-V46", amd_endpoint, CapabilityLane.AGENTIC_GTM, AccessClass.AMD_SPONSORED_QUOTA, "RADEON_TOKEN_FACTORY_API_KEY", amd_source, True, OpenWeightStatus.UNKNOWN, 0.01),
        model("deepseek-direct-v4-flash-0731", "deepseek", "deepseek-v4-flash", "https://api.deepseek.com/chat/completions", CapabilityLane.AGENTIC_GTM, AccessClass.DIRECT_PAYG, "DEEPSEEK_API_KEY", "https://api-docs.deepseek.com/news/news260424", True, OpenWeightStatus.VERIFIED, 0.10),
        model("deepseek-direct-v4-pro", "deepseek", "deepseek-v4-pro", "https://api.deepseek.com/chat/completions", CapabilityLane.LONG_CONTEXT_CRITIC, AccessClass.DIRECT_PAYG, "DEEPSEEK_API_KEY", "https://api-docs.deepseek.com/quick_start/pricing/", True, OpenWeightStatus.VERIFIED, 0.25),
        model("minimax-direct-m3", "minimax", "MiniMax-M3", "https://api.minimax.io/v1/chat/completions", CapabilityLane.MULTIMODAL_GTM, AccessClass.DIRECT_PAYG, "MINIMAX_API_KEY", "https://platform.minimax.io/docs/api-reference/api-overview", True, OpenWeightStatus.VERIFIED, 0.25),
        model("minimax-direct-m27", "minimax", "MiniMax-M2.7", "https://api.minimax.io/v1/chat/completions", CapabilityLane.AGENTIC_GTM, AccessClass.DIRECT_PAYG, "MINIMAX_API_KEY", "https://platform.minimax.io/docs/api-reference/api-overview", True, OpenWeightStatus.VERIFIED, 0.10),
        model("minimax-direct-m27-highspeed", "minimax", "MiniMax-M2.7-highspeed", "https://api.minimax.io/v1/chat/completions", CapabilityLane.AGENTIC_GTM, AccessClass.DIRECT_PAYG, "MINIMAX_API_KEY", "https://platform.minimax.io/docs/api-reference/api-overview", True, OpenWeightStatus.VERIFIED, 0.20),
        model("minimax-direct-hailuo-23", "minimax", "MiniMax-Hailuo-2.3", "https://api.minimax.io/v1/video_generation", CapabilityLane.VIDEO_GENERATION, AccessClass.DIRECT_PAYG, "MINIMAX_API_KEY", "https://platform.minimax.io/docs/guides/video-generation", True, OpenWeightStatus.NOT_OPEN_WEIGHT, 0.49),
        model("minimax-direct-h3", "minimax", "MiniMax-H3", "https://api.minimax.io/v2/video_generation", CapabilityLane.VIDEO_GENERATION, AccessClass.DIRECT_PAYG, "MINIMAX_API_KEY", "https://platform.minimax.io/docs/api-reference/video-generation-v2-create", True, OpenWeightStatus.UNKNOWN, 10.0),
        model("openrouter-nemotron-3-ultra-free", "openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free", openrouter_endpoint, CapabilityLane.LONG_CONTEXT_CRITIC, AccessClass.ZERO_COST_RATE_LIMITED, "OPENROUTER_API_KEY", openrouter_source, True, OpenWeightStatus.UNKNOWN, 0.0),
        model("openrouter-nemotron-3-super-free", "openrouter", "nvidia/nemotron-3-super-120b-a12b:free", openrouter_endpoint, CapabilityLane.AGENTIC_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "OPENROUTER_API_KEY", openrouter_source, True, OpenWeightStatus.UNKNOWN, 0.0),
        model("openrouter-nemotron-3-nano-free", "openrouter", "nvidia/nemotron-3-nano-30b-a3b:free", openrouter_endpoint, CapabilityLane.AGENTIC_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "OPENROUTER_API_KEY", openrouter_source, True, OpenWeightStatus.UNKNOWN, 0.0),
        model("openrouter-nemotron-3-omni-free", "openrouter", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", openrouter_endpoint, CapabilityLane.MULTIMODAL_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "OPENROUTER_API_KEY", openrouter_source, True, OpenWeightStatus.UNKNOWN, 0.0),
        model("openrouter-nemotron-nano-12b-vl-free", "openrouter", "nvidia/nemotron-nano-12b-v2-vl:free", openrouter_endpoint, CapabilityLane.MULTIMODAL_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "OPENROUTER_API_KEY", openrouter_source, True, OpenWeightStatus.UNKNOWN, 0.0),
        model("openrouter-nemotron-nano-9b-free", "openrouter", "nvidia/nemotron-nano-9b-v2:free", openrouter_endpoint, CapabilityLane.AGENTIC_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "OPENROUTER_API_KEY", openrouter_source, True, OpenWeightStatus.UNKNOWN, 0.0),
        model("openrouter-gemma-4-26b-free", "openrouter", "google/gemma-4-26b-a4b-it:free", openrouter_endpoint, CapabilityLane.MULTIMODAL_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "OPENROUTER_API_KEY", openrouter_source, True, OpenWeightStatus.VERIFIED, 0.0),
        model("openrouter-gemma-4-31b-free", "openrouter", "google/gemma-4-31b-it:free", openrouter_endpoint, CapabilityLane.MULTIMODAL_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "OPENROUTER_API_KEY", openrouter_source, True, OpenWeightStatus.VERIFIED, 0.0),
        model("openrouter-ling-3-flash-free", "openrouter", "inclusionai/ling-3.0-flash:free", openrouter_endpoint, CapabilityLane.AGENTIC_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "OPENROUTER_API_KEY", openrouter_source, True, OpenWeightStatus.UNKNOWN, 0.0),
        model("openrouter-gpt-oss-20b-free", "openrouter", "openai/gpt-oss-20b:free", openrouter_endpoint, CapabilityLane.AGENTIC_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "OPENROUTER_API_KEY", openrouter_source, True, OpenWeightStatus.VERIFIED, 0.0),
        model("openrouter-poolside-laguna-free", "openrouter", "poolside/laguna-s-2.1:free", openrouter_endpoint, CapabilityLane.AGENTIC_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "OPENROUTER_API_KEY", openrouter_source, True, OpenWeightStatus.UNKNOWN, 0.0),
        model("openrouter-nemotron-safety-free", "openrouter", "nvidia/nemotron-3.5-content-safety:free", openrouter_endpoint, CapabilityLane.SAFETY_CRITIC, AccessClass.ZERO_COST_RATE_LIMITED, "OPENROUTER_API_KEY", openrouter_source, True, OpenWeightStatus.UNKNOWN, 0.0),
        model("openrouter-dynamic-free", "openrouter", "openrouter/free", openrouter_endpoint, CapabilityLane.AGENTIC_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "OPENROUTER_API_KEY", "https://openrouter.ai/docs/guides/routing/routers/free-router", True, OpenWeightStatus.UNKNOWN, 0.0),
        model("groq-gpt-oss-120b-free", "groq", "openai/gpt-oss-120b", groq_endpoint, CapabilityLane.AGENTIC_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "GROQ_API_KEY", groq_source, True, OpenWeightStatus.VERIFIED, 0.0),
        model("groq-gpt-oss-20b-free", "groq", "openai/gpt-oss-20b", groq_endpoint, CapabilityLane.AGENTIC_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "GROQ_API_KEY", groq_source, True, OpenWeightStatus.VERIFIED, 0.0),
        model("groq-qwen3p6-27b-free", "groq", "qwen/qwen3.6-27b", groq_endpoint, CapabilityLane.AGENTIC_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "GROQ_API_KEY", groq_source, True, OpenWeightStatus.VERIFIED, 0.0),
        model("groq-compound-free", "groq", "groq/compound", groq_endpoint, CapabilityLane.AGENTIC_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "GROQ_API_KEY", groq_source, True, OpenWeightStatus.UNKNOWN, 0.0),
        model("nvidia-deepseek-v4-pro-free", "nvidia_nim", "deepseek-ai/deepseek-v4-pro", nvidia_endpoint, CapabilityLane.LONG_CONTEXT_CRITIC, AccessClass.ZERO_COST_RATE_LIMITED, "NVIDIA_API_KEY", nvidia_source, True, OpenWeightStatus.VERIFIED, 0.0),
        model("nvidia-nemotron-3-ultra-free", "nvidia_nim", "nvidia/nemotron-3-ultra-550b-a55b", nvidia_endpoint, CapabilityLane.AGENTIC_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "NVIDIA_API_KEY", nvidia_source, True, OpenWeightStatus.VERIFIED, 0.0),
        model("nvidia-kimi-k26-free", "nvidia_nim", "moonshotai/kimi-k2.6", nvidia_endpoint, CapabilityLane.MULTIMODAL_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "NVIDIA_API_KEY", nvidia_source, True, OpenWeightStatus.VERIFIED, 0.0),
        model("nvidia-diffusiongemma-26b-free", "nvidia_nim", "google/diffusiongemma-26b-a4b-it", nvidia_endpoint, CapabilityLane.MULTIMODAL_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "NVIDIA_API_KEY", "https://build.nvidia.com/google/diffusiongemma-26b-a4b-it", True, OpenWeightStatus.VERIFIED, 0.0),
        model("sambanova-deepseek-v31-free", "sambanova", "DeepSeek-V3.1", sambanova_endpoint, CapabilityLane.AGENTIC_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "SAMBANOVA_API_KEY", sambanova_source, True, OpenWeightStatus.VERIFIED, 0.0),
        model("sambanova-gpt-oss-120b-free", "sambanova", "gpt-oss-120b", sambanova_endpoint, CapabilityLane.AGENTIC_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "SAMBANOVA_API_KEY", sambanova_source, True, OpenWeightStatus.VERIFIED, 0.0),
        model("sambanova-deepseek-v32-preview-free", "sambanova", "DeepSeek-V3.2", sambanova_endpoint, CapabilityLane.LONG_CONTEXT_CRITIC, AccessClass.ZERO_COST_RATE_LIMITED, "SAMBANOVA_API_KEY", sambanova_source, True, OpenWeightStatus.VERIFIED, 0.0),
        model("sambanova-gemma-4-31b-preview-free", "sambanova", "gemma-4-31B-it", sambanova_endpoint, CapabilityLane.MULTIMODAL_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "SAMBANOVA_API_KEY", sambanova_source, True, OpenWeightStatus.VERIFIED, 0.0),
        model("mistral-large-latest-free-mode", "mistral", "mistral-large-latest", mistral_endpoint, CapabilityLane.AGENTIC_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "MISTRAL_API_KEY", mistral_source, True, OpenWeightStatus.NOT_OPEN_WEIGHT, 0.0),
        model("gemini-35-flash-free-tier", "google_ai_studio", "gemini-3.5-flash", gemini_endpoint, CapabilityLane.MULTIMODAL_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "GEMINI_API_KEY", gemini_source, True, OpenWeightStatus.NOT_OPEN_WEIGHT, 0.0),
        model("cloudflare-gpt-oss-120b-free-allocation", "cloudflare_workers_ai", "@cf/openai/gpt-oss-120b", cloudflare_endpoint, CapabilityLane.AGENTIC_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "CLOUDFLARE_API_TOKEN", cloudflare_source, True, OpenWeightStatus.VERIFIED, 0.0),
        model("cloudflare-gemma-4-26b-free-allocation", "cloudflare_workers_ai", "@cf/google/gemma-4-26b-a4b-it", cloudflare_endpoint, CapabilityLane.MULTIMODAL_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "CLOUDFLARE_API_TOKEN", cloudflare_source, True, OpenWeightStatus.VERIFIED, 0.0),
        model("cerebras-gpt-oss-120b-trial-credit", "cerebras", "gpt-oss-120b", cerebras_endpoint, CapabilityLane.AGENTIC_GTM, AccessClass.DEVELOPER_CREDITS, "CEREBRAS_API_KEY", cerebras_source, True, OpenWeightStatus.VERIFIED, 0.10),
        model("cerebras-zai-glm-47-trial-credit", "cerebras", "zai-glm-4.7", cerebras_endpoint, CapabilityLane.LONG_CONTEXT_CRITIC, AccessClass.DEVELOPER_CREDITS, "CEREBRAS_API_KEY", cerebras_source, True, OpenWeightStatus.VERIFIED, 0.10),
        model("lightning-nemotron-3-ultra-free", "lightning_model_api", "lightning-ai/nvidia-nemotron-3-ultra-550b-a55b", lightning_endpoint, CapabilityLane.LONG_CONTEXT_CRITIC, AccessClass.ZERO_COST_RATE_LIMITED, "LIGHTNING_API_KEY", lightning_source, True, OpenWeightStatus.VERIFIED, 0.0),
        model("cohere-command-a-plus-evaluation", "cohere", "command-a-plus-05-2026", cohere_endpoint, CapabilityLane.AGENTIC_GTM, AccessClass.ZERO_COST_RATE_LIMITED, "COHERE_API_KEY", cohere_source, True, OpenWeightStatus.NOT_OPEN_WEIGHT, 0.0),
        model("huggingface-gpt-oss-120b-monthly-credit", "huggingface_inference_providers", "openai/gpt-oss-120b", huggingface_endpoint, CapabilityLane.AGENTIC_GTM, AccessClass.DEVELOPER_CREDITS, "HF_TOKEN", huggingface_source, True, OpenWeightStatus.VERIFIED, 0.10),
        model("dashscope-qwen37-max-new-user-credit", "alibaba_model_studio", "qwen3.7-max", dashscope_endpoint, CapabilityLane.LONG_CONTEXT_CRITIC, AccessClass.DEVELOPER_CREDITS, "DASHSCOPE_API_KEY", dashscope_source, True, OpenWeightStatus.NOT_OPEN_WEIGHT, 0.10),
    )


def main() -> int:
    roster = candidates()
    credential_state = {
        name: bool(os.environ.get(name, "").strip())
        for name in sorted({item.api_key_env for item in roster})
    }
    admitted = admitted_candidates(roster, credential_env_present=credential_state)
    free_roster = tuple(
        item for item in roster
        if item.access_class is AccessClass.ZERO_COST_RATE_LIMITED
    )
    qualification_roster = tuple(
        item
        for item in free_roster
        if item.candidate_id
        not in {"openrouter-dynamic-free", "openrouter-poolside-laguna-free"}
    )
    free_request_ceiling = request_ceiling(len(qualification_roster))
    if free_request_ceiling > 50:
        raise RuntimeError("free API panel exceeds the documented 50 request/day ceiling")
    video_probe = MiniMaxVideoRequest(
        "Five-second evidence-led GTM product film; preserve exact brand identity and show the approval gate.",
        duration_seconds=5,
    )
    contract = {
        "schema": "ProofLaunchFrontierApiPanelV1",
        "observed_at": "2026-08-02",
        "selection_policy": {
            "strategy": "successive_halving",
            "reason": "all candidates receive a cheap same-input qualification; only verified winners consume final-stage quota",
            "agent_ladder": [asdict(item) for item in DEFAULT_AGENT_LADDER],
            "hard_gates": ["valid_schema", "valid_dependency_graph", "valid_tool_calls", "complete_artifacts", "claim_provenance", "human_release_boundary"],
            "tie_break_order": ["quality", "cost", "latency", "candidate_id"],
            "training_admission_requires_provider_output_rights": True,
            "free_route_daily_request_limit": 50,
            "free_route_request_ceiling": free_request_ceiling,
            "qualification_candidate_ids": [
                item.candidate_id for item in qualification_roster
            ],
            "free_route_data_classes": ["public", "synthetic"],
            "free_route_training_output_admission": "blocked_pending_model-specific-output-rights-review",
            "workload_assignment": {
                "structured_agent_draft": [
                    "groq-gpt-oss-120b-free",
                    "cloudflare-gpt-oss-120b-free-allocation",
                    "cohere-command-a-plus-evaluation",
                    "sambanova-gpt-oss-120b-free",
                ],
                "long_context_red_team": [
                    "openrouter-nemotron-3-ultra-free",
                    "nvidia-nemotron-3-ultra-free",
                    "lightning-nemotron-3-ultra-free",
                    "sambanova-deepseek-v32-preview-free",
                ],
                "multimodal_understanding": [
                    "gemini-35-flash-free-tier",
                    "openrouter-gemma-4-31b-free",
                    "cloudflare-gemma-4-26b-free-allocation",
                    "nvidia-diffusiongemma-26b-free",
                    "nvidia-kimi-k26-free",
                    "sambanova-gemma-4-31b-preview-free",
                ],
                "safety_critic": ["openrouter-nemotron-safety-free"],
                "dynamic_exploration_only": ["openrouter-dynamic-free"],
            },
            "routing_invariants": [
                "local_graph_remains_authoritative",
                "fixed_model_identity_required_for_frozen_promotion",
                "resolved_model_recorded_for_every_dynamic_route",
                "cloud_output_cannot_publish_or_spend",
                "no_confidential_input_on_free_routes",
                "no_training_admission_without_output_rights_review",
            ],
            "groq_free_tier": {
                "models": ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b", "groq/compound"],
                "rpm": 30,
                "rpd": {"language_models": 1_000, "compound": 250},
                "tpm": {"language_models": 8_000, "compound": 70_000},
                "source": "https://console.groq.com/docs/rate-limits",
                "use": "bounded inference qualification only until output-training rights are approved",
            },
            "additional_official_free_routes": {
                "nvidia_nim": {
                    "models": ["deepseek-ai/deepseek-v4-pro", "nvidia/nemotron-3-ultra-550b-a55b", "moonshotai/kimi-k2.6", "google/diffusiongemma-26b-a4b-it"],
                    "source": "https://build.nvidia.com/explore/discover?api-key=true",
                },
                "sambanova": {
                    "models": ["DeepSeek-V3.1", "gpt-oss-120b", "DeepSeek-V3.2", "gemma-4-31B-it"],
                    "free_tier_rpd_per_model": 20,
                    "free_tier_tpd_per_model": 200_000,
                    "source": "https://docs.sambanova.ai/docs/en/models/rate-limits",
                },
                "mistral": {
                    "models": ["mistral-large-latest"],
                    "mode": "free_no_credit_card_rate_limited",
                    "source": "https://docs.mistral.ai/getting-started/quickstarts/studio/activate-and-generate-api-key",
                },
                "google_ai_studio": {
                    "models": ["gemini-3.5-flash"],
                    "mode": "free_tier_rate_limited",
                    "openai_compatible_endpoint": "https://generativelanguage.googleapis.com/v1beta/openai/",
                    "source": "https://ai.google.dev/gemini-api/docs/pricing",
                },
                "cloudflare_workers_ai": {
                    "models": [
                        "@cf/openai/gpt-oss-120b",
                        "@cf/google/gemma-4-26b-a4b-it",
                        "@cf/moonshotai/kimi-k2.7-code",
                        "@cf/zai-org/glm-5.2",
                    ],
                    "free_allocation_neurons_per_day": 10_000,
                    "reset": "00:00 UTC",
                    "openai_compatible": True,
                    "allocation_is_shared_across_models": True,
                    "non_chat_modalities_use_model_specific_endpoints": True,
                    "source": "https://developers.cloudflare.com/workers-ai/platform/pricing/",
                },
                "lightning_model_api": {
                    "models": ["lightning-ai/nvidia-nemotron-3-ultra-550b-a55b"],
                    "mode": "monthly_free_token_allocation",
                    "free_tokens_per_month": 30_000_000,
                    "free_limits": {"rpm": 15, "tpm": 120_000},
                    "openai_compatible_endpoint": "https://lightning.ai/api/v1/",
                    "source": "https://lightning.ai/docs/platform/inference/model-apis",
                    "use": "bounded long-context critique; requires LIGHTNING_FREE_ONLY_ACK=1 and never becomes release authority",
                },
                "cohere": {
                    "models": ["command-a-plus-05-2026"],
                    "mode": "free_evaluation_key_nonproduction",
                    "trial_limits": {"rpm": 20, "calls_per_month": 1_000},
                    "openai_compatible_endpoint": "https://api.cohere.ai/compatibility/v1/",
                    "source": "https://docs.cohere.com/v2/docs/rate-limits",
                    "use": "structured GTM challenger and rubric judge only; never production or release authority",
                },
            },
            "official_developer_credit_routes": {
                "cerebras": {
                    "models": ["gpt-oss-120b", "zai-glm-4.7", "gemma-4-31b"],
                    "trial_credit_usd": 5,
                    "validity_days": 30,
                    "verified_payment_method_required": True,
                    "source": "https://inference-docs.cerebras.ai/support/rate-limits",
                    "safety": "trial only; hard stop at granted credit and never label it a standing free API",
                },
                "huggingface_inference_providers": {
                    "models": ["openai/gpt-oss-120b"],
                    "monthly_credit_usd_free_user": 0.10,
                    "openai_compatible_endpoint": "https://router.huggingface.co/v1/",
                    "source": "https://huggingface.co/docs/inference-providers/en/pricing",
                    "safety": "hard stop at included credit; no automatic paid continuation",
                },
                "alibaba_model_studio": {
                    "models": ["qwen3.7-max"],
                    "scope": "China (Beijing) new-user real-time inference only",
                    "typical_free_quota_tokens_per_model": 1_000_000,
                    "validity_days": 90,
                    "source": "https://help.aliyun.com/en/model-studio/new-free-quota",
                    "safety": "enable Free Quota Only in console before execution; batch, fine-tuning and deployment are excluded",
                },
            },
        },
        "openrouter_catalog_observation": {
            "endpoint": "https://openrouter.ai/api/v1/models",
            "http_status": 200,
            "observed_at": "2026-08-02",
            "catalog_model_count": 455,
            "exact_zero_cost_variant_count": 18,
            "exact_zero_cost_variants_in_panel": 12,
            "dynamic_free_router_in_panel": True,
            "specialist_variants_not_in_chat_qualification": [
                {"model": "fish-audio/s2.1-pro-free:free", "input_modalities": ["text"], "output_modalities": ["speech"], "reason": "speech output requires a modality-specific acceptance and artifact gate"},
                {"model": "nvidia/nemotron-3-embed-1b:free", "input_modalities": ["text"], "output_modalities": ["embeddings"], "reason": "embeddings are not a chat-completions response"},
                {"model": "nvidia/llama-nemotron-rerank-vl-1b-v2:free", "input_modalities": ["text", "image"], "output_modalities": ["rerank"], "reason": "reranking requires a dedicated relevance evaluation contract"},
                {"model": "nvidia/llama-nemotron-embed-vl-1b-v2:free", "input_modalities": ["text", "image"], "output_modalities": ["embeddings"], "reason": "multimodal embeddings require a dedicated retrieval evaluation contract"},
                {"model": "poolside/laguna-xs-2.1:free", "input_modalities": ["text"], "output_modalities": ["text"], "reason": "held outside the frozen 50-request qualification budget as a same-provider fallback"},
                {"model": "cohere/north-mini-code:free", "input_modalities": ["text"], "output_modalities": ["text"], "reason": "held outside the frozen 50-request qualification budget as a specialist coding fallback"},
            ],
            "response_sha256": "85294c5f5f1910ee4a7375fe685f1a9d2ea9c8a9d65454ba48d5a7f5f7e9d9ec",
            "credential_required_for_inference": True,
        },
        "candidates": [
            {
                **asdict(item),
                "lane": item.lane.value,
                "access_class": item.access_class.value,
                "open_weight_status": item.open_weight_status.value,
            }
            for item in roster
        ],
        "minimax_video_same_brief_probe": video_probe.payload(),
        "combined_execution_plan": {
            "objective": "maximize validated quality per zero-cost unit without making cloud availability a product dependency",
            "phase_order": [
                "local_preprocess_deduplicate_and_route",
                "free_api_same_input_qualification",
                "single_winner_teacher_or_critic_pass",
                "single_provider_checkpointed_gpu_training",
                "local_frozen_regression_and_radeon_handoff",
            ],
            "api_roles": {
                "draft_and_schema": ["groq", "cloudflare_workers_ai", "cohere", "sambanova"],
                "long_context_critique": ["lightning_model_api", "nvidia_nim", "openrouter", "sambanova"],
                "multimodal_understanding": ["google_ai_studio", "openrouter", "cloudflare_workers_ai", "nvidia_nim", "sambanova"],
                "safety": ["openrouter"],
            },
            "gpu_priority": [
                "lightning_ai_studios",
                "modelscope_notebook",
                "modal_starter",
                "kaggle_notebooks",
                "google_colab_free",
            ],
            "checkpoint_contract": {
                "restore_before_gpu_start": True,
                "export_before_stop_or_switch": True,
                "required_artifacts": [
                    "adapter_or_checkpoint",
                    "tokenizer_and_config",
                    "optimizer_and_scheduler_when_resumable",
                    "frozen_split_manifest",
                    "metrics",
                    "environment_lock",
                    "sha256_receipt",
                ],
            },
            "anti_waste": [
                "never_download_a_model_already_present_locally",
                "never_split_one_optimizer_state_across_unrelated_ephemeral_providers",
                "never_use_free_api_output_for_training_before_model_specific_rights_review",
                "never_auto_publish_or_spend_from_any_external_model",
                "stop_on_quota_exhaustion_instead_of_falling_through_to_paid_usage",
            ],
        },
        "excluded_route_observations": [
            {
                "provider": "github_models",
                "reason": "GitHub officially retired the playground, catalog, inference API and BYOK service for every customer on 2026-07-30",
                "execution_status": "retired_globally_no_executable_route",
                "source": "https://docs.github.com/en/github-models",
            }
        ],
        "free_compute_matrix": [
            {
                "provider": "kaggle_notebooks",
                "hardware": "NVIDIA Tesla P100",
                "official_free_quota": "30 GPU hours/week or higher depending on demand",
                "fit": "bounded LoRA/SFT experiments with explicit checkpoint export",
                "reliability": "quota and availability vary; never make the product runtime depend on it",
                "source": "https://www.kaggle.com/docs/efficient-gpu-usage",
            },
            {
                "provider": "lightning_ai_studios",
                "hardware": "T4 through H200 subject to free-credit balance and availability",
                "official_free_quota": "15 USD credits/month; current pricing guidance advertises about 80 interruptible GPU hours depending on GPU price and availability",
                "fit": "persistent checkpointed LoRA/SFT workspace; use T4 for duration or high-memory GPU only for a short blocked step",
                "reliability": "identity verification, geography, supply and machine pricing can reduce the realized hours; treat credits rather than hours as authoritative",
                "source": "https://lightning.ai/docs/overview/ai-studio/",
            },
            {
                "provider": "modelscope_notebook",
                "hardware": "NVIDIA A10 with 24 GB VRAM",
                "official_free_quota": "free Notebook allocation after account binding; AMD x ModelScope developer program can grant additional GPU-hour awards",
                "fit": "persistent ModelScope-native LoRA/SFT with 100 GB mounted workspace and direct reuse of ModelScope models and datasets",
                "reliability": "account binding, activity eligibility, review and current capacity govern the realized allocation",
                "source": "https://www.modelscope.cn/learn/434591",
                "additional_quota_source": "https://modelscope.cn/events/247",
            },
            {
                "provider": "modal_starter",
                "hardware": "serverless T4/L4/A10/L40S/RTX Pro 6000/A100/H100/H200/B200/B300",
                "official_free_quota": "30 USD compute credit/month on Starter",
                "fit": "parallel evaluation, teacher generation and resumable batch training with content-addressed volumes",
                "reliability": "credit-denominated rather than guaranteed hours; GPU choice determines duration",
                "source": "https://modal.com/pricing",
            },
            {
                "provider": "google_colab_free",
                "hardware": "dynamic GPU or TPU",
                "official_free_quota": "free-of-charge but not guaranteed, not unlimited, and fluctuating",
                "fit": "short reproducibility probes only",
                "reliability": "no fixed accelerator, duration, or quota claim",
                "source": "https://research.google.com/colaboratory/faq.html",
            },
            {
                "provider": "huggingface_zerogpu",
                "hardware": "48GB or 96GB NVIDIA RTX Pro 6000 Blackwell allocation",
                "official_free_quota": "5 minutes/day for a free account; hosting limited to eligible Gradio Spaces",
                "fit": "short inference/demo kernels, not sustained training",
                "reliability": "shared queue and daily quota",
                "source": "https://huggingface.co/docs/hub/main/en/spaces-zerogpu",
            },
            {
                "provider": "nvidia_launchpad",
                "hardware": "NVIDIA enterprise lab infrastructure",
                "official_free_quota": "free guided hands-on labs or development sandbox subject to program availability",
                "fit": "NIM evaluation and reproducibility lab",
                "reliability": "not represented as unrestricted persistent GPU rental",
                "source": "https://docs.api.nvidia.com/nim/docs/deployment",
            },
            {
                "provider": "amazon_sagemaker_studio_lab_existing_accounts",
                "hardware": "dynamic GPU compute type with 15 GB persistent storage and 16 GB RAM",
                "official_free_quota": "up to 4 GPU hours per 24 hours in sessions up to 4 hours",
                "fit": "checkpointed notebook training only for an account that already existed before the access cutoff",
                "reliability": "new customer access closed on 2026-07-30; compute availability is not guaranteed",
                "source": "https://docs.aws.amazon.com/sagemaker/latest/dg/studio-lab-overview.html",
            },
        ],
        "unresolved_model_claims": [],
        "truth_boundary": (
            "Sponsored quota, developer credits, pay-as-you-go API access and open weights are distinct. "
            "No external candidate is competition-core eligible, and API outputs cannot prove local Radeon execution or training."
        ),
    }
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(CONFIG, json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    preflight = {
        "schema": "ProofLaunchFrontierApiPanelPreflightV1",
        "observed_at": "2026-08-02",
        "contract_sha256": sha256_file(CONFIG),
        "credential_environment_present": credential_state,
        "admitted_candidate_ids": [item.candidate_id for item in admitted],
        "admitted_count": len(admitted),
        "live_calls_executed": 0,
        "existing_real_amd_benchmark": "evidence/v10/agentic-gtm-flagship-benchmark-2026-07-31.json",
        "existing_amd_teacher_corpus": "data/tokenfactory_teacher_v10",
        "existing_teacher_corpus_validation": "evidence/v10/tokenfactory-corpus-validation.json",
        "latest_deepseek_identity": "DeepSeek-V4-Flash-0731 via API id deepseek-v4-flash / Token Factory id DeepSeek-V4-Flash",
        "minimax_m3_role": "official direct multimodal Agent API plus separately verified official open weights; direct API remains pay-as-you-go",
        "minimax_direct_text_role": "MiniMax-M3, MiniMax-M2.7 and MiniMax-M2.7-highspeed are official OpenAI-compatible text/tool-call routes",
        "minimax_video_role": "MiniMax-H3 official asynchronous multimodal 2K 4-15 second video generation; Hailuo 2.3 remains a separate legacy-compatible lane",
        "minimax_h3_identity_status": "verified_in_official_api_catalog_and_admitted_as_direct_payg",
        "deepseek_direct_api_free_claim": False,
        "minimax_direct_api_free_claim": False,
        "verified_zero_cost_providers": [
            "OpenRouter :free variants and openrouter/free router",
            "Groq Free Plan",
            "NVIDIA NIM free serverless development endpoints",
            "SambaNova Free Tier",
            "Mistral Studio Free mode",
            "Google AI Studio Gemini API Free Tier",
            "Cloudflare Workers AI daily free allocation",
            "Lightning Model APIs monthly free-token allocation",
            "Cohere free evaluation key",
        ],
        "verified_developer_credit_providers": [
            "Cerebras 30-day payment-method-backed trial credit",
            "Hugging Face Inference Providers monthly free-user credit",
            "Alibaba Cloud Model Studio new-user real-time inference quota",
        ],
        "free_candidate_count": len(free_roster),
        "free_qualification_candidate_count": len(qualification_roster),
        "free_panel_request_ceiling": free_request_ceiling,
        "free_panel_daily_limit": 50,
        "free_panel_live_call_status": (
            "ready_for_public_or_synthetic_qualification"
            if any(
                credential_state.get(name, False)
                for name in (
                    "OPENROUTER_API_KEY",
                    "GROQ_API_KEY",
                    "NVIDIA_API_KEY",
                    "SAMBANOVA_API_KEY",
                    "MISTRAL_API_KEY",
                    "GEMINI_API_KEY",
                    "CLOUDFLARE_API_TOKEN",
                    "CEREBRAS_API_KEY",
                    "LIGHTNING_API_KEY",
                    "COHERE_API_KEY",
                )
            )
            else "blocked_missing_all_verified_free_route_credentials"
        ),
        "direct_api_cost_sources": [
            "https://api-docs.deepseek.com/quick_start/pricing/",
            "https://platform.minimax.io/docs/pricing/overview",
        ],
        "status": "ready_no_credentials" if not admitted else "ready_for_bounded_live_qualification",
        "truth_boundary": "Environment-variable presence is recorded only as a boolean; no credential, prompt, or output is persisted here.",
        "content_sha256": stable_sha256({"roster": [item.candidate_id for item in roster], "credential_state": credential_state}),
    }
    atomic_write_text(EVIDENCE, json.dumps(preflight, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"candidates": len(roster), "admitted": len(admitted), "contract_sha256": sha256_file(CONFIG), "preflight_sha256": sha256_file(EVIDENCE)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
