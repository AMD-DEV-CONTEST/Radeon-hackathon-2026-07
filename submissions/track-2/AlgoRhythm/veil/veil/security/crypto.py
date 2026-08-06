"""Encryption at rest.

Findings are the most sensitive artefact VEIL produces — a finding file is a
re-identification recipe. It is encrypted with a key derived from the operator
passphrase, held only in memory, and never written to disk in plaintext.

Fernet (AES-128-CBC + HMAC-SHA256) with PBKDF2-HMAC-SHA256 key derivation. Not
exotic, which is the point: this is the part of the system nobody should have
to review twice.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
from dataclasses import dataclass
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_ITERATIONS = 480_000   # OWASP guidance for PBKDF2-HMAC-SHA256


class DecryptionFailed(RuntimeError):
    pass


def derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=salt, iterations=_ITERATIONS
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


@dataclass
class Vault:
    """Holds the derived key for the lifetime of a session and no longer."""

    key: bytes
    salt: bytes

    @classmethod
    def create(cls, passphrase: str, salt: bytes | None = None) -> "Vault":
        salt = salt or os.urandom(16)
        return cls(key=derive_key(passphrase, salt), salt=salt)

    def encrypt(self, payload: Any) -> bytes:
        blob = json.dumps(payload, default=str).encode("utf-8")
        # Salt is prepended so a vault file is self-describing on reopen.
        return self.salt + Fernet(self.key).encrypt(blob)

    def decrypt(self, blob: bytes) -> Any:
        try:
            token = blob[16:]
            return json.loads(Fernet(self.key).decrypt(token))
        except (InvalidToken, ValueError, IndexError) as exc:
            raise DecryptionFailed("Wrong passphrase or corrupted vault file.") from exc

    @staticmethod
    def salt_from(blob: bytes) -> bytes:
        return blob[:16]

    def wipe(self) -> None:
        """Best-effort key removal. Python cannot guarantee this, so the real
        guarantee is that the key was never persisted in the first place."""
        self.key = secrets.token_bytes(len(self.key))


def write_vault(path: str, vault: Vault, payload: Any) -> None:
    with open(path, "wb") as fh:
        fh.write(vault.encrypt(payload))
    os.chmod(path, 0o600)


def read_vault(path: str, passphrase: str) -> Any:
    with open(path, "rb") as fh:
        blob = fh.read()
    vault = Vault.create(passphrase, salt=Vault.salt_from(blob))
    return vault.decrypt(blob)
