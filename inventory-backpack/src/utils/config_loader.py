"""Config loader - adapts to your agent.yaml structure"""

from __future__ import annotations

import os
import re
import yaml
from pathlib import Path


def _resolve_env_vars(value):
    """Parse ${VAR} or ${VAR:-default} format"""
    if not isinstance(value, str):
        return value

    # Match ${VAR:-default} or ${VAR}
    pattern = r'\$\{([^}]+?)(?::-(.*?))?\}'
    
    def replace(match):
        var_name = match.group(1)
        default = match.group(2) or ""
        return os.environ.get(var_name, default)
    
    return re.sub(pattern, replace, value)


def _deep_resolve(obj):
    """Recursively resolve all environment variables"""
    if isinstance(obj, dict):
        return {k: _deep_resolve(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_deep_resolve(v) for v in obj]
    elif isinstance(obj, str):
        return _resolve_env_vars(obj)
    return obj


def load_config(path: str = "config/agent.yaml") -> dict:
    """Load config, auto-resolve environment variables"""
    config_path = Path(path)

    # Multi-path search
    search_paths = [
        config_path,
        Path.cwd() / path,
        Path(__file__).parents[2] / path,
        Path(__file__).parents[2] / "config" / "agent.yaml",
    ]
    
    for p in search_paths:
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
                return _deep_resolve(raw)
    
    return {}


def get_remote_config(path: str = "config/agent.yaml") -> dict:
    """Get remote config (for API connections)"""
    config = load_config(path)
    return config.get("remote", {})


def get_rag_config(path: str = "config/agent.yaml") -> dict:
    """Get RAG config"""
    config = load_config(path)
    return config.get("rag", {})


def get_inference_config(path: str = "config/agent.yaml") -> dict:
    """Get inference parameters"""
    config = load_config(path)
    return config.get("inference", {})