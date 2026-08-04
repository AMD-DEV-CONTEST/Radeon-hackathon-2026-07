"""
Local inference client for the fine-tuned fraud-classification model.

Model: Qwen3-14B, QLoRA fine-tuned (Unsloth) on 358,000+ historical Solana
scan records plus the Avalanche CIA/V5/V6 corpus, published as GGUF at
https://huggingface.co/ffurduj/syndicate-gguf (read-only reference:
Syndicate-Protocol/README.md).

AMD Track 2 requires core inference to run locally on the Radeon GPU/ROCm
stack, not a remote closed-source API. This client uses `llama-cpp-python`
(built with GGML_HIPBLAS=on for ROCm, see docker/Dockerfile and README) via
LangChain's `LlamaCpp` wrapper — a fully local, open-weight, open-runtime
path with no external API calls. Device/offload configuration comes from
gpu_config.py so the same code runs on the Z13 dev box (gfx1151) and on
whatever Radeon Cloud GPU the final submission targets.

The model is used as the final classifier over the *structured* module
outputs the orchestrator collects (matching how it was trained: on
structured CIA/V5/V6 scan-evidence records), not as a free-form ReAct tool
router — see orchestrator.py for why.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from .gpu_config import resolve_device_config

DEFAULT_MODEL_REPO = "ffurduj/syndicate-gguf"
DEFAULT_MODEL_FILE = os.getenv("CIA_LLM_GGUF_FILE", "qwen3-14b.Q4_K_M.gguf")


def resolve_model_path() -> Path:
    """
    Resolve the local GGUF model path. Preference order:
      1. CIA_LLM_MODEL_PATH env var (explicit local file)
      2. ./models/<DEFAULT_MODEL_FILE> next to this repo
      3. downloaded on demand from HuggingFace (ffurduj/syndicate-gguf) into ./models/
    """
    explicit = os.getenv("CIA_LLM_MODEL_PATH", "").strip()
    if explicit:
        return Path(explicit)

    local_dir = Path(os.getenv("CIA_LLM_MODEL_DIR", "models"))
    local_path = local_dir / DEFAULT_MODEL_FILE
    if local_path.exists():
        return local_path

    local_dir.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import hf_hub_download

        downloaded = hf_hub_download(
            repo_id=DEFAULT_MODEL_REPO, filename=DEFAULT_MODEL_FILE, local_dir=str(local_dir)
        )
        return Path(downloaded)
    except Exception as exc:  # pragma: no cover - network/environment dependent
        raise RuntimeError(
            f"Could not find or download the GGUF model. Set CIA_LLM_MODEL_PATH to a local "
            f"file, or ensure network access to download {DEFAULT_MODEL_REPO}/{DEFAULT_MODEL_FILE}. "
            f"Underlying error: {exc}"
        ) from exc


def build_llm(model_path: Optional[Path] = None):
    """
    Build a LangChain `LlamaCpp` LLM bound to the local GGUF model, offloaded
    to the detected Radeon GPU via ROCm (falls back to CPU if none detected).
    Import of langchain_community.llms.LlamaCpp is deferred so environments
    that only need the deterministic planner/tools (e.g. CI, unit tests) are
    not forced to install llama-cpp-python.
    """
    from langchain_community.llms import LlamaCpp

    device = resolve_device_config()
    path = model_path or resolve_model_path()

    return LlamaCpp(
        model_path=str(path),
        n_gpu_layers=device.n_gpu_layers,
        n_ctx=int(os.getenv("CIA_LLM_CTX", "4096")),
        temperature=float(os.getenv("CIA_LLM_TEMPERATURE", "0.1")),
        max_tokens=int(os.getenv("CIA_LLM_MAX_TOKENS", "512")),
        verbose=os.getenv("CIA_LLM_VERBOSE", "false").lower() == "true",
    )
