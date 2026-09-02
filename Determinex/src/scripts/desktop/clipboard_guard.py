"""
Clipboard guard — prevents sensitive data from leaking through VM→host clipboard.
All clipboard reads/writes must go through this module.
"""

from __future__ import annotations

import logging
import re

from vision.visual_cloak import scan_text_for_pii

log = logging.getLogger(__name__)

_SECRET_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{48}\b"),
    re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{40,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b[A-Za-z0-9/+]{40}\b"),  # generic base64-like secrets
]


def is_safe_for_host(clipboard_text: str) -> tuple[bool, str]:
    """
    Returns (safe, reason).
    Checks clipboard content before allowing it to pass from VM to host scope.
    """
    pii_hits = scan_text_for_pii(clipboard_text)
    if pii_hits:
        categories = [h[0] for h in pii_hits]
        return False, f"clipboard contains PII/secrets: {categories}"

    for pattern in _SECRET_PATTERNS:
        if pattern.search(clipboard_text):
            return False, "clipboard contains likely secret token"

    return True, "ok"


def safe_read(clipboard_text: str, allow_unsafe: bool = False) -> str:
    """
    Read clipboard text, returning empty string if it contains secrets.
    Set allow_unsafe=True only in explicitly sandboxed test contexts.
    """
    if allow_unsafe:
        return clipboard_text
    safe, reason = is_safe_for_host(clipboard_text)
    if not safe:
        log.warning("[clipboard_guard] blocked clipboard read: %s", reason)
        return ""
    return clipboard_text


def safe_write(text: str) -> tuple[bool, str]:
    """
    Returns (allowed, reason).
    Use before writing to VM clipboard to prevent injecting secrets into the VM.
    """
    safe, reason = is_safe_for_host(text)
    if not safe:
        log.warning("[clipboard_guard] blocked clipboard write: %s", reason)
        return False, reason
    return True, "ok"
