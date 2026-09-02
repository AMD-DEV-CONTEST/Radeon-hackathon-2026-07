"""Application settings for PolicyCut.

Settings are a plain dataclass (contract section 2). Environment variables
provide overrides so `run.py` can configure the server process before the
FastAPI app module is imported:

- ``POLICYCUT_DATA_DIR``       -> Settings.data_dir (default: "data")
- ``POLICYCUT_REQUIRE_ROCM``   -> Settings.require_rocm ("1" => True)

A module-level singleton ``settings`` is created at import time;
``get_settings()`` returns it. ``reload_settings()`` re-reads the
environment (useful in tests).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Settings", "settings", "get_settings", "reload_settings"]


def _env_data_dir() -> Path:
    return Path(os.environ.get("POLICYCUT_DATA_DIR", "data"))


def _env_require_rocm() -> bool:
    return os.environ.get("POLICYCUT_REQUIRE_ROCM", "0") == "1"


def _env_str(name: str, default: str):
    return lambda: os.environ.get(name, default)


def _env_float(name: str, default: float):
    return lambda: float(os.environ.get(name, default))


@dataclass
class Settings:
    """Runtime configuration (contract section 2).

    Model ids and detection intervals accept environment overrides
    (``POLICYCUT_DINO_MODEL``, ``POLICYCUT_QWEN_MODEL``,
    ``POLICYCUT_WHISPER_MODEL``, ``POLICYCUT_SAM2_MODEL``,
    ``POLICYCUT_DINO_INTERVAL``) — used for small-model CPU testing and
    for tuning on the contest machine without code changes.
    """

    data_dir: Path = field(default_factory=_env_data_dir)
    require_rocm: bool = field(default_factory=_env_require_rocm)
    max_video_seconds: float = 60.0
    max_height: int = 1080
    proxy_long_edge: int = 1280
    dino_model: str = field(default_factory=_env_str(
        "POLICYCUT_DINO_MODEL", "IDEA-Research/grounding-dino-tiny"))
    qwen_model: str = field(default_factory=_env_str(
        "POLICYCUT_QWEN_MODEL", "Qwen/Qwen3-4B-Instruct-2507"))
    whisper_model: str = field(default_factory=_env_str(
        "POLICYCUT_WHISPER_MODEL", "openai/whisper-large-v3-turbo"))
    sam2_model: str = field(default_factory=_env_str(
        "POLICYCUT_SAM2_MODEL", "facebook/sam2.1-hiera-small"))
    dino_interval_s: float = field(default_factory=_env_float(
        "POLICYCUT_DINO_INTERVAL", 0.5))
    yunet_interval_s: float = 0.25
    box_threshold: float = 0.25
    text_threshold: float = 0.20
    nms_iou: float = 0.50


# Module-level singleton per contract.
settings = Settings()


def get_settings() -> Settings:
    """Return the module-level Settings singleton."""
    return settings


def reload_settings() -> Settings:
    """Re-read environment overrides into the singleton (test helper)."""
    global settings
    settings = Settings()
    return settings
