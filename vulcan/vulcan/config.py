"""Runtime configuration.

Everything speaks to one OpenAI-compatible endpoint, so the same code runs
against Ollama on a laptop and vLLM on a ROCm box. Only the env changes.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    base_url: str = field(default_factory=lambda: os.getenv("VULCAN_BASE_URL", "http://localhost:11434/v1"))
    api_key: str = field(default_factory=lambda: os.getenv("VULCAN_API_KEY", "local"))
    model: str = field(default_factory=lambda: os.getenv("VULCAN_MODEL", "qwen3:4b-instruct"))
    embed_model: str = field(default_factory=lambda: os.getenv("VULCAN_EMBED_MODEL", "mxbai-embed-large"))
    # Embeddings can live on a different server than chat. A vLLM instance
    # started with task=generate serves no /v1/embeddings route at all, and
    # Radeon Cloud allows one active instance, so the working split is
    # generation on the GPU and embeddings on a local model. Defaults to
    # base_url, which keeps single-endpoint setups exactly as they were.
    embed_base_url: str = field(default_factory=lambda: os.getenv("VULCAN_EMBED_BASE_URL", ""))
    embed_api_key: str = field(default_factory=lambda: os.getenv("VULCAN_EMBED_API_KEY", ""))
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("VULCAN_DATA_DIR", "~/.vulcan")).expanduser())
    max_steps: int = int(os.getenv("VULCAN_MAX_STEPS", "12"))
    # Explicit task decomposition, measured and rejected. Neither
    # qwen3:4b-instruct nor qwen3-ws:32k ever emitted a plan when instructed to,
    # so completion was identical (3/4 and 4/4 respectively, both modes) while
    # the instructions cost 18 to 21 seconds of extra wall clock per question.
    # Off by default; VULCAN_PLAN=1 restores it so `vulcan plan-bench`
    # reproduces the result. See bench-results/planning*.json.
    plan: bool = field(default_factory=lambda: os.getenv("VULCAN_PLAN", "0") not in ("0", "false", "no"))
    temperature: float = float(os.getenv("VULCAN_TEMPERATURE", "0.2"))
    # Unset means "send nothing", because backends that don't understand
    # chat_template_kwargs reject the request outright. Set it only against
    # vLLM serving a Qwen3 model: "false" there cuts agent-step latency ~3.5x.
    enable_thinking: bool | None = field(
        default_factory=lambda: {"true": True, "false": False}.get(
            os.getenv("VULCAN_ENABLE_THINKING", "").lower()
        )
    )

    def __post_init__(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.embed_base_url = self.embed_base_url or self.base_url
        self.embed_api_key = self.embed_api_key or self.api_key


def load() -> Config:
    return Config()
