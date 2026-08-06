"""Encryption at rest for MedGlass PHI (notes, transcripts, case photos).

AES-256-GCM envelope using a per-install key file (``output/.keys/medglass.key``,
0600 perms). Encoded blobs look like ``v1.<b64 nonce>.<b64 ct+tag>`` so readers
can detect and decrypt transparently while old plaintext files keep working.
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

LOG = logging.getLogger("medglass.crypto")

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _AVAILABLE = True
except Exception:  # pragma: no cover - cryptography absent
    AESGCM = None
    _AVAILABLE = False

_KEK: bytes | None = None
_KEY_PATH = Path("output") / ".keys" / "medglass.key"
_PREFIX = "v1."


def available() -> bool:
    return _AVAILABLE


def _load_key() -> bytes | None:
    global _KEK
    if _KEK is not None:
        return _KEK
    if not _AVAILABLE:
        return None
    key_path = _KEY_PATH
    key_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if not key_path.exists():
            key = os.urandom(32)
            key_path.write_bytes(key)
            key_path.chmod(0o600)
            LOG.info("generated encryption key %s", key_path)
        _KEK = key_path.read_bytes()
        if len(_KEK) != 32:
            raise ValueError("key file must be 32 bytes")
        return _KEK
    except Exception as exc:
        LOG.error("encryption unavailable: %s", exc)
        return None


def encrypt_bytes(data: bytes) -> str:
    """Return 'v1.<nonce>.<ciphertext+tag>' or empty string if unavailable."""
    key = _load_key()
    if key is None:
        return ""
    try:
        nonce = os.urandom(12)
        ct = AESGCM(key).encrypt(nonce, data, b"medglass")
        return _PREFIX + base64.b64encode(nonce).decode() + "." + base64.b64encode(ct).decode()
    except Exception as exc:
        LOG.error("encrypt failed: %s", exc)
        return ""


def encrypt_text(text: str) -> str:
    return encrypt_bytes(text.encode("utf-8"))


def is_encrypted(data: str | bytes) -> bool:
    s = data if isinstance(data, str) else data.decode("utf-8", "replace")
    return s.startswith(_PREFIX)


def decrypt_bytes(token: str) -> bytes:
    key = _load_key()
    if key is None:
        raise RuntimeError("encryption key unavailable")
    try:
        body = token[len(_PREFIX):]
        nonce_b64, ct_b64 = body.split(".", 1)
        nonce = base64.b64decode(nonce_b64)
        ct = base64.b64decode(ct_b64)
        return AESGCM(key).decrypt(nonce, ct, b"medglass")
    except Exception as exc:
        raise ValueError(f"decrypt failed: {exc}") from exc


def decrypt_text(token: str) -> str:
    return decrypt_bytes(token).decode("utf-8")
