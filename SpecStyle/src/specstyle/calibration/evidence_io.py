"""Canonical JSON and primitive validators for calibration evidence."""

from __future__ import annotations

import json
import math
from typing import Any

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError
from specstyle.observability.hashing import hash_bytes

_PIN_KEYS = {"id", "revision", "sha256"}


def _pairs_no_duplicates(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def canonical_json(document: object) -> bytes:
    """Encode one canonical JSON document used by the evidence protocol."""
    try:
        return json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise DomainError("invalid evidence document") from exc


def _load_canonical(data: bytes) -> dict[str, Any]:
    if type(data) is not bytes or not data:
        raise DomainError("invalid evidence document")
    try:
        document = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("invalid constant")
            ),
        )
    except UnicodeError as exc:
        raise DomainError("invalid evidence encoding") from exc
    except ValueError as exc:
        if "duplicate key" in str(exc):
            raise DomainError("duplicate evidence key") from exc
        raise DomainError("invalid evidence document") from exc
    if type(document) is not dict or canonical_json(document) != data:
        raise DomainError("evidence document is not canonical")
    return document


def evidence_sha256(data: bytes) -> Sha256:
    """Hash canonical JSON bytes after duplicate-key and encoding checks."""
    _load_canonical(data)
    return hash_bytes(data)


def _exact(document: object, keys: set[str], name: str) -> dict[str, Any]:
    if type(document) is not dict or set(document) != keys:
        raise DomainError(f"invalid {name}")
    return document


def _text(value: object, name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > 2048
        or any(ord(character) <= 31 or ord(character) == 127 for character in value)
    ):
        raise DomainError(f"invalid {name}")
    return value


def _sha(value: object, name: str) -> str:
    try:
        return Sha256(value).value  # type: ignore[arg-type]
    except (DomainError, TypeError, AttributeError) as exc:
        raise DomainError(f"invalid {name}") from exc


def _float(value: object, name: str) -> float:
    if type(value) is not float or not math.isfinite(value):
        raise DomainError(f"invalid {name}")
    return value


def _count(value: object, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or isinstance(value, bool) or value < minimum:
        raise DomainError(f"invalid {name}")
    return value


def _pin(value: object, name: str) -> dict[str, str]:
    raw = _exact(value, _PIN_KEYS, name)
    return {
        "id": _text(raw["id"], f"{name} id"),
        "revision": _text(raw["revision"], f"{name} revision"),
        "sha256": _sha(raw["sha256"], f"{name} sha256"),
    }
