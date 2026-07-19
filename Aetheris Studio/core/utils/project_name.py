"""Persisted "active project" display name. Was Mongo-backed with a local
`models/config.json` fallback (`core/mongo.py`, now removed along with
MongoDB entirely) -- this is just the local-file path, always, using the
same atomic-write pattern as everything else in this codebase.
"""

import os

from core.atomic_io import atomic_read_json, atomic_write_json

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "models", "config.json")


def persist_project_name(name: str) -> None:
    config = atomic_read_json(_CONFIG_PATH, default={})
    config["project_name"] = name
    atomic_write_json(_CONFIG_PATH, config)


def get_project_name() -> str:
    config = atomic_read_json(_CONFIG_PATH, default={})
    if "project_name" in config:
        return config["project_name"]

    active_path = os.environ.get("ACTIVE_PROJECT_PATH", "")
    if active_path:
        return os.path.basename(active_path)
    return "PROJETO ATIVO"
