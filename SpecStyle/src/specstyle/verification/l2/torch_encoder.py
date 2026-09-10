"""Optional real-style encoder adapter — injected callable, no network.

Production path: host injects an encode function bound to local weights.
CPU contract path: use FakeStyleEncoder from encoder.py.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.observability.hashing import hash_bytes
from specstyle.verification.l2.encoder import EncoderPin, StyleFeature

EncodeFn = Callable[[bytes], tuple[float, ...]]


@dataclass(slots=True)
class InjectableStyleEncoder:
    """StyleEncoder implementation backed by a pure encode function."""

    _pin: EncoderPin
    _encode: EncodeFn
    _dim: int

    def __init__(self, pin: EncoderPin, encode: EncodeFn, dim: int) -> None:
        if type(pin) is not EncoderPin:
            raise DomainError("invalid encoder pin")
        if not callable(encode):
            raise DomainError("invalid encode function")
        if type(dim) is not int or isinstance(dim, bool) or dim < 2:
            raise DomainError("invalid encoder dim")
        self._pin = pin
        self._encode = encode
        self._dim = dim

    @property
    def pin(self) -> EncoderPin:
        return self._pin

    def encode(self, image_bytes: bytes, asset_hash: Sha256, /) -> StyleFeature:
        if type(image_bytes) is not bytes or not image_bytes:
            raise DomainError("invalid encode input")
        if type(asset_hash) is not Sha256:
            raise DomainError("invalid encode input")
        try:
            vector = self._encode(image_bytes)
        except DomainError:
            raise
        except Exception as exc:
            raise InfrastructureError("style encoder failed") from exc
        if type(vector) is not tuple or len(vector) != self._dim:
            raise DomainError("invalid encoder vector")
        if any(
            type(x) is not float or x != x or x in (float("inf"), float("-inf"))
            for x in vector
        ):
            raise DomainError("invalid encoder vector")
        return StyleFeature(vector, self._pin, asset_hash)


def hash_projection_encoder(pin: EncoderPin, dim: int = 32) -> InjectableStyleEncoder:
    """Deterministic CPU stand-in for integration without Torch weights."""

    def _encode(image_bytes: bytes) -> tuple[float, ...]:
        digest = hash_bytes(
            image_bytes
            + pin.encoder_id.encode()
            + pin.revision.encode()
            + pin.layer.encode()
            + pin.preprocess_version.encode()
        ).value
        vals: list[float] = []
        for i in range(dim):
            chunk = digest[(i * 2) % 64 : (i * 2) % 64 + 2]
            vals.append(int(chunk, 16) / 255.0)
        # L2-normalize-ish (avoid zero).
        norm = sum(v * v for v in vals) ** 0.5
        if norm == 0.0:
            vals[0] = 1.0
            norm = 1.0
        return tuple(v / norm for v in vals)

    return InjectableStyleEncoder(pin, _encode, dim)


def try_import_torch_encode_stub() -> None:
    """Honest availability probe for Torch-based encoders."""
    try:
        import torch  # noqa: F401
    except Exception as exc:
        raise InfrastructureError("torch unavailable for style encoder") from exc
