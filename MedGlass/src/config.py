"""Central configuration for MedGlass.

All paths, model names, quantization levels and pipeline knobs live here so the
rest of the codebase stays free of magic numbers. Override via environment
variables (prefix MEDGLASS_) or a local config.json.
"""

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ENV_PREFIX = "MEDGLASS_"


def _rocm_vision_available() -> bool:
    """True only if ONNX Runtime actually exposes the ROCm EP here.

    Ubuntu's native ROCm lacks the ROCm Tracer (roctracer) shared library, so
    onnxruntime-rocm installs but never registers its provider; requesting it
    just makes ORT warn and fall back to CPU. Detect the real state instead of
    assuming.
    """
    try:
        import onnxruntime as ort
        return "ROCMExecutionProvider" in ort.get_available_providers()
    except Exception:
        return False


VISION_ROCM = _rocm_vision_available()

DEFAULTS = {
    # Server
    "host": "0.0.0.0",
    "port": 8100,

    # Audio
    "sample_rate": 16000,
    "chunk_seconds": 5.0,
    "overlap_seconds": 1.0,
    "whisper_min_gap_seconds": 1.0,
    "whisper_threads": 8,
    "whisper_beam_size": 3,

    # Whisper.cpp subprocess
    "whisper_backend": "auto",          # auto | cli | pywhispercpp
    "whisper_bin": str(ROOT / "vendor/whisper.cpp/build/bin/whisper-cli"),
    "whisper_model": str(ROOT / "models/ggml-small.en.bin"),
    "whisper_lang": "en",
    "whisper_hipblas": True,

    # Vision
    "video_fps": 5,
    "yolo_model": str(ROOT / "models/yolov8n-seg.onnx"),
    "yolo_rocm": VISION_ROCM,
    "yolo_conf": 0.35,
    "ocr_rocm": VISION_ROCM,
    "ocr_cpu": True,
    "ocr_languages": ["en"],

    # LLM (llama.cpp subprocess)
    "llm_backend": "cli",           # auto | ollama | cli | template
    "llama_bin": str(ROOT / "vendor/llama.cpp/build/bin/llama-cli"),
    "llama_model": str(ROOT / "models/qwen3.6-27b-q4_k_m.gguf"),
    "llama_n_gpu_layers": 999,
    "llama_ctx": 8192,
    "llama_threads": 8,
    "llama_max_tokens": 2048,
    "llama_temperature": 0.2,

    # Local Ollama LLM (preferred: no cloud, no GGUF download)
    "ollama_url": "http://localhost:11434",
    "ollama_model": "qwen3.6:27b",
    "ollama_num_ctx": 8192,
    "ollama_num_predict": 2048,

    # OpenRouter remote LLM (cloud inference via OpenAI-compatible API)
    "openrouter_api_key": os.environ.get("MEDGLASS_OPENROUTER_API_KEY",
                                         os.environ.get("OPENROUTER_API_KEY", "")),
    "openrouter_model": "~openai/gpt-latest",
    "openrouter_referer": "http://localhost:8100",  # Optional. Site URL for rankings.
    "openrouter_title": "MedGlass",                 # Optional. Ranking title.

    # Memory budget (GB) to decide which models run concurrently on one GPU
    "memory_budget_gb": 8.0,
    "whisper_vram_gb": 1.5,
    "yolo_vram_gb": 0.5,
    "llm_vram_gb": 4.5,

    # HUD
    "hud_endpoint": os.environ.get("MEDGLASS_HUD_ENDPOINT", ""),

    # Dashboard access token (optional). When set, /dashboard and /notes
    # require `?token=` or `X-Dashboard-Token` to view patient data from a
    # phone / remote browser. Leave empty for open localhost access.
    "dashboard_token": os.environ.get("MEDGLASS_DASHBOARD_TOKEN", ""),

    # PHI sanitization
    "strip_phi_on_store": True,

    # Browser UI login (notes dashboard is the default page). Override via
    # MEDGLASS_LOGIN_USER / MEDGLASS_LOGIN_PASSWORD. No default password is
    # baked in: when the users store is empty and none is configured, the
    # server generates a one-time password and logs it at startup.
    "login_user": os.environ.get("MEDGLASS_LOGIN_USER", "clinician"),
    "login_password": os.environ.get("MEDGLASS_LOGIN_PASSWORD", ""),

    # -------- security (HIPAA hardening) --------
    # scrypt password hashing + per-user accounts (output/users.json).
    "users_file": str(ROOT / "output" / "users.json"),
    "max_login_attempts": 10,         # lock after this many failures
    "lock_minutes": 15,               # lock duration after repeated failures
    "session_idle_minutes": 60,       # idle timeout per session
    "audit_log": str(ROOT / "output" / "audit.log"),
    # AES-GCM encryption at rest for notes + photos (key in output/.keys/).
    "encrypt_at_rest": False,
    # Delete notes (and their photos/tasks) older than N days; 0 = disabled.
    "retention_days": 0,
    # Comma-separated client IPs allowed through (empty = allow all). The
    # Mentra proxy forwards X-Forwarded-For so the real client is seen here.
    "allowed_ips": "",
}


def _load_env(name: str) -> str | None:
    return os.environ.get(ENV_PREFIX + name)


def _coerce(key: str, value) -> object:
    default = DEFAULTS[key]
    if isinstance(default, bool):
        if isinstance(value, str):
            return value.lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(default, int):
        return int(value)
    if isinstance(default, float):
        return float(value)
    return value


def load_config(path: Path | None = None) -> dict:
    cfg = dict(DEFAULTS)
    cfg_path = Path(path) if path else ROOT / "config.json"
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as fh:
            user = json.load(fh)
        cfg.update(user)
    for key in DEFAULTS:
        env_val = _load_env(key.upper())
        if env_val is not None:
            cfg[key] = _coerce(key, env_val)
    return cfg


def save_config(cfg: dict, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({k: cfg[k] for k in DEFAULTS}, fh, indent=2)


CONFIG = load_config()
