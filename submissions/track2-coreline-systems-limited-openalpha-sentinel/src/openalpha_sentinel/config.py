from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    host: str = "127.0.0.1"
    port: int = 8765
    offline: bool = False
    allowed_domains: tuple[str, ...] = ()
    llm_backend: str = "auto"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "mistral:latest"
    llama_url: str = "http://127.0.0.1:8080/v1"
    llama_model: str = "qwen3-8b"
    github_token: str | None = None
    user_agent: str = "OpenAlpha-Sentinel/0.1"
    max_document_bytes: int = 2_000_000
    worker_poll_seconds: int = 15

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.getenv("OPENALPHA_DATA_DIR", "./data/runtime")).expanduser().resolve()
        allowed = tuple(
            item.strip().lower()
            for item in os.getenv(
                "OPENALPHA_ALLOWED_DOMAINS",
                "api.github.com,github.com,raw.githubusercontent.com",
            ).split(",")
            if item.strip()
        )
        return cls(
            data_dir=data_dir,
            db_path=data_dir / "openalpha.db",
            host=os.getenv("OPENALPHA_HOST", "127.0.0.1"),
            port=int(os.getenv("OPENALPHA_PORT", "8765")),
            offline=_bool_env("OPENALPHA_OFFLINE"),
            allowed_domains=allowed,
            llm_backend=os.getenv("OPENALPHA_LLM_BACKEND", "auto").strip().lower(),
            ollama_url=os.getenv("OPENALPHA_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
            ollama_model=os.getenv("OPENALPHA_OLLAMA_MODEL", "mistral:latest"),
            llama_url=os.getenv("OPENALPHA_LLAMA_URL", "http://127.0.0.1:8080/v1").rstrip("/"),
            llama_model=os.getenv("OPENALPHA_LLAMA_MODEL", "qwen3-8b"),
            github_token=os.getenv("GITHUB_TOKEN") or None,
            user_agent=os.getenv("OPENALPHA_USER_AGENT", "OpenAlpha-Sentinel/0.1"),
            max_document_bytes=int(os.getenv("OPENALPHA_MAX_DOCUMENT_BYTES", "2000000")),
            worker_poll_seconds=int(os.getenv("OPENALPHA_WORKER_POLL_SECONDS", "15")),
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "raw").mkdir(exist_ok=True)
        (self.data_dir / "exports").mkdir(exist_ok=True)
