"""Fail-closed readers for immutable H3 input artifacts.

The durable artifact reference is metadata, not proof that storage still
contains the same object.  This boundary therefore validates the reference
set before any I/O and re-verifies bytes returned by the injected gateway.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from collections.abc import Iterable, Mapping, Set
from typing import TypeVar
from urllib.parse import unquote
from uuid import UUID

from pydantic import BaseModel
from shared_contracts import AtomicArtifactRef


__all__ = ("H3ArtifactInputError", "VerifiedH3ArtifactInputs")


_ModelT = TypeVar("_ModelT", bound=BaseModel)

# A caller may choose a smaller limit for a particular role, but it may not
# turn this verification boundary into an unbounded allocation primitive.
_MAXIMUM_ARTIFACT_BYTES = 1_073_741_824
_DEFAULT_JSON_BYTES = 16_777_216
_MAX_PERCENT_DECODES = 8
_MAX_JSON_DEPTH = 64
_MAX_JSON_CONTAINERS = 16_384
_MAX_JSON_NODES = 131_072

_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_URI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


class H3ArtifactInputError(RuntimeError):
    """A safe public error for an untrusted H3 artifact input."""


class _DuplicateJsonKey(ValueError):
    pass


def _normalized_path_key(key: str) -> str:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key.strip())
    return re.sub(r"[^a-z0-9]+", "_", separated.lower()).strip("_")


def _is_physical_path_key(key: str) -> bool:
    normalized = _normalized_path_key(key)
    path_names = {
        "path",
        "paths",
        "file",
        "files",
        "filepath",
        "filepaths",
        "filename",
        "filenames",
    }
    return normalized in path_names or normalized.endswith(
        tuple(f"_{name}" for name in path_names)
    )


def _decode_for_path_check(value: str) -> str:
    decoded = value
    # Repeated encoding must not turn traversal into an accepted value.
    for _ in range(_MAX_PERCENT_DECODES):
        candidate = unquote(decoded)
        if candidate == decoded:
            return decoded.strip()
        decoded = candidate
    if unquote(decoded) != decoded:
        raise H3ArtifactInputError(
            "JSON string exceeds percent-decoding limit"
        )
    return decoded.strip()


def _looks_like_physical_path(value: str) -> bool:
    candidate = _decode_for_path_check(value)
    lowered = candidate.lower()
    if (
        not candidate
        or lowered.startswith("file:")
        or _WINDOWS_ABSOLUTE_PATH.match(candidate)
        or candidate.startswith(("/", "\\\\", "~/", "~\\"))
        or "\\" in candidate
    ):
        return bool(candidate)

    # Artifact and public HTTP(S) locators are logical identifiers.  They are
    # not local filesystem paths and are deliberately allowed here.
    if _URI_SCHEME.match(candidate):
        return False

    segments = candidate.split("/")
    return any(segment in {".", ".."} for segment in segments)


def _reject_physical_paths(value: object) -> None:
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, Mapping):
            for key, child in current.items():
                if _is_physical_path_key(key):
                    raise H3ArtifactInputError(
                        "JSON contains a forbidden physical path field"
                    )
                pending.append(child)
        elif isinstance(current, list):
            pending.extend(current)
        elif isinstance(current, str) and _looks_like_physical_path(current):
            raise H3ArtifactInputError(
                "JSON contains a forbidden path-like string"
            )


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey
        result[key] = value
    return result


def _reject_non_json_number(_value: str) -> object:
    raise ValueError


def _strict_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError
    return parsed


def _enforce_json_protocol_limits(value: object) -> None:
    """Bound decoded JSON iteratively before schema validation."""

    pending: list[tuple[object, int]] = [(value, 1)]
    node_count = 0
    container_count = 0
    while pending:
        current, depth = pending.pop()
        node_count += 1
        if node_count > _MAX_JSON_NODES:
            raise H3ArtifactInputError(
                "JSON document exceeds complexity limit"
            )
        if isinstance(current, Mapping):
            container_count += 1
            if depth > _MAX_JSON_DEPTH:
                raise H3ArtifactInputError(
                    "JSON document exceeds depth limit"
                )
            if container_count > _MAX_JSON_CONTAINERS:
                raise H3ArtifactInputError(
                    "JSON document exceeds complexity limit"
                )
            if node_count + len(pending) + len(current) > _MAX_JSON_NODES:
                raise H3ArtifactInputError(
                    "JSON document exceeds complexity limit"
                )
            pending.extend((child, depth + 1) for child in current.values())
        elif isinstance(current, list):
            container_count += 1
            if depth > _MAX_JSON_DEPTH:
                raise H3ArtifactInputError(
                    "JSON document exceeds depth limit"
                )
            if container_count > _MAX_JSON_CONTAINERS:
                raise H3ArtifactInputError(
                    "JSON document exceeds complexity limit"
                )
            if node_count + len(pending) + len(current) > _MAX_JSON_NODES:
                raise H3ArtifactInputError(
                    "JSON document exceeds complexity limit"
                )
            pending.extend((child, depth + 1) for child in current)


def _allowed_mimes(values: Set[str]) -> frozenset[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Set):
        raise H3ArtifactInputError("allowed MIME types must be a set")
    normalized = frozenset(values)
    if not normalized or any(
        not isinstance(value, str)
        or not value
        or value != value.strip()
        for value in normalized
    ):
        raise H3ArtifactInputError("allowed MIME types must be pinned")
    return normalized


def _bounded_maximum(value: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        or value > _MAXIMUM_ARTIFACT_BYTES
    ):
        raise H3ArtifactInputError("maximum artifact size is invalid")
    return value


class VerifiedH3ArtifactInputs:
    """Read an H3 input only after its immutable authority is re-verified."""

    __slots__ = ("_cache", "_reader", "_refs_by_role")

    def __init__(
        self,
        *,
        project_id: UUID,
        artifact_refs: Iterable[AtomicArtifactRef],
        gateway: object,
    ) -> None:
        if not isinstance(project_id, UUID):
            raise H3ArtifactInputError("artifact project identity is invalid")

        try:
            refs = tuple(artifact_refs)
        except (TypeError, ValueError):
            raise H3ArtifactInputError("artifact references are invalid") from None

        refs_by_role: dict[str, AtomicArtifactRef] = {}
        artifact_ids: set[UUID] = set()
        for ref in refs:
            if not isinstance(ref, AtomicArtifactRef):
                raise H3ArtifactInputError("artifact reference type is invalid")
            if ref.project_id != project_id:
                raise H3ArtifactInputError("artifact project identity mismatch")
            if ref.artifact_id in artifact_ids:
                raise H3ArtifactInputError("duplicate artifact identity")
            if ref.logical_role in refs_by_role:
                raise H3ArtifactInputError("duplicate artifact logical role")
            artifact_ids.add(ref.artifact_id)
            refs_by_role[ref.logical_role] = ref

        try:
            reader = getattr(gateway, "read_bytes")
        except Exception:
            raise H3ArtifactInputError("artifact gateway is invalid") from None
        if not callable(reader):
            raise H3ArtifactInputError("artifact gateway reader is not callable")

        self._refs_by_role = refs_by_role
        self._reader = reader
        self._cache: dict[UUID, bytes] = {}

    def read_bytes(
        self,
        role: str,
        *,
        allowed_mime_types: Set[str],
        maximum_bytes: int = _MAXIMUM_ARTIFACT_BYTES,
    ) -> bytes:
        """Return verified immutable bytes for exactly one logical role."""

        if (
            not isinstance(role, str)
            or not role
            or role != role.strip()
        ):
            raise H3ArtifactInputError("artifact role is invalid")
        allowed = _allowed_mimes(allowed_mime_types)
        maximum = _bounded_maximum(maximum_bytes)
        ref = self._refs_by_role.get(role)
        if ref is None:
            raise H3ArtifactInputError("artifact role is not available")
        if ref.mime_type not in allowed:
            raise H3ArtifactInputError("artifact MIME type is not allowed")
        if ref.byte_size > maximum:
            raise H3ArtifactInputError("artifact size is too large")

        cached = self._cache.get(ref.artifact_id)
        if cached is not None:
            return cached

        try:
            payload = self._reader(ref)
        except Exception:
            raise H3ArtifactInputError("artifact gateway read failed") from None
        if not isinstance(payload, bytes):
            raise H3ArtifactInputError("artifact gateway must return bytes")
        if len(payload) != ref.byte_size:
            raise H3ArtifactInputError("artifact size verification failed")
        digest = hashlib.sha256(payload).hexdigest()
        if not hmac.compare_digest(digest, str(ref.content_digest)):
            raise H3ArtifactInputError("artifact digest verification failed")

        self._cache[ref.artifact_id] = payload
        return payload

    def read_json_model(
        self,
        role: str,
        model: type[_ModelT],
        *,
        maximum_bytes: int = _DEFAULT_JSON_BYTES,
    ) -> _ModelT:
        """Decode one strict, path-free JSON object as a Pydantic model."""

        if not isinstance(model, type) or not issubclass(model, BaseModel):
            raise H3ArtifactInputError("JSON schema model is invalid")
        payload = self.read_bytes(
            role,
            allowed_mime_types=frozenset({"application/json"}),
            maximum_bytes=maximum_bytes,
        )
        try:
            text = payload.decode("utf-8", errors="strict")
            decoded = json.loads(
                text,
                object_pairs_hook=_json_object,
                parse_constant=_reject_non_json_number,
                parse_float=_strict_json_float,
            )
        except _DuplicateJsonKey:
            raise H3ArtifactInputError("JSON contains a duplicate key") from None
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
            raise H3ArtifactInputError("JSON document is invalid") from None
        if not isinstance(decoded, dict):
            raise H3ArtifactInputError("JSON document must be one object")

        _enforce_json_protocol_limits(decoded)
        _reject_physical_paths(decoded)

        try:
            return model.model_validate(decoded)
        except Exception:
            # Validation details may contain attacker-controlled input values.
            raise H3ArtifactInputError("JSON schema validation failed") from None
