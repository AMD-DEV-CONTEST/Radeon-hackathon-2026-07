"""Verify a local model artifact against its immutable JSON manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(model: Path, manifest_path: Path) -> dict[str, Any]:
    model = model.resolve()
    manifest_path = manifest_path.resolve()
    if not model.is_file():
        raise FileNotFoundError(f"Model file does not exist: {model}")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Model manifest does not exist: {manifest_path}")
    payload: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("Model manifest root must be an object")
    expected = payload.get("model_sha256")
    revision = payload.get("revision")
    if not isinstance(expected, str) or not SHA256_PATTERN.fullmatch(expected):
        raise ValueError("Manifest model_sha256 must be 64 lowercase hexadecimal characters")
    if not isinstance(revision, str) or not revision.strip():
        raise ValueError("Manifest revision must be a non-empty immutable identifier")
    actual = sha256_file(model)
    if actual != expected:
        raise ValueError(f"Model SHA-256 mismatch: expected {expected}, actual {actual}")
    return {
        "status": "PASS",
        "model": str(model),
        "manifest": str(manifest_path),
        "revision": revision,
        "model_sha256": actual,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("model", type=Path)
    parser.add_argument("manifest", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(verify(arguments.model, arguments.manifest), indent=2))
