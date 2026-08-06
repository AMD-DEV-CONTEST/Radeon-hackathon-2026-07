"""Configuration loading: read .toml + .env, inject into Agently settings.

Dual-model scheme:
- chat:      Qwen3-8B (main model, RAG Q&A)
- reasoning: DeepSeek-R1-Distill-Qwen-7B (reasoning enhancement, complex computation)
- embedding: BGE-M3 (vectorized retrieval)

P0-1 fix: added model_request.retry_backoff_base/max retry backoff configuration.
P0-2 fix: tomllib fallback for Python <3.11.
P1-1 fix: added model_request.scheduler native scheduler configuration.
"""
import os

# P0-2: tomllib fallback — built-in for Python 3.11+, requires tomli on 3.10 and earlier
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # pip install tomli

from pathlib import Path
from dotenv import load_dotenv
from agently import Agently

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_config():
    """Load toml configurations + .env secrets, return the configuration dictionary."""
    load_dotenv(PROJECT_ROOT / ".env")

    with open(PROJECT_ROOT / "configs" / "agent.toml", "rb") as f:
        agent_cfg = tomllib.load(f)
    with open(PROJECT_ROOT / "configs" / "models.toml", "rb") as f:
        models_cfg = tomllib.load(f)
    return agent_cfg, models_cfg


def _require_env(env_key: str) -> str:
    """Read an environment variable, raise on missing value instead of silently returning an empty string (M7 fix)."""
    value = os.environ.get(env_key, "")
    if not value:
        raise RuntimeError(
            f"Environment variable {env_key} is not set or is empty. Please configure it in the .env file."
        )
    return value


def configure_agently(models_cfg: dict | None = None, agent_cfg: dict | None = None) -> None:
    """Call once at startup: inject the model_request scheduling/retry configuration into the Agently global.

    I5 fix: removed the global OpenAICompatible setting to avoid implicit state dependencies when combined
    with per-agent set_settings. Model connection configuration is injected by make_chat_agent /
    make_reasoning_agent / make_embedding_agent via per-agent set_settings.

    P0-1 fix: inject model_request.retry_backoff_base/max to implement exponential backoff retry.
    P1-1 fix: inject model_request.scheduler.max_concurrency to use the native scheduler.
    """
    pressure_cfg = (agent_cfg or {}).get("pressure", {})
    Agently.set_settings("model_request", {
        # P1-1: native scheduler replaces the custom Semaphore
        "scheduler": {
            "max_concurrency": pressure_cfg.get("max_concurrent_requests", 4),
            "rate_per_second": pressure_cfg.get("rate_per_second", 0),  # 0 = no rate limit
        },
        # P0-1: retry backoff — exponential backoff retry after failure
        "retry_backoff_base": pressure_cfg.get("retry_backoff_base", 1.0),
        "retry_backoff_max": pressure_cfg.get("retry_backoff_max", 10.0),
        "retry_max_attempts": pressure_cfg.get("retry_max_attempts", 3),
    })

    # ── Monkey-patch: Agently LocalBackend surrogate sanitization ──
    # Agently's LocalBackend.append_runtime_event writes event data into SQLite.
    # If the event data contains UTF-16 surrogate characters (such as \udce9), it triggers UnicodeEncodeError.
    # Surrogates come from incomplete UTF-16 decoding (e.g., truncated emoji, terminal encoding issues).
    # This patch wraps append_runtime_event and recursively sanitizes all strings before writing.
    _patch_agently_localbackend_surrogate()


def _sanitize_surrogate(obj):
    """Recursively remove UTF-16 surrogate characters from strings."""
    if isinstance(obj, str):
        return obj.encode("utf-8", errors="replace").decode("utf-8")
    if isinstance(obj, dict):
        return {k: _sanitize_surrogate(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_surrogate(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_sanitize_surrogate(v) for v in obj)
    return obj


def _patch_agently_localbackend_surrogate():
    """Monkey-patch Agently LocalBackend to sanitize surrogate characters before SQLite writes."""
    try:
        from agently.core.workspace import LocalBackend
        if getattr(LocalBackend, "_surrogate_patched", False):
            return  # already patched, skip

        _original_append = LocalBackend.append_runtime_event

        async def _sanitized_append(self, *args, **kwargs):
            # recursively sanitize all arguments
            clean_args = tuple(_sanitize_surrogate(a) for a in args)
            clean_kwargs = {k: _sanitize_surrogate(v) for k, v in kwargs.items()}
            return await _original_append(self, *clean_args, **clean_kwargs)

        LocalBackend.append_runtime_event = _sanitized_append
        LocalBackend._surrogate_patched = True

        import logging
        logging.getLogger(__name__).info("Agently LocalBackend surrogate sanitization patch installed")
    except ImportError:
        pass  # Agently not installed, skip
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Agently LocalBackend patch installation failed: %s", e)


def make_chat_agent(models_cfg: dict | None = None) -> object:
    """Return an Agent instance bound to the chat configuration (Qwen3-8B).

    I5 fix: uniformly use per-agent set_settings, no longer depending on the global OpenAICompatible.
    M7 fix: raise on missing env instead of silently returning an empty string.
    When models_cfg is None, fall back to the global configuration (backward compatible).
    """
    if not models_cfg:
        raise ValueError("make_chat_agent requires the models_cfg parameter (I5: no longer relies on global settings)")
    chat = models_cfg["chat"]
    agent = Agently.create_agent("insurance-chat")
    agent.set_settings("OpenAICompatible", {
        "base_url": chat["base_url"],
        "model": chat["model"],
        "model_type": chat["model_type"],
        "auth": _require_env(chat["auth_env"]),
        "request_options": chat.get("request_options", {}),
    })
    return agent


def make_reasoning_agent(models_cfg: dict) -> object:
    """Return an Agent instance bound to the reasoning configuration (DeepSeek-R1-Distill-Qwen-7B).

    Used for complex computation, logical reasoning, and other scenarios requiring deep chain-of-thought.
    Independent port (8002), does not affect the main model service.
    """
    reasoning = models_cfg.get("reasoning")
    if not reasoning:
        raise ValueError("The [reasoning] section is not configured in models.toml")
    agent = Agently.create_agent("insurance-reasoning")
    agent.set_settings("OpenAICompatible", {
        "base_url": reasoning["base_url"],
        "model": reasoning["model"],
        "model_type": reasoning["model_type"],
        "auth": _require_env(reasoning["auth_env"]),
        "request_options": reasoning.get("request_options", {}),
    })
    return agent


def make_embedding_agent(models_cfg: dict) -> object:
    """Return an embedding client instance.

    Uses DirectEmbeddingAgent (direct httpx call) instead of the Agently embedding agent
    to eliminate the TypeError caused by Agently response format uncertainty.

    Interface fully compatible: agent.input(texts).async_start() → list[list[float]]
    """
    from src.rag.embedding_client import DirectEmbeddingAgent

    emb = models_cfg["embedding"]
    # embedding service is usually local, auth key is optional (use _require_env to ensure .env is configured)
    api_key = _require_env(emb["auth_env"])
    return DirectEmbeddingAgent(
        base_url=emb["base_url"],
        model=emb["model"],
        api_key=api_key,
    )


def get_workspace_root(agent_cfg: dict) -> Path:
    """Return the Workspace root directory."""
    return Path(agent_cfg["workspace"]["root"])


def get_index_dir(agent_cfg: dict) -> Path:
    """Return the FAISS index directory."""
    path = agent_cfg["workspace"].get("index_dir", "")
    if not path:
        path = str(get_workspace_root(agent_cfg) / "index")
    return Path(path)