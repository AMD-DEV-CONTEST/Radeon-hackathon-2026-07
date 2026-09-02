"""LLMRouter — routes by task_type to the appropriate provider."""
from typing import Optional
from services.llm_engine.manager import AIEngineManager
from services.llm_engine.cloud_provider import get_cloud_provider
from services.llm_engine.local_runtime import get_local_provider
import logging

log = logging.getLogger(__name__)

# Default routing: maps task_type -> preferred backend
_DEFAULT_ROUTES = {
    "quick_import": "local",
    "chapter_split": "local",
    "chapter_analysis": "local",
    "entity_extract": "local",
    "relation_extract": "local",
    "book_summary": "cloud",
    "conflict_check": "cloud",
    "rag_answer": "hybrid",
    "creative_assist": "hybrid",
    "ask_first": "hybrid",
}

class LLMRouter:
    """Routes LLM requests to the appropriate provider by task type."""

    def __init__(self, config: Optional[dict] = None):
        self._config = config or AIEngineManager.load_config()

    def route(self, task_type: str, messages: list, **kwargs) -> str:
        """Route a request to the appropriate provider."""
        mode = self._config.get("mode", "disabled")
        if mode == "disabled":
            raise RuntimeError("AI Engine is disabled")
        preferred = _DEFAULT_ROUTES.get(task_type, "local")
        cloud_cfg = self._config.get("cloud", {})
        local_cfg = self._config.get("local", {})

        if mode == "cloud" or (mode == "hybrid" and preferred == "cloud"):
            return self._call_cloud(cloud_cfg, messages, **kwargs)
        elif mode == "local" or (mode == "hybrid" and preferred == "local"):
            return self._call_local(local_cfg, messages, **kwargs)
        elif mode == "hybrid":
            try:
                return self._call_local(local_cfg, messages, **kwargs)
            except Exception:
                if self._config.get("safety", {}).get("ask_before_cloud_fallback", True):
                    raise RuntimeError("Local model unavailable. Cloud fallback requires user confirmation.")
                return self._call_cloud(cloud_cfg, messages, **kwargs)
        raise RuntimeError(f"Invalid AI mode: {mode}")

    def _call_cloud(self, cfg: dict, messages: list, **kwargs) -> str:
        provider_name = cfg.get("active_provider", "deepseek")
        provider = get_cloud_provider(provider_name, cfg)
        return provider.chat(messages, **kwargs)

    def _call_local(self, cfg: dict, messages: list, **kwargs) -> str:
        provider = get_local_provider(cfg)
        return provider.chat(messages, **kwargs)
