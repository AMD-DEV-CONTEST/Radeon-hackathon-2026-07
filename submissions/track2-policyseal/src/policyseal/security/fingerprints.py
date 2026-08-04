from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from policyseal.security.key_store import MasterKeyStore


def _field(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return len(encoded).to_bytes(4, "big") + encoded


@dataclass(frozen=True, slots=True)
class KeyedFingerprinter:
    key_store: MasterKeyStore

    def digest(self, purpose: str, value: str, *, scope: str = "") -> str:
        if not purpose.strip() or not value:
            raise ValueError("fingerprint purpose and value must not be blank")
        message = b"policyseal-hmac-v1" + _field(purpose) + _field(scope) + _field(value)
        return hmac.new(self.key_store.load_or_create(), message, hashlib.sha256).hexdigest()

    def matches(self, expected: str, purpose: str, value: str, *, scope: str = "") -> bool:
        actual = self.digest(purpose, value, scope=scope)
        return hmac.compare_digest(expected, actual)
