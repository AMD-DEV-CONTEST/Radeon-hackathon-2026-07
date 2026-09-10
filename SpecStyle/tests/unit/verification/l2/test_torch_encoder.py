"""Injectable style encoder contract."""

from __future__ import annotations

import pytest

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.verification.l2.encoder import EncoderPin
from specstyle.verification.l2.torch_encoder import (
    InjectableStyleEncoder,
    hash_projection_encoder,
    try_import_torch_encode_stub,
)


def test_hash_projection_deterministic() -> None:
    pin = EncoderPin("enc", "r1", "layer", "prep-v1")
    enc = hash_projection_encoder(pin, dim=16)
    h = Sha256("a" * 64)
    a = enc.encode(b"image-bytes", h)
    b = enc.encode(b"image-bytes", h)
    assert a.vector == b.vector
    assert len(a.vector) == 16
    assert a.pin == pin


def test_injectable_rejects_bad_vector() -> None:
    pin = EncoderPin("enc", "r1", "layer", "prep-v1")

    def bad(_b: bytes) -> tuple[float, ...]:
        return (1.0,)  # wrong dim

    enc = InjectableStyleEncoder(pin, bad, 4)
    with pytest.raises(DomainError, match="vector"):
        enc.encode(b"x", Sha256("b" * 64))


def test_torch_probe_honest_without_torch() -> None:
    try:
        import torch  # noqa: F401
    except Exception:
        with pytest.raises(InfrastructureError, match="torch unavailable"):
            try_import_torch_encode_stub()
    else:
        try_import_torch_encode_stub()
