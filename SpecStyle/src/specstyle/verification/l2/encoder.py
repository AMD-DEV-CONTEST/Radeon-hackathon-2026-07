"""StyleEncoder protocol, FakeEncoder, and atomic feature cache."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.observability.hashing import hash_bytes


@dataclass(frozen=True, slots=True)
class EncoderPin:
    encoder_id: str
    revision: str
    layer: str
    preprocess_version: str

    def __post_init__(self) -> None:
        for name in ("encoder_id", "revision", "layer", "preprocess_version"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip() or value != value.strip():
                raise DomainError("invalid encoder pin")


@dataclass(frozen=True, slots=True)
class StyleFeature:
    vector: tuple[float, ...]
    pin: EncoderPin
    asset_hash: Sha256

    def __post_init__(self) -> None:
        if type(self.vector) is not tuple or not self.vector:
            raise DomainError("invalid feature vector")
        if any(
            type(x) is not float or x != x or x in (float("inf"), float("-inf"))
            for x in self.vector
        ):
            raise DomainError("invalid feature vector")
        if type(self.pin) is not EncoderPin or type(self.asset_hash) is not Sha256:
            raise DomainError("invalid feature")


@runtime_checkable
class StyleEncoder(Protocol):
    @property
    def pin(self) -> EncoderPin: ...

    def encode(self, image_bytes: bytes, asset_hash: Sha256, /) -> StyleFeature: ...


class FakeStyleEncoder:
    """Deterministic CPU encoder: hash-derived unit-ish vector."""

    def __init__(self, pin: EncoderPin, dim: int = 8) -> None:
        if type(pin) is not EncoderPin or type(dim) is not int or dim < 2:
            raise DomainError("invalid fake encoder")
        self._pin = pin
        self._dim = dim

    @property
    def pin(self) -> EncoderPin:
        return self._pin

    def encode(self, image_bytes: bytes, asset_hash: Sha256, /) -> StyleFeature:
        if type(image_bytes) is not bytes or type(asset_hash) is not Sha256:
            raise DomainError("invalid encode input")
        if not image_bytes:
            raise DomainError("empty image")
        digest = hash_bytes(
            image_bytes
            + self._pin.encoder_id.encode()
            + self._pin.revision.encode()
            + self._pin.layer.encode()
            + self._pin.preprocess_version.encode()
            + asset_hash.value.encode()
        ).value
        raw = bytes.fromhex(digest)
        vec = []
        for i in range(self._dim):
            vec.append((raw[i % len(raw)] / 255.0) * 2.0 - 1.0)
        return StyleFeature(tuple(vec), self._pin, asset_hash)


def cache_key(pin: EncoderPin, asset_hash: Sha256) -> str:
    material = "|".join(
        (
            pin.encoder_id,
            pin.revision,
            pin.layer,
            pin.preprocess_version,
            asset_hash.value,
        )
    )
    return hash_bytes(material.encode("utf-8")).value


class FeatureCache:
    """Local atomic JSON feature cache keyed by encoder pin + asset hash."""

    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path):
            raise DomainError("invalid cache root")
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def get(self, pin: EncoderPin, asset_hash: Sha256) -> StyleFeature | None:
        path = self._root / f"{cache_key(pin, asset_hash)}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_bytes())
        except (OSError, json.JSONDecodeError) as exc:
            raise InfrastructureError("feature cache read failed") from exc
        if type(data) is not dict:
            raise DomainError("corrupt feature cache")
        vec = data.get("vector")
        if type(vec) is not list or any(type(x) is not float for x in vec):
            raise DomainError("corrupt feature cache")
        if any(x != x or x in (float("inf"), float("-inf")) for x in vec):
            raise DomainError("corrupt feature cache")
        return StyleFeature(tuple(vec), pin, asset_hash)

    def put(self, feature: StyleFeature) -> None:
        if type(feature) is not StyleFeature:
            raise DomainError("invalid feature")
        key = cache_key(feature.pin, feature.asset_hash)
        path = self._root / f"{key}.json"
        # Unique tmp per writer so concurrent puts do not clobber partial files.
        tmp = self._root / f".{key}.{os.getpid()}.{threading.get_ident()}.tmp"
        payload = json.dumps(
            {"vector": list(feature.vector)},
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        try:
            with open(tmp, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except OSError as exc:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise InfrastructureError("feature cache write failed") from exc


_ENCODE_LOCKS: dict[str, threading.Lock] = {}
_ENCODE_LOCKS_GUARD = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _ENCODE_LOCKS_GUARD:
        lock = _ENCODE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _ENCODE_LOCKS[key] = lock
        return lock


def encode_with_cache(
    encoder: StyleEncoder,
    cache: FeatureCache,
    image_bytes: bytes,
    asset_hash: Sha256,
    /,
) -> StyleFeature:
    """Encode with single-flight per cache key (in-process)."""
    key = cache_key(encoder.pin, asset_hash)
    lock = _lock_for(key)
    with lock:
        hit = cache.get(encoder.pin, asset_hash)
        if hit is not None:
            if hit.pin != encoder.pin:
                raise DomainError("cache pin mismatch")
            return hit
        feature = encoder.encode(image_bytes, asset_hash)
        cache.put(feature)
        return feature
