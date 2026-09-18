"""Verify every configured competition model artifact and manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml
from verify_model_manifest import verify


def verify_inventory(config_path: Path) -> dict[str, Any]:
    raw: Any = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("models"), dict):
        raise TypeError("Model inventory must contain a models mapping")
    results: dict[str, dict[str, Any]] = {}
    for name, entry in raw["models"].items():
        if not isinstance(name, str) or not isinstance(entry, dict):
            raise TypeError("Invalid model inventory entry")
        artifact = Path(str(entry.get("artifact", "")))
        manifest = Path(str(entry.get("manifest", "")))
        results[name] = verify(artifact, manifest)
    return {"status": "PASS", "models": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    arguments = parser.parse_args()
    print(
        json.dumps(
            verify_inventory(arguments.config.resolve()),
            ensure_ascii=False,
            indent=2,
        )
    )
