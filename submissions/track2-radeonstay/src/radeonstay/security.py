from __future__ import annotations

import re
from typing import Literal

SensitiveMaterialKind = Literal["credential", "token", "payment_card"]

_SECRET_MARKERS = (
    "api key",
    "api-key",
    "api_key",
    "access token",
    "authorization:",
    "bearer ",
    "confirmation token",
    "confirmation_token",
    "credential",
    "identity token",
    "identity_token",
    "private key",
    "private-key",
    "private_key",
    "ssh key",
    "ssh-key",
    "ssh_key",
    "password",
    "passwd",
    "refresh token",
    "refresh_token",
    "secret key",
    "session_token",
    "synthetic_api_key",
    "begin openssh private key",
    "cvv",
    "cvc",
    "银行卡密码",
    "支付密码",
    "密码",
    "密钥",
    "私钥",
    "凭据",
    "口令",
)
_TOKEN_PATTERN = re.compile(
    r"\b(?:sk|ghp|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{12,}\b"
)
_SIGNED_TOKEN_PATTERN = re.compile(
    r"\b[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b"
)
_OPAQUE_TOKEN_PATTERN = re.compile(
    r"\b(?=[A-Za-z0-9_-]{28,}\b)(?=[A-Za-z0-9_-]*[a-z])"
    r"(?=[A-Za-z0-9_-]*[A-Z])(?=[A-Za-z0-9_-]*[0-9])"
    r"[A-Za-z0-9_-]{28,}\b"
)
_CARD_CANDIDATE_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


def _passes_luhn(value: str) -> bool:
    digits = [int(character) for character in value if character.isdigit()]
    if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def sensitive_material_kind(value: str) -> SensitiveMaterialKind | None:
    """Classify credential-shaped text before it reaches models or storage."""

    normalized = value.casefold()
    if any(marker in normalized for marker in _SECRET_MARKERS):
        return "credential"
    if (
        _TOKEN_PATTERN.search(value)
        or _SIGNED_TOKEN_PATTERN.search(value)
        or _OPAQUE_TOKEN_PATTERN.search(value)
    ):
        return "token"
    if any(
        _passes_luhn(match.group(0))
        for match in _CARD_CANDIDATE_PATTERN.finditer(value)
    ):
        return "payment_card"
    return None


def contains_sensitive_material(value: str) -> bool:
    """Return true for shared marker, token, JWT-like, opaque, or card evidence."""

    return sensitive_material_kind(value) is not None
