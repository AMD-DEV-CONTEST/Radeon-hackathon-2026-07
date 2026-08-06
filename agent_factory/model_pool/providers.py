from __future__ import annotations

from typing import Any

from agent_factory.model_pool.schema import DEFAULT_LLAMA_CPP_PARALLEL_SLOTS



def list_local_inference_engines() -> list[dict[str, Any]]:
    return [
        {
            "engine": "llama_cpp_rocm",
            "display_name": "llama.cpp on AMD ROCm",
            "kind": "chat",
            "transport": "local_llama_cpp",
            "parameters": {
                "gpu_layers": {"default": 99, "min": 0},
                "parallel_slots": {
                    "default": DEFAULT_LLAMA_CPP_PARALLEL_SLOTS,
                    "min": 1,
                },
                "cache_types": ["f16", "bf16", "q8_0", "q4_0"],
                "speculative_decoding_methods": ["mtp"],
            },
        },
        {
            "engine": "transformers_rocm",
            "display_name": "Transformers on AMD ROCm",
            "kind": "embedding",
            "transport": "in_process",
            "parameters": {},
        },
        {
            "engine": "stable_diffusion_cpp_rocm",
            "display_name": "stable-diffusion.cpp on AMD ROCm",
            "kind": "image_generation",
            "transport": "openai_compatible_images",
            "parameters": {
                "batch_count": {"default": 1, "min": 1, "max": 1},
                "diffusion_flash_attention": {"default": True},
                "clip_on_cpu": {"default": True},
            },
        },
        {
            "engine": "external",
            "display_name": "External inference endpoint",
            "kind": "chat",
            "transport": "openai_compatible",
            "parameters": {},
        },
    ]
