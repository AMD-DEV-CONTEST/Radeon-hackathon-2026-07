"""Shared resource and writable runtime path helpers."""
import os
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOT = Path(os.environ.get("AETHERDB_RESOURCE_ROOT", PROJECT_ROOT)).expanduser().resolve()
RUNTIME_ROOT = Path(os.environ.get("AETHERDB_RUNTIME_ROOT", PROJECT_ROOT)).expanduser().resolve()


def get_resource_path(*parts: str) -> Path:
    """Resolve a read-only asset shipped with AetherDB."""
    return RESOURCE_ROOT.joinpath(*parts)


def get_runtime_path(*parts: str) -> Path:
    """Resolve a user-owned writable runtime path."""
    return RUNTIME_ROOT.joinpath(*parts)


CONFIG_LOCAL_PATH = get_runtime_path("config.local.yaml")
CONFIG_DEFAULT_PATH = get_runtime_path("config.yaml")
CONFIG_EXAMPLE_PATH = get_resource_path("config.example.yaml")

def get_runtime_config_path() -> Path:
    """Read local config first; accept config.yaml only as a legacy migration fallback."""
    for path in (CONFIG_LOCAL_PATH, CONFIG_DEFAULT_PATH, CONFIG_EXAMPLE_PATH):
        if path.exists():
            return path
    raise FileNotFoundError("No config file found")

def get_writable_config_path() -> Path:
    """Create the ignored local config from a template or a legacy local file."""
    if not CONFIG_LOCAL_PATH.exists():
        source = CONFIG_DEFAULT_PATH if CONFIG_DEFAULT_PATH.exists() else CONFIG_EXAMPLE_PATH
        if not source.exists():
            raise FileNotFoundError("No source config file found")
        CONFIG_LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, CONFIG_LOCAL_PATH)
    return CONFIG_LOCAL_PATH

ENTITY_TYPES = {
    "character": "人物",
    "faction": "阵营",
    "location": "地点",
    "rule": "规则",
    "event": "事件",
    "item": "物品",
    "concept": "概念",
    "system": "系统",
}

ENTITY_PREFIXES = {
    "character": "CHR",
    "faction": "FAC",
    "location": "LOC",
    "rule": "RUL",
    "event": "EVT",
    "item": "ITM",
    "concept": "CON",
    "system": "SYS",
}

DB_PATH = str(get_runtime_path("novel_world_zh.db"))
