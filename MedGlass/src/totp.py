"""TOTP (RFC 6238) one-time codes using only the stdlib.

Used for optional two-factor auth. 6 digits, 30 s period, ±1 step tolerance,
HMAC-SHA1 (compatible with Google Authenticator / Aegis / 1Password).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time

_PERIOD = 30
_DIGITS = 6
_ISSUER = "MedGlass"


def generate_secret() -> str:
    """Base32 random secret for a new authenticator registration."""
    return base64.b32encode(os.urandom(20)).decode()


def _hotp(secret_b32: str, counter: int) -> str:
    key = base64.b32decode(secret_b32)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0]
            & 0x7FFFFFFF) % (10 ** _DIGITS)
    return f"{code:0{_DIGITS}d}"


def verify(secret_b32: str, code: str, window: int = 1) -> bool:
    code = (code or "").strip().replace(" ", "")
    if not code or not code.isdigit() or len(code) != _DIGITS:
        return False
    counter = int(time.time()) // _PERIOD
    for i in range(-window, window + 1):
        if hmac.compare_digest(_hotp(secret_b32, counter + i), code):
            return True
    return False


def otpauth_uri(secret_b32: str, user: str) -> str:
    import urllib.parse
    label = urllib.parse.quote(user)
    return (f"otpauth://totp/{_ISSUER}:{label}?"
            f"secret={secret_b32}&issuer={_ISSUER}&digits={_DIGITS}")
