"""
Phase H — JWT 认证服务

提供用户登录、Token 签发与验证的核心逻辑。
使用 HMAC-SHA256 签发的自包含 Token，不依赖外部 JWT 库。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time


# ---------------------------------------------------------------------------
# Token config
# ---------------------------------------------------------------------------

SECRET_KEY: str = os.environ.get("PROJECTPACK_SECRET", "projectpack-dev-secret-2026")
TOKEN_EXPIRE_SECONDS: int = 3600 * 24  # 24 hours


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

def _b64url_encode(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    import base64
    padding = 4 - (len(s) % 4)
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_token(user_id: str, username: str, display_name: str) -> str:
    """Create a self-signed JWT-like token using HMAC-SHA256."""
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    now = int(time.time())
    payload_data = {
        "sub": user_id,
        "username": username,
        "display_name": display_name,
        "iat": now,
        "exp": now + TOKEN_EXPIRE_SECONDS,
    }
    payload = _b64url_encode(json.dumps(payload_data).encode())
    signing_input = f"{header}.{payload}"
    signature = hmac.new(
        SECRET_KEY.encode(), signing_input.encode(), hashlib.sha256
    ).hexdigest()
    token = f"{header}.{payload}.{signature}"
    return token


def verify_token(token: str) -> dict | None:
    """Verify a token and return its payload, or None if invalid/expired."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, signature = parts
        signing_input = f"{header_b64}.{payload_b64}"
        expected_sig = hmac.new(
            SECRET_KEY.encode(), signing_input.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected_sig, signature):
            return None
        payload = json.loads(_b64url_decode(payload_b64))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def _hash_password(password: str, salt: bytes | None = None) -> str:
    if salt is None:
        salt = os.urandom(16)
    pk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return salt.hex() + ":" + pk.hex()


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against the stored salted hash."""
    try:
        salt_hex, pk_hex = stored_hash.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        pk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
        return hmac.compare_digest(pk.hex(), pk_hex)
    except (ValueError, IndexError):
        return False


# ---------------------------------------------------------------------------
# Auth service
# ---------------------------------------------------------------------------

class AuthService:
    """Handles authentication: login, token verification, and user lookup."""

    def __init__(self, db_path: str):
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def authenticate(self, username: str, password: str) -> dict | None:
        """Return token dict if credentials are valid, else None."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT id, username, display_name, password_hash, is_active "
                "FROM user_account WHERE username = ?",
                (username,),
            ).fetchone()
            if row is None:
                return None
            if not row["is_active"]:
                return None
            if not verify_password(password, row["password_hash"]):
                return None
            token = create_token(row["id"], row["username"], row["display_name"])
            return {
                "access_token": token,
                "token_type": "bearer",
                "user_id": row["id"],
                "username": row["username"],
                "display_name": row["display_name"],
            }
        finally:
            conn.close()

    def get_user(self, user_id: str) -> dict | None:
        """Get user profile by ID."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT id, username, display_name, is_active "
                "FROM user_account WHERE id = ?",
                (user_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "user_id": row["id"],
                "username": row["username"],
                "display_name": row["display_name"],
                "is_active": bool(row["is_active"]),
            }
        finally:
            conn.close()

    def list_users(self) -> list[dict]:
        """List all active users."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, username, display_name, is_active "
                "FROM user_account WHERE is_active = 1"
            ).fetchall()
            return [
                {
                    "user_id": r["id"],
                    "username": r["username"],
                    "display_name": r["display_name"],
                    "is_active": bool(r["is_active"]),
                }
                for r in rows
            ]
        finally:
            conn.close()
