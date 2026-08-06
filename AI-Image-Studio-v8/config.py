# -*- coding: utf-8 -*-
"""AI-Image-Studio v2 (Radeon Edition) — global configuration.

v2 rebuild: SDXL-based pipelines only. Every knob can be overridden via
environment variables.
"""
from __future__ import annotations

import os
from pathlib import Path


def _flag(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


class Settings:
    # ---------------------------------------------------------- models
    # SDXL base (txt2img / img2img style transfer) — fp16 variant
    sdxl_model_id: str = os.environ.get(
        "AISTUDIO_SDXL_ID", "stabilityai/stable-diffusion-xl-base-1.0")
    # SDXL inpainting (inpaint / outpaint / remove fallback / split fill)
    sdxl_inpaint_id: str = os.environ.get(
        "AISTUDIO_SDXL_INPAINT_ID", "diffusers/stable-diffusion-xl-1.0-inpainting-0.1")
    # ControlNet Canny for structure-locked style transfer
    controlnet_id: str = os.environ.get(
        "AISTUDIO_CONTROLNET_ID", "diffusers/controlnet-canny-sdxl-1.0")
    # BiRefNet matting (background / split)
    birefnet_model_id: str = os.environ.get(
        "AISTUDIO_BIREFNET_ID", "ZhengPeng7/BiRefNet")
    # LCM-LoRA (SDXL) — turbo mode: 30 steps → 6~8 steps
    lcm_lora_id: str = os.environ.get(
        "AISTUDIO_LCM_LORA_ID", "latent-consistency/lcm-lora-sdxl")
    enable_lcm: bool = _flag(os.environ.get("AISTUDIO_ENABLE_LCM", "1"))
    lcm_steps: int = int(os.environ.get("AISTUDIO_LCM_STEPS", "8"))
    lcm_guidance: float = float(os.environ.get("AISTUDIO_LCM_GUIDANCE", "1.5"))
    # Repaint (masked garment/design swaps) needs real denoise depth even in
    # turbo mode — 8 LCM steps at strength .85 leaves the edit half-done.
    lcm_repaint_steps: int = int(os.environ.get("AISTUDIO_LCM_REPAINT_STEPS", "16"))
    # Startup warmup: pre-run tiny inferences through every engine path at the
    # canonical bucket shapes so the first user click doesn't pay the MIOpen
    # autotune stall (~6 min per unseen shape on ROCm).
    enable_warmup: bool = _flag(os.environ.get("AISTUDIO_ENABLE_WARMUP", "1"))

    # LaMa (remove / split fill): local file first, never hits the network
    lama_model_path: str = os.environ.get(
        "LAMA_MODEL", os.environ.get("AISTUDIO_LAMA_PATH", "models/big-lama.pt"))
    # Split background fill: how far beyond the matte the erase mask grows.
    # 6px left a visible human silhouette; ~28px eats the halo too.
    split_fill_dilate: int = int(os.environ.get("AISTUDIO_SPLIT_DILATE", "28"))

    # --------------------------------------------------- intent layer (LLM)
    # Small local instruction parser: rewrites free-form user text into
    # structured pipeline params. Rule-based fallback if unavailable.
    enable_intent_llm: bool = _flag(os.environ.get("AISTUDIO_ENABLE_INTENT", "1"))
    intent_model_id: str = os.environ.get(
        "AISTUDIO_INTENT_ID", "Qwen/Qwen2.5-1.5B-Instruct")
    intent_max_tokens: int = int(os.environ.get("AISTUDIO_INTENT_MAX_TOKENS", "260"))

    # -------------------------------------------------------- runtime
    device: str = os.environ.get("AISTUDIO_DEVICE", "auto")      # auto|cuda|cpu
    dtype: str = os.environ.get("AISTUDIO_DTYPE", "auto")        # auto|fp16|bf16|fp32
    low_vram: bool = _flag(os.environ.get("AISTUDIO_LOW_VRAM", "0"))

    # Working resolution (long edge) for SDXL pipelines. SDXL is native at 1024.
    max_working_size: int = int(os.environ.get("AISTUDIO_MAX_WORKING", "1024"))
    # BiRefNet matting resolution (square). Lower it on low-RAM CPU boxes.
    matte_size: int = int(os.environ.get("AISTUDIO_MATTE_SIZE", "1024"))
    # Inpaint crop target (long edge of the masked-region crop)
    inpaint_crop_size: int = int(os.environ.get("AISTUDIO_INPAINT_CROP", "1024"))

    # ---------------------------------------------------------- server
    server_name: str = os.environ.get("AISTUDIO_HOST", "0.0.0.0")
    server_port: int = int(os.environ.get("AISTUDIO_PORT", "7860"))
    share: bool = _flag(os.environ.get("AISTUDIO_SHARE", "0"))

    output_dir: Path = Path(os.environ.get("AISTUDIO_OUTPUT_DIR", "outputs"))


settings = Settings()
settings.output_dir.mkdir(parents=True, exist_ok=True)
