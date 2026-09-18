"""Environment-backed runtime configuration."""

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    model_mode: str = "mock"
    model_base_url: str = ""
    model_api_key: str = ""
    model_name: str = "mock-radeon-sentinel"
    database_path: Path = Path("artifacts/sentinel.db")
    runbook_dir: Path = Path("demo_data/runbooks")
    incident_dir: Path = Path("demo_data/incidents")
    request_timeout_seconds: int = 60

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls(
            model_mode=os.getenv("SENTINEL_MODEL_MODE", "mock").strip().lower(),
            model_base_url=os.getenv("MODEL_BASE_URL", "").strip(),
            model_api_key=os.getenv("MODEL_API_KEY", "").strip(),
            model_name=os.getenv(
                "MODEL_NAME", "mock-radeon-sentinel"
            ).strip(),
            database_path=Path(
                os.getenv("SENTINEL_DB_PATH", "artifacts/sentinel.db")
            ),
            runbook_dir=Path(
                os.getenv("SENTINEL_RUNBOOK_DIR", "demo_data/runbooks")
            ),
            incident_dir=Path(
                os.getenv("SENTINEL_INCIDENT_DIR", "demo_data/incidents")
            ),
            request_timeout_seconds=int(
                os.getenv("SENTINEL_REQUEST_TIMEOUT_SECONDS", "60")
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.model_mode not in {"mock", "openai"}:
            raise ValueError(
                "SENTINEL_MODEL_MODE must be either 'mock' or 'openai'"
            )
        if self.model_mode == "openai":
            if not self.model_base_url:
                raise ValueError("MODEL_BASE_URL is required in openai mode")
            if not self.model_name:
                raise ValueError("MODEL_NAME is required in openai mode")
        if self.request_timeout_seconds < 1:
            raise ValueError(
                "SENTINEL_REQUEST_TIMEOUT_SECONDS must be positive"
            )
