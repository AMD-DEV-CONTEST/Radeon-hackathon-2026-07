"""
Filesystem guard for desktop agents — prevents VM-side file operations from
targeting sensitive host-accessible paths, and enforces VM filesystem isolation.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

# Paths that must never be written to, even inside a VM (defense-in-depth)
_BLOCKED_PATH_PATTERNS: list[re.Pattern] = [
    re.compile(r"^/etc/(passwd|shadow|sudoers|crontab|ssh/)", re.I),
    re.compile(r"^/root/"),
    re.compile(r"^/proc/"),
    re.compile(r"^/sys/"),
    re.compile(r"^/(boot|grub)/"),
    re.compile(r"C:\\Windows\\System32", re.I),
    re.compile(r"C:\\Users\\[^\\]+\\AppData\\Roaming\\Microsoft", re.I),
    re.compile(r"HKEY_LOCAL_MACHINE\\SAM", re.I),
    re.compile(r"HKEY_LOCAL_MACHINE\\SECURITY", re.I),
    # Network shares that might leak to host
    re.compile(r"\\\\[^\\]+\\[cC]\$"),
]

# Extensions that are never allowed to be written
_BLOCKED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".exe",
        ".dll",
        ".sys",
        ".drv",
        ".com",
        ".bat",
        ".cmd",
        ".msi",
        ".ps1",
        ".vbs",
        ".hta",
        ".scr",
        ".pif",
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
    }
)


def check_path(path: str, operation: str = "write") -> tuple[bool, str]:
    """
    Returns (allowed, reason).
    Call before any file operation from the desktop agent.
    """
    for pattern in _BLOCKED_PATH_PATTERNS:
        if pattern.search(path):
            log.warning(
                "[filesystem_guard] BLOCKED %s on path: %s (pattern: %s)",
                operation,
                path,
                pattern.pattern,
            )
            return False, f"path matches blocked pattern: {pattern.pattern}"

    if operation == "write":
        lower = path.lower()
        for ext in _BLOCKED_EXTENSIONS:
            if lower.endswith(ext):
                return False, f"blocked file extension for write: {ext}"

    return True, "ok"


def is_safe_for_corpus(path: str) -> tuple[bool, str]:
    """Check if a file path is safe to include as evidence in a corpus record."""
    # Strip local usernames from paths before storing
    sensitive_patterns = [
        re.compile(r"/home/[^/]+/", re.I),
        re.compile(r"C:\\Users\\[^\\]+\\", re.I),
    ]
    for p in sensitive_patterns:
        if p.search(path):
            return False, "path contains username/home directory"
    return True, "ok"


def sanitize_for_corpus(path: str) -> str:
    """Replace sensitive path components before storing in corpus."""
    path = re.sub(r"/home/[^/]+/", "/home/<user>/", path, flags=re.I)
    path = re.sub(r"C:\\Users\\[^\\]+\\", r"C:\\Users\\<user>\\", path, flags=re.I)
    return path
