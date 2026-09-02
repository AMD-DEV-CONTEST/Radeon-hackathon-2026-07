"""Private, random identity for future one-way publication provenance."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

from app.config import get_runtime_path


INSTANCE_ID_PREFIX = "aether_instance_"
INSTANCE_SCHEMA_VERSION = 1


class InstanceIdentityError(RuntimeError):
    pass


def _identity_path(runtime_root: Path | None = None) -> Path:
    root = runtime_root if runtime_root is not None else get_runtime_path("app_data")
    return Path(root).expanduser().resolve() / "instance.json"


def _validate_instance_id(value: object) -> str:
    instance_id = str(value or "")
    suffix = instance_id.removeprefix(INSTANCE_ID_PREFIX)
    if (
        not instance_id.startswith(INSTANCE_ID_PREFIX)
        or len(suffix) != 32
        or any(character not in "0123456789abcdef" for character in suffix)
    ):
        raise InstanceIdentityError("Runtime source_instance_id is malformed")
    return instance_id


def get_or_create_source_instance_id(runtime_root: Path | None = None) -> str:
    """Return a stable random ID without using user, device, or hardware data."""
    path = _identity_path(runtime_root)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InstanceIdentityError("Runtime instance identity is unreadable") from exc
        if payload.get("schema_version") != INSTANCE_SCHEMA_VERSION:
            raise InstanceIdentityError("Runtime instance identity schema is unsupported")
        return _validate_instance_id(payload.get("source_instance_id"))

    path.parent.mkdir(parents=True, exist_ok=True)
    instance_id = INSTANCE_ID_PREFIX + secrets.token_hex(16)
    payload = {
        "schema_version": INSTANCE_SCHEMA_VERSION,
        "source_instance_id": instance_id,
    }
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError:
        return get_or_create_source_instance_id(runtime_root)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True, indent=2) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return instance_id
