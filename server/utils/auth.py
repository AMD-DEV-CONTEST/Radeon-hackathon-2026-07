"""Reusable auth utility re-exports for application code."""

from api.auth.deps import (
    AdminUser,
    CurrentUser,
    RecruiterUser,
    get_current_active_user,
    get_current_user,
    require_roles,
)
from core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    decode_token,
    get_password_hash,
    hash_token,
    verify_password,
)

__all__ = [
    "AdminUser",
    "CurrentUser",
    "RecruiterUser",
    "create_access_token",
    "create_refresh_token",
    "decode_access_token",
    "decode_refresh_token",
    "decode_token",
    "get_current_active_user",
    "get_current_user",
    "get_password_hash",
    "hash_token",
    "require_roles",
    "verify_password",
]
