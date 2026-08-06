from __future__ import annotations

from pathlib import Path

from src.paths import MODELS


def local_llm_dir() -> Path:
    return MODELS / "llm"


def local_image_dir() -> Path:
    return MODELS / "image"


def has_local_llm() -> bool:
    """True if a usable LLM checkpoint exists under models/llm."""
    d = local_llm_dir()
    return (d / "config.json").exists() or (d / "model.safetensors").exists()


def has_local_image() -> bool:
    """True if a usable diffusers checkpoint exists under models/image."""
    d = local_image_dir()
    return (d / "model_index.json").exists()
