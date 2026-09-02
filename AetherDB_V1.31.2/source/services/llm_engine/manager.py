"""AIEngineManager — reads llm config, manages initialization state."""
import os, yaml, logging
from typing import Optional
from app.config import get_runtime_config_path, get_writable_config_path

log = logging.getLogger(__name__)

class AIEngineManager:
    """Reads and manages AI Engine configuration."""

    @staticmethod
    def load_config() -> dict:
        with get_runtime_config_path().open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        return cfg.get("llm", {})

    @staticmethod
    def save_config(llm_cfg: dict):
        config_path = get_writable_config_path()
        with config_path.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        cfg["llm"] = llm_cfg
        with config_path.open("w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)

    @staticmethod
    def get_status() -> dict:
        cfg = AIEngineManager.load_config()
        mode = cfg.get("mode", "disabled")
        cloud = cfg.get("cloud", {}).get("active_provider", "none")
        local = cfg.get("local", {}).get("enabled", False)
        initialized = cfg.get("initialized", False)
        return {
            "initialized": initialized,
            "mode": mode,
            "cloud_provider": cloud if mode in ("cloud", "hybrid") else None,
            "local_enabled": local if mode in ("local", "hybrid") else False,
            "status": "ready" if initialized else "not_configured",
        }

    @staticmethod
    def update_config(updates: dict) -> dict:
        cfg = AIEngineManager.load_config()
        def deep_merge(base, overrides):
            for k, v in overrides.items():
                if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                    deep_merge(base[k], v)
                else:
                    base[k] = v
        deep_merge(cfg, updates)
        AIEngineManager.save_config(cfg)
        return cfg

    @staticmethod
    def get_analysis_preferences() -> dict:
        cfg = AIEngineManager.load_config()
        settings = cfg.get("import_analysis") or {}
        mode = settings.get("default_mode", "ask")
        if mode not in {"ask", "local_rules", "cloud_model"}:
            mode = "ask"
        return {"default_mode": mode}

    @staticmethod
    def update_analysis_preferences(default_mode: str) -> dict:
        if default_mode not in {"ask", "local_rules", "cloud_model"}:
            raise ValueError("Unsupported analysis preference")
        AIEngineManager.update_config({"import_analysis": {"default_mode": default_mode}})
        return AIEngineManager.get_analysis_preferences()
