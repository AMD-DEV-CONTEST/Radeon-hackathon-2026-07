from __future__ import annotations

import uuid
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

_AGENT_DID_PREFIX = "did:percq:agent:"
_ORG_DID_PREFIX = "did:percq:org:"


def _generate_keypair() -> tuple[str, str]:
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_pem = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return priv_pem, pub_pem


def generate_org_keypair() -> tuple[str, str]:
    return _generate_keypair()


def generate_agent_keypair() -> tuple[str, str]:
    return _generate_keypair()


def did_for_agent(uuid4: str | None = None) -> str:
    if uuid4 is None:
        uuid4 = str(uuid.uuid4())
    return f"{_AGENT_DID_PREFIX}{uuid4}"


def did_for_org(slug: str) -> str:
    return f"{_ORG_DID_PREFIX}{slug}"


def sign(canonical_bytes_: bytes, private_pem: str) -> bytes:
    priv = serialization.load_pem_private_key(
        private_pem.encode("utf-8"), password=None
    )
    return priv.sign(canonical_bytes_)


def verify(canonical_bytes_: bytes, signature: bytes, public_pem: str) -> bool:
    try:
        pub = serialization.load_pem_public_key(public_pem.encode("utf-8"))
        pub.verify(signature, canonical_bytes_)
        return True
    except Exception:
        return False


def load_private_pem(path) -> str:
    return Path(path).read_text(encoding="utf-8")
