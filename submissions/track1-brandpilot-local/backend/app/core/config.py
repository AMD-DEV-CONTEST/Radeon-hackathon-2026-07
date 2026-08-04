import os
from pathlib import Path

APP_MODE = os.getenv("APP_MODE", "mock")
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE_MB", "10")) * 1024 * 1024
STORAGE_ROOT = Path(os.getenv("STORAGE_ROOT", "storage")).resolve()
CORS_ORIGINS = [item.strip() for item in os.getenv("BACKEND_CORS_ORIGINS", "http://localhost:3000").split(",") if item.strip()]
ALLOWED_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}

VALIDATED_MODEL_ID = "stabilityai/stable-diffusion-xl-base-1.0"
VALIDATED_MODEL_REVISION = "462165984030d82259a11f4367a4eed129e94a7b"


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def experimental_rocm_enabled() -> bool:
    return env_flag("ENABLE_EXPERIMENTAL_ROCM")


def demo_auth_enabled() -> bool:
    return env_flag("DEMO_AUTH_ENABLED")


def rocm_output_root() -> Path:
    configured = os.getenv("ROCM_OUTPUT_DIR", "").strip()
    return Path(configured).expanduser().resolve() if configured else STORAGE_ROOT / "rocm-outputs"


def validate_experimental_configuration() -> None:
    if int(os.getenv("EXPERIMENTAL_MAX_ACTIVE_JOBS", "1")) != 1:
        raise RuntimeError("EXPERIMENTAL_MAX_ACTIVE_JOBS must remain 1.")
    if demo_auth_enabled() and len(os.getenv("DEMO_AUTH_TOKEN", "")) < 32:
        raise RuntimeError("Demo authentication requires an ephemeral token of at least 32 bytes.")
    configured_origins = [
        item.strip()
        for item in os.getenv("BACKEND_CORS_ORIGINS", "http://localhost:3000").split(",")
        if item.strip()
    ]
    if demo_auth_enabled() and "*" in configured_origins:
        raise RuntimeError("Authenticated demo mode requires explicit CORS origins.")
