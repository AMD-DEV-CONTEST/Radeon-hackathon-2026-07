"""Per-user accounts with scrypt password hashing and lockout.

Stored in ``output/users.json`` (perms 0600). Roles: ``admin``, ``clinician``.
On first run, if no users exist, the configured login user is seeded (so the
existing single-credential deployment migrates cleanly to hashed storage).
"""

from __future__ import annotations

import base64
import hmac
import hashlib
import json
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from utils import write_json

LOG = logging.getLogger("medglass.users")

USERS_FILE = Path("output") / "users.json"
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
DK_LEN = 64
ROLES = ("admin", "clinician")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load() -> dict:
    if not USERS_FILE.exists():
        return {}
    try:
        data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        LOG.warning("users.json unreadable; starting empty", exc_info=True)
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    write_json(USERS_FILE, data)
    try:
        USERS_FILE.chmod(0o600)
    except Exception:
        pass


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"),
                          salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
                          dklen=DK_LEN)


def create_user(username: str, password: str, role: str = "clinician") -> dict:
    """Create or overwrite a user; returns the stored record."""
    if role not in ROLES:
        role = "clinician"
    salt = os.urandom(16)
    data = _load()
    existing = data.get(username, {})
    data[username] = {
        "salt": base64.b64encode(salt).decode(),
        "hash": base64.b64encode(_hash(password, salt)).decode(),
        "role": role,
        "created_at": existing.get("created_at") or _now_iso(),
        "failed": 0,
        "locked_until": "",
        "totp_secret": existing.get("totp_secret", ""),
        "totp_enabled": bool(existing.get("totp_enabled", False)),
    }
    _save(data)
    LOG.info("user %r upserted (role=%s)", username, role)
    return data[username]


def verify(username: str, password: str) -> dict | None:
    """Return the user record on success, or a locked/failed marker dict.

    Returns None if the username is unknown. On wrong password, increments the
    failure counter and returns {"error": ...} style record without secrets.
    """
    data = _load()
    rec = data.get(username)
    if not rec:
        return None
    try:
        salt = base64.b64decode(rec["salt"])
        expected = base64.b64decode(rec["hash"])
    except Exception:
        return None

    now = time.time()
    if rec.get("locked_until"):
        try:
            if now < float(rec["locked_until"]):
                return {"locked": True}
        except Exception:
            pass

    if hmac.compare_digest(_hash(password, salt), expected):
        if rec.get("failed"):
            rec["failed"] = 0
            rec["locked_until"] = ""
            data[username] = rec
            _save(data)
        return rec
    return {"failed": True}


def record_failure(username: str, max_attempts: int, lock_minutes: int) -> None:
    data = _load()
    rec = data.get(username)
    if not rec:
        return
    rec["failed"] = int(rec.get("failed", 0)) + 1
    if rec["failed"] >= max_attempts:
        rec["locked_until"] = str(time.time() + lock_minutes * 60)
        rec["failed"] = 0
        LOG.warning("user %r locked for %s min after repeated failures",
                    username, lock_minutes)
    data[username] = rec
    _save(data)


def get_user(username: str) -> dict | None:
    """Return the stored record or None."""
    return _load().get(username)


def list_users() -> dict[str, dict]:
    """All accounts (hash omitted)."""
    data = _load()
    out = {}
    for u, rec in data.items():
        out[u] = {
            "role": rec.get("role", "clinician"),
            "created_at": rec.get("created_at", ""),
            "totp_enabled": bool(rec.get("totp_enabled", False)),
            "locked": bool(rec.get("locked_until")),
        }
    return out


def set_role(username: str, role: str) -> bool:
    """Change a user's role without touching the password hash."""
    if role not in ROLES:
        return False
    data = _load()
    rec = data.get(username)
    if not rec:
        return False
    rec["role"] = role
    data[username] = rec
    _save(data)
    LOG.info("user %r role -> %s", username, role)
    return True


def set_totp(username: str, secret_b32: str | None) -> None:
    """Enable (secret given) or disable (secret None) TOTP for a user."""
    data = _load()
    rec = data.get(username)
    if not rec:
        return
    rec["totp_secret"] = secret_b32 or ""
    rec["totp_enabled"] = bool(secret_b32)
    data[username] = rec
    _save(data)
    LOG.info("user %r totp %s", username, "enabled" if secret_b32 else "disabled")


def set_totp_pending(username: str, secret_b32: str) -> None:
    """Stage a new TOTP secret; it becomes active only after confirmation."""
    data = _load()
    rec = data.get(username)
    if not rec:
        return
    rec["totp_pending"] = secret_b32
    data[username] = rec
    _save(data)


def confirm_totp(username: str) -> bool:
    """Activate a staged TOTP secret (called after a valid code is shown)."""
    data = _load()
    rec = data.get(username)
    if not rec or not rec.get("totp_pending"):
        return False
    rec["totp_secret"] = rec["totp_pending"]
    rec["totp_pending"] = ""
    rec["totp_enabled"] = True
    data[username] = rec
    _save(data)
    LOG.info("user %r totp confirmed", username)
    return True


def cancel_totp_pending(username: str) -> None:
    """Drop a staged (unconfirmed) TOTP secret."""
    data = _load()
    rec = data.get(username)
    if not rec or not rec.get("totp_pending"):
        return
    rec["totp_pending"] = ""
    data[username] = rec
    _save(data)


def delete_user(username: str) -> bool:
    """Remove a user account (admin only)."""
    data = _load()
    if username not in data:
        return False
    del data[username]
    _save(data)
    LOG.warning("user %r deleted", username)
    return True


def seed(default_user: str, default_password: str) -> None:
    """Create the default admin user when the store is empty.

    No password is baked into the source: if none was configured via
    MEDGLASS_LOGIN_PASSWORD, a random one-time password is generated and
    written to the server log so the operator can sign in on first boot.
    """
    if _load():
        return
    if not default_user:
        default_user = "clinician"
    if not default_password:
        default_password = secrets.token_urlsafe(12)
        LOG.warning(
            "No login password configured. Generated one-time password for "
            "%r (set MEDGLASS_LOGIN_PASSWORD to control it): %s",
            default_user, default_password)
    create_user(default_user, default_password, role="admin")
    LOG.info("seeded default user %r (admin)", default_user)
