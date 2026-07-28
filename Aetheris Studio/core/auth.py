"""Local authentication for Aetheris.

Single local-admin account for now, credentials in a local JSON file
(never plaintext -- PBKDF2-SHA256 hash + per-account random salt). Designed
to grow into a database-backed multi-user system later without changing
the surface the rest of the app already depends on: `AuthManager` (used by
`core/utils/tool_security.py`, `core/utils/builtin_actions.py`) and
`RESERVED_USERNAMES` (used by `core/utils/task_scheduler.py`).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from pathlib import Path
from typing import Optional

from core.atomic_io import atomic_read_json, atomic_write_json
from core.platform_compat import safe_chmod
from core.utils.constants import DATA_DIR

# Names a real account may never register as -- keeps `owner` strings that
# already mean something special elsewhere (the "no owner"/system/public
# sentinels used throughout core/utils/*) from colliding with a real login.
RESERVED_USERNAMES = {"admin", "system", "root", "owner", "public", "anonymous", ""}

_CREDENTIALS_FILE = Path(DATA_DIR) / "auth_local.json"
# OWASP's 2023 minimum recommendation for PBKDF2-HMAC-SHA256.
_PBKDF2_ITERATIONS = 600_000


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS).hex()


class AuthManager:
    """Single local-admin credential store backed by a JSON file
    (`{DATA_DIR}/auth_local.json`: `{username, salt_hex, hash_hex}`, never
    the plaintext password). A future DB-backed, multi-user `AuthManager`
    only needs to keep this same `is_configured`/`is_admin`/`verify`/
    `set_credentials` surface for every existing caller to keep working.
    """

    def __init__(self, credentials_file: Optional[Path] = None):
        self._file = credentials_file or _CREDENTIALS_FILE

    @property
    def is_configured(self) -> bool:
        """True once a local admin account has been created."""
        return self._file.is_file()

    def _load(self) -> Optional[dict]:
        return atomic_read_json(self._file, default=None)

    def set_credentials(self, username: str, password: str) -> None:
        """Create or replace the single local admin account."""
        username = (username or "").strip()
        if not username:
            raise ValueError("username is required")
        if username.lower() in RESERVED_USERNAMES:
            raise ValueError(f"'{username}' is a reserved username")
        if not password or len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        salt = secrets.token_bytes(16)
        atomic_write_json(self._file, {
            "username": username,
            "salt": salt.hex(),
            "hash": _hash_password(password, salt),
        })
        # No-op on Windows today (core.platform_compat.safe_chmod only acts on
        # POSIX) -- real per-file ACL tightening on Windows is a separate,
        # bigger piece of work (win32security/icacls), not covered by this
        # call. Kept so the credential file is at least owner-only on any
        # POSIX deployment, and so this isn't silently forgotten later.
        safe_chmod(self._file, 0o600)

    def verify(self, username: str, password: str) -> bool:
        """Check a login attempt against the stored account."""
        data = self._load()
        if not data:
            return False
        if not hmac.compare_digest(data.get("username", ""), username or ""):
            return False
        try:
            salt = bytes.fromhex(data["salt"])
        except (KeyError, ValueError):
            return False
        candidate = _hash_password(password or "", salt)
        return hmac.compare_digest(candidate, data.get("hash", ""))

    def is_admin(self, owner: str) -> bool:
        """Whether `owner` (an already-authenticated username) is the local
        admin. There's only one account today, so this is just identity."""
        data = self._load()
        if not data:
            return False
        return hmac.compare_digest(data.get("username", ""), owner or "")

    def ensure_configured(self) -> Optional[tuple[str, str]]:
        """Idempotent first-run bootstrap: if no local account exists yet,
        generate a random username + strong password and create it. Returns
        the plaintext `(username, password)` pair exactly once, on the run
        that actually created the account -- returns `None` on every
        subsequent call (`is_configured` is already true by then), since
        the plaintext password is never recoverable from the stored hash.
        Callers that need to surface the generated credentials to the user
        (writing them to a file, printing them) must do so on that one
        call; there is no second chance."""
        if self.is_configured:
            return None
        username = f"aetheris-{secrets.token_hex(3)}"
        password = secrets.token_urlsafe(18)
        self.set_credentials(username, password)
        return username, password

    def current_username(self) -> Optional[str]:
        """The configured local account's username, or None if no account
        exists yet. Single-user app: until a real multi-user login flow
        replaces it (Restriction #8), every request from this machine acts
        as this one account -- the same trust boundary a desktop app's own
        OS-level user session already implies. Fixes a real bug found while
        building the Settings/login UI: the live `/v1/chat/completions/
        stream` endpoint never passed any `owner` to stream_agent_loop, so
        `owner_is_admin_or_single_user(None)` always failed and every
        sensitive tool (edit_file included) was silently blocked in the
        actual running app, not just in ad-hoc test scripts that happened
        to pass owner='prisc' by hand."""
        data = self._load()
        return data.get("username") if data else None
