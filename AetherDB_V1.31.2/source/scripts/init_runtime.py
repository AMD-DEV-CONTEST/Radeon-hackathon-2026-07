"""Initialize local runtime files for a fresh checkout.

This script creates only local runtime artifacts. Those artifacts are ignored
by Git and must not be committed.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.config import get_resource_path, get_runtime_path
from app.instance_identity import get_or_create_source_instance_id

CONFIG_EXAMPLE = get_resource_path("config.example.yaml")
CONFIG_LOCAL = get_runtime_path("config.local.yaml")
KEY_FILE = get_runtime_path(".api_keys.json")
RUNTIME_DIRS = [
    get_runtime_path("app_data"),
    get_runtime_path("app_data", "databases"),
    get_runtime_path("app_data", "cache"),
    get_runtime_path("logs"),
    get_runtime_path("备份内容"),
]


def ensure_config() -> None:
    if CONFIG_LOCAL.exists():
        print("[OK] config.local.yaml exists")
        return
    if not CONFIG_EXAMPLE.exists():
        raise FileNotFoundError("config.example.yaml is missing")
    CONFIG_LOCAL.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(CONFIG_EXAMPLE, CONFIG_LOCAL)
    print("[OK] created config.local.yaml from config.example.yaml")


def ensure_directories() -> None:
    for path in RUNTIME_DIRS:
        path.mkdir(parents=True, exist_ok=True)
    print("[OK] runtime directories are ready")


def ensure_api_keys() -> None:
    if KEY_FILE.exists():
        print("[OK] .api_keys.json exists")
        return

    from app.dependencies.auth import ADMIN_API_KEY, USER_API_KEY

    if not KEY_FILE.exists():
        with KEY_FILE.open("w", encoding="utf-8") as f:
            json.dump({"admin": ADMIN_API_KEY, "user": USER_API_KEY}, f, indent=2)
    try:
        os.chmod(KEY_FILE, 0o600)
    except OSError:
        pass
    print("[OK] generated .api_keys.json")
    print("[INFO] API keys are stored only in the private runtime key file")


def ensure_instance_identity() -> None:
    get_or_create_source_instance_id(get_runtime_path("app_data"))
    print("[OK] private source instance identity is ready")


def main() -> int:
    ensure_config()
    ensure_directories()
    ensure_instance_identity()
    ensure_api_keys()
    print("[OK] local runtime initialization complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
