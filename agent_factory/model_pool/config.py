from __future__ import annotations

import os
from pathlib import Path

from agent_factory.paths import factory_artifact_path, resolve_project_path


MODEL_POOL_STORE_PATH_ENV = "AGENTFACTORY_MODEL_POOL_STORE_PATH"
MODEL_POOL_STORE_READ_ONLY_ENV = "AGENTFACTORY_MODEL_POOL_STORE_READ_ONLY"
MODEL_ROOT_ENV = "AGENTFACTORY_MODEL_ROOT"


def default_model_pool_store_path() -> Path:
    return factory_artifact_path("model_pool", "factory.sqlite")


def default_model_usage_store_path() -> Path:
    return factory_artifact_path("model_pool", "usage.sqlite")


def resolve_model_pool_store_path(value: str | Path | None = None) -> Path:
    configured = value if value is not None else os.getenv(MODEL_POOL_STORE_PATH_ENV)
    if configured:
        return resolve_project_path(configured)
    return default_model_pool_store_path()


def model_pool_store_read_only(value: str | None = None) -> bool:
    configured = value if value is not None else os.getenv(MODEL_POOL_STORE_READ_ONLY_ENV)
    return str(configured or "").strip().lower() in {"1", "true", "yes", "on"}


def default_model_root() -> Path:
    return factory_artifact_path("models")


def resolve_model_root(value: str | Path | None = None) -> Path:
    configured = value if value is not None else os.getenv(MODEL_ROOT_ENV)
    path = Path(configured).expanduser() if configured else default_model_root()
    return path.resolve()
