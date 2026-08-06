from __future__ import annotations


CONTRACT_VERSION = "beaver-external-inference-v1"

OBJECT_DETECTION_PATH = "/v1/detections"
FACE_RECOGNITION_PATH = "/v1/faces/recognize"
VOICE_ANALYSIS_PATH = "/v1/voices/analyze"
HEALTH_PATH = "/health"
MODELS_PATH = "/v1/models"

DEFAULT_MAX_IMAGE_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_AUDIO_BYTES = 32 * 1024 * 1024


def service_root_url(base_url: str) -> str:
    """Accept either a service root or an OpenAI-style URL ending in /v1."""
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        normalized = normalized[:-3]
    return normalized
