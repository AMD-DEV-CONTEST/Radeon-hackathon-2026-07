"""System/health endpoints: GET /health and GET /system."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


def _version() -> str:
    try:
        import policycut

        return getattr(policycut, "__version__", "1.0.0")
    except Exception:  # pragma: no cover
        return "1.0.0"


def _device_info() -> dict:
    try:
        from policycut.core.device import device_info

        return device_info()
    except Exception:
        return {
            "available": False,
            "name": "unknown",
            "torch_version": None,
            "hip_version": None,
            "rocm": False,
        }


def _yunet_ready(settings) -> bool:
    """Best-effort check that the YuNet face detector ONNX file is on disk."""
    candidates: list[Path] = []
    for attr in ("yunet_path", "yunet_model", "yunet_file"):
        value = getattr(settings, attr, None)
        if value:
            candidates.append(Path(value))
    for base in (
        Path(getattr(settings, "data_dir", "data")) / "models",
        Path("models"),
        Path(__file__).resolve().parent.parent / "models",
    ):
        try:
            if base.is_dir():
                candidates.extend(base.glob("*yunet*.onnx"))
        except Exception:
            continue
    for path in candidates:
        try:
            if path.is_file():
                return True
        except Exception:
            continue
    return False


def _model_flags(settings) -> dict:
    """Ready flags per model via a huggingface_hub cache scan (best effort)."""
    ids = {
        "dino": getattr(settings, "dino_model", "IDEA-Research/grounding-dino-tiny"),
        "qwen": getattr(settings, "qwen_model", "Qwen/Qwen3-4B-Instruct-2507"),
        "whisper": getattr(settings, "whisper_model", "openai/whisper-large-v3-turbo"),
        "sam2": getattr(settings, "sam2_model", "facebook/sam2.1-hiera-small"),
    }
    flags = {key: False for key in ids}
    try:
        from huggingface_hub import scan_cache_dir

        cached = {repo.repo_id for repo in scan_cache_dir().repos}
        for key, model_id in ids.items():
            flags[key] = model_id in cached
    except Exception:
        logger.debug("huggingface_hub cache scan unavailable", exc_info=True)
    flags["yunet"] = _yunet_ready(settings)
    return flags


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "version": _version()}


@router.get("/system")
def system_info(request: Request) -> dict:
    settings = request.app.state.settings
    return {
        "gpu": _device_info(),
        "models": _model_flags(settings),
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
    }
