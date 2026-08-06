"""Immutable packaging of a trained vision model for deployment."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REQUIRED_MODEL_FILES = ("model.safetensors", "config.json", "preprocessor_config.json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def finalize_vision_model(
    source: Path,
    target: Path,
    *,
    model_id: str,
    revision: str,
    source_uri: str,
    license_name: str,
    validated_on_amd: bool,
) -> dict[str, Any]:
    """Copy a completed model into a new immutable deployment directory."""
    source = source.resolve()
    target = target.resolve()
    if not source.is_dir():
        raise FileNotFoundError(source)
    if source == target or source in target.parents:
        raise ValueError("target must not be the source or a child of the source")
    if target.exists():
        raise FileExistsError(f"refusing to overwrite deployment artifact: {target}")
    for value, field in (
        (model_id, "model_id"),
        (revision, "revision"),
        (source_uri, "source"),
        (license_name, "license"),
    ):
        if not value.strip():
            raise ValueError(f"{field} must be non-empty")
    for name in REQUIRED_MODEL_FILES:
        if not (source / name).is_file():
            raise FileNotFoundError(source / name)

    config_payload = json.loads((source / "config.json").read_text(encoding="utf-8"))
    id2label = config_payload.get("id2label")
    if not isinstance(id2label, dict) or not id2label:
        raise ValueError("config.json must contain a non-empty id2label map")

    temporary = target.with_name(f".{target.name}.partial-{uuid.uuid4().hex}")
    temporary.mkdir(parents=True)
    try:
        for name in REQUIRED_MODEL_FILES:
            shutil.copy2(source / name, temporary / name)
        files = {name: _sha256(temporary / name) for name in REQUIRED_MODEL_FILES}
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "model_id": model_id,
            "revision": revision,
            "source": source_uri,
            "license": license_name,
            "model_sha256": files["model.safetensors"],
            "files": files,
            "classes": {str(key): str(value) for key, value in id2label.items()},
            "created_at_utc": datetime.now(UTC).isoformat(),
            "validated_on_amd": validated_on_amd,
        }
        (temporary / "model-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.rename(target)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return manifest
