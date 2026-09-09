from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .rocm_profile import RadeonDeploymentProfile


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def is_competition_eligible(provider_mode: str, endpoint: str, allow_remote: bool) -> bool:
    if provider_mode != "rocm-local" or allow_remote or not endpoint:
        return False
    return (urlparse(endpoint).hostname or "").lower() in LOOPBACK_HOSTS


def validate_model_endpoint(endpoint: str, allow_remote: bool = False) -> str:
    endpoint = endpoint.strip()
    if not endpoint:
        return ""
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Model endpoint must be an absolute HTTP URL.")
    if not allow_remote and parsed.hostname.lower() not in LOOPBACK_HOSTS:
        raise ValueError("Competition mode requires a loopback model endpoint on the same Radeon instance.")
    return endpoint.rstrip("/")


@dataclass(frozen=True)
class Settings:
    provider_mode: str
    knowledge_dir: Path
    state_dir: Path
    workspace_dir: Path
    model_endpoint: str = ""
    model_name: str = "Qwen/Qwen2.5-7B-Instruct"
    model_api_key: str = ""
    allow_remote_model: bool = False
    request_timeout_seconds: int = 90

    @classmethod
    def from_env(cls) -> "Settings":
        legacy_rocm = os.environ.get("PRIVATEOPS_USE_ROCM_PROVIDER", "").lower() in {"1", "true", "yes"}
        mode = os.environ.get("PRIVATEOPS_PROVIDER_MODE", "rocm-local" if legacy_rocm else "development").strip().lower()
        if mode not in {"development", "rocm-local"}:
            raise ValueError("PRIVATEOPS_PROVIDER_MODE must be development or rocm-local.")
        allow_remote = os.environ.get("PRIVATEOPS_ALLOW_REMOTE_MODEL", "").lower() in {"1", "true", "yes"}
        endpoint = validate_model_endpoint(
            os.environ.get("PRIVATEOPS_MODEL_ENDPOINT", ""),
            allow_remote=allow_remote or mode == "development",
        )
        if mode == "rocm-local" and not endpoint:
            raise ValueError("rocm-local mode requires PRIVATEOPS_MODEL_ENDPOINT.")
        return cls(
            provider_mode=mode,
            knowledge_dir=Path(os.environ.get("PRIVATEOPS_KNOWLEDGE_DIR", "data/knowledge")).resolve(),
            state_dir=Path(os.environ.get("PRIVATEOPS_STATE_DIR", "data/state")).resolve(),
            workspace_dir=Path(os.environ.get("PRIVATEOPS_WORKSPACE_DIR", ".")).resolve(),
            model_endpoint=endpoint,
            model_name=os.environ.get(
                "PRIVATEOPS_MODEL_NAME",
                RadeonDeploymentProfile.competition_default().model_name,
            ),
            model_api_key=os.environ.get("PRIVATEOPS_MODEL_API_KEY", ""),
            allow_remote_model=allow_remote,
            request_timeout_seconds=max(1, int(os.environ.get("PRIVATEOPS_REQUEST_TIMEOUT", "90"))),
        )

    def public_status(self) -> dict[str, object]:
        return {
            "provider_mode": self.provider_mode,
            "workspace": str(self.workspace_dir),
            "knowledge_dir": str(self.knowledge_dir),
            "model_endpoint": self.model_endpoint,
            "model_name": self.model_name,
            "remote_model_allowed": self.allow_remote_model,
            "competition_eligible": is_competition_eligible(
                self.provider_mode,
                self.model_endpoint,
                self.allow_remote_model,
            ),
        }
