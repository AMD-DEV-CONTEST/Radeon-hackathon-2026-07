"""
fleet.crypto -- sealed-box encryption for fleet contributions (no new dependency).
==================================================================================
HPKE-style anonymous sealed box using the stdlib-adjacent `cryptography` package
(already a Determinex dependency; pynacl is intentionally NOT required):

    node keypair:  X25519 (private stays on the node; public is published)
    per-shard:     ephemeral X25519 keypair -> ECDH with node public key
                   -> HKDF-SHA256 -> ChaCha20Poly1305 (AEAD)

Only the node's private key can open a shard. The contributor needs no identity and
no shared secret -- they only need the node's *public* key. The ephemeral key is
discarded after sealing, so a shard is not linkable to a long-lived contributor key.

    pub, priv = generate_node_keypair()
    env = seal(pub, b"...payload...")            # contributor side
    plaintext = open_sealed(priv, env)           # node side (Hetzner only)

`env` is a small JSON-serializable dict (base64 fields) safe to write to R2 / HF.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from . import SEAL_ALG

_HKDF_INFO = b"determinex-fleet-sealed-box-v1"


def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def _raw_pub(pub: X25519PublicKey) -> bytes:
    return pub.public_bytes(Encoding.Raw, PublicFormat.Raw)


def key_id(pub: X25519PublicKey) -> str:
    """Short, stable fingerprint of a public key (first 8 bytes of SHA-256, hex)."""
    return hashlib.sha256(_raw_pub(pub)).hexdigest()[:16]


# ---------------------------------------------------------------------------
# keypair management
# ---------------------------------------------------------------------------
def generate_node_keypair() -> tuple[str, str]:
    """Return (public_b64, private_b64). Publish the public; keep private on node."""
    priv = X25519PrivateKey.generate()
    pub = priv.public_key()
    priv_raw = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return _b64e(_raw_pub(pub)), _b64e(priv_raw)


def load_public(pub_b64: str) -> X25519PublicKey:
    return X25519PublicKey.from_public_bytes(_b64d(pub_b64))


def load_private(priv_b64: str) -> X25519PrivateKey:
    return X25519PrivateKey.from_private_bytes(_b64d(priv_b64))


# ---------------------------------------------------------------------------
# seal / open
# ---------------------------------------------------------------------------
def _derive_key(shared: bytes, epk_raw: bytes, node_pub_raw: bytes) -> bytes:
    # bind the derived key to both public keys (defends against key-confusion).
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=_HKDF_INFO + epk_raw + node_pub_raw,
    ).derive(shared)


def seal(node_pub_b64: str, plaintext: bytes, aad: bytes = b"") -> dict[str, Any]:
    """Contributor side: encrypt `plaintext` so only the node private key can open it."""
    node_pub = load_public(node_pub_b64)
    eph = X25519PrivateKey.generate()
    epk_raw = _raw_pub(eph.public_key())
    shared = eph.exchange(node_pub)
    aead_key = _derive_key(shared, epk_raw, _raw_pub(node_pub))
    nonce = hashlib.sha256(epk_raw).digest()[:12]  # unique per ephemeral key
    ct = ChaCha20Poly1305(aead_key).encrypt(nonce, plaintext, aad)
    return {
        "v": 1,
        "alg": SEAL_ALG,
        "node_key_id": key_id(node_pub),
        "epk": _b64e(epk_raw),
        "nonce": _b64e(nonce),
        "ct": _b64e(ct),
        "aad": _b64e(aad) if aad else "",
    }


def open_sealed(node_priv_b64: str, env: dict[str, Any]) -> bytes:
    """Node side (Hetzner only): recover plaintext from a sealed envelope."""
    if env.get("alg") != SEAL_ALG:
        raise ValueError(f"unsupported seal alg: {env.get('alg')!r}")
    priv = load_private(node_priv_b64)
    node_pub_raw = _raw_pub(priv.public_key())
    if env.get("node_key_id") and env["node_key_id"] != key_id(priv.public_key()):
        raise ValueError("shard sealed to a different node key")
    epk_raw = _b64d(env["epk"])
    eph_pub = X25519PublicKey.from_public_bytes(epk_raw)
    shared = priv.exchange(eph_pub)
    aead_key = _derive_key(shared, epk_raw, node_pub_raw)
    aad = _b64d(env["aad"]) if env.get("aad") else b""
    return ChaCha20Poly1305(aead_key).decrypt(_b64d(env["nonce"]), _b64d(env["ct"]), aad)


def seal_json(node_pub_b64: str, obj: Any, aad: bytes = b"") -> dict[str, Any]:
    return seal(node_pub_b64, json.dumps(obj, separators=(",", ":")).encode("utf-8"), aad)


def open_json(node_priv_b64: str, env: dict[str, Any]) -> Any:
    return json.loads(open_sealed(node_priv_b64, env).decode("utf-8"))
