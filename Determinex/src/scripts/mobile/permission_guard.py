"""
Permission guard for mobile agents.
Dangerous Android permissions require explicit confirmation before grant.
"""

from __future__ import annotations

import logging
import subprocess

log = logging.getLogger(__name__)

# Android dangerous permissions that require user confirmation
_DANGEROUS_PERMISSIONS: frozenset[str] = frozenset(
    {
        "android.permission.READ_CONTACTS",
        "android.permission.WRITE_CONTACTS",
        "android.permission.ACCESS_FINE_LOCATION",
        "android.permission.ACCESS_COARSE_LOCATION",
        "android.permission.ACCESS_BACKGROUND_LOCATION",
        "android.permission.READ_CALL_LOG",
        "android.permission.WRITE_CALL_LOG",
        "android.permission.READ_SMS",
        "android.permission.SEND_SMS",
        "android.permission.RECEIVE_SMS",
        "android.permission.CAMERA",
        "android.permission.RECORD_AUDIO",
        "android.permission.READ_EXTERNAL_STORAGE",
        "android.permission.WRITE_EXTERNAL_STORAGE",
        "android.permission.READ_PHONE_STATE",
        "android.permission.CALL_PHONE",
        "android.permission.USE_BIOMETRIC",
        "android.permission.USE_FINGERPRINT",
        "android.permission.BODY_SENSORS",
        "android.permission.PROCESS_OUTGOING_CALLS",
    }
)

# Permissions that are always blocked (covert surveillance categories)
_ALWAYS_BLOCKED_PERMISSIONS: frozenset[str] = frozenset(
    {
        "android.permission.ACCESS_BACKGROUND_LOCATION",  # covert location tracking
        "android.permission.READ_SMS",  # privacy violation
        "android.permission.PROCESS_OUTGOING_CALLS",  # call interception
    }
)


def check_permission_grant(permission: str) -> tuple[str, str]:
    """
    Returns (decision, reason) where decision is "ALLOW", "REQUIRE_CONFIRMATION", or "BLOCK".
    """
    if permission in _ALWAYS_BLOCKED_PERMISSIONS:
        return (
            "BLOCK",
            f"permission {permission} is categorically blocked (covert surveillance / privacy)",
        )
    if permission in _DANGEROUS_PERMISSIONS:
        return (
            "REQUIRE_CONFIRMATION",
            f"permission {permission} is a dangerous permission requiring confirmation",
        )
    return "ALLOW", "ok"


def grant_permission(serial: str, package: str, permission: str) -> tuple[bool, str]:
    """
    Grant a permission via adb. Call check_permission_grant first.
    """
    decision, reason = check_permission_grant(permission)
    if decision == "BLOCK":
        log.warning("[permission_guard] BLOCKED grant %s to %s: %s", permission, package, reason)
        return False, reason
    if decision == "REQUIRE_CONFIRMATION":
        log.warning(
            "[permission_guard] permission %s requires confirmation — not auto-granting", permission
        )
        return False, f"REQUIRE_CONFIRMATION: {reason}"
    try:
        result = subprocess.run(
            ["adb", "-s", serial, "shell", "pm", "grant", package, permission],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0, result.stderr or "ok"
    except Exception as exc:
        return False, str(exc)


def revoke_permission(serial: str, package: str, permission: str) -> bool:
    try:
        result = subprocess.run(
            ["adb", "-s", serial, "shell", "pm", "revoke", package, permission],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False
