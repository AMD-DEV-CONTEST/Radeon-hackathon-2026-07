from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
import hashlib
import hmac
import json
import re
from typing import Any

from glass_gateway.config import Settings, get_settings


_SAFE_USER_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_current_user_id: ContextVar[str | None] = ContextVar(
    "beaver_current_user_id",
    default=None,
)


@dataclass(frozen=True)
class UserPrincipal:
    user_id: str
    display_name: str
    token_digest: str


class UserTokenRegistry:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._by_digest: dict[str, UserPrincipal] = {}
        self._by_user_id: dict[str, UserPrincipal] = {}
        raw = self.settings.user_tokens_json.get_secret_value().strip()
        self.multi_user_enabled = bool(raw)
        if raw:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError("USER_TOKENS_JSON must be valid JSON") from exc
            if not isinstance(payload, dict):
                raise ValueError("USER_TOKENS_JSON must be an object keyed by token")
            for token, value in payload.items():
                if not isinstance(value, dict):
                    raise ValueError("each USER_TOKENS_JSON value must be an object")
                self._add(
                    token=str(token),
                    user_id=str(value.get("user_id") or ""),
                    display_name=str(value.get("display_name") or value.get("user_id") or ""),
                )
        else:
            self._add(
                token=self.settings.device_token,
                user_id=self.settings.everos_user_id,
                display_name="默认用户",
            )

    @staticmethod
    def digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _add(self, *, token: str, user_id: str, display_name: str) -> None:
        token = token.strip()
        user_id = user_id.strip()
        if not token:
            raise ValueError("user token must not be empty")
        if not _SAFE_USER_ID.fullmatch(user_id):
            raise ValueError(f"invalid user_id in USER_TOKENS_JSON: {user_id!r}")
        digest = self.digest(token)
        if digest in self._by_digest:
            raise ValueError("duplicate user token")
        if user_id in self._by_user_id:
            raise ValueError(f"duplicate user_id in USER_TOKENS_JSON: {user_id}")
        principal = UserPrincipal(
            user_id=user_id,
            display_name=display_name.strip() or user_id,
            token_digest=digest,
        )
        self._by_digest[digest] = principal
        self._by_user_id[user_id] = principal

    def principals(self) -> list[UserPrincipal]:
        return list(self._by_user_id.values())

    def principal_for_user(self, user_id: str) -> UserPrincipal | None:
        return self._by_user_id.get(user_id)

    def authenticate_token(self, token: str | None) -> UserPrincipal | None:
        if not token:
            return None
        digest = self.digest(token.strip())
        for expected, principal in self._by_digest.items():
            if hmac.compare_digest(expected, digest):
                return principal
        return None

    def authenticate_authorization(self, authorization: str | None) -> UserPrincipal | None:
        if not authorization or not authorization.startswith("Bearer "):
            return None
        return self.authenticate_token(authorization[7:])

    def authenticate_cookie(self, cookie_value: str | None) -> UserPrincipal | None:
        if not cookie_value:
            return None
        for expected, principal in self._by_digest.items():
            if hmac.compare_digest(expected, cookie_value):
                return principal
        return None

    def bind(self, principal: UserPrincipal) -> Token:
        return _current_user_id.set(principal.user_id)

    def bind_authorization(self, authorization: str | None) -> UserPrincipal | None:
        principal = self.authenticate_authorization(authorization)
        if principal is not None:
            self.bind(principal)
        return principal

    def reset(self, token: Token) -> None:
        _current_user_id.reset(token)

    def current_user_id(self) -> str | None:
        return _current_user_id.get()

    def current_principal(self) -> UserPrincipal | None:
        user_id = self.current_user_id()
        return self._by_user_id.get(user_id) if user_id else None

    def authorized(self, authorization: str | None) -> bool:
        # A valid HttpOnly login cookie is bound by middleware before the route.
        if self.current_principal() is not None:
            return True
        return self.authenticate_authorization(authorization) is not None

    def authorized_device(self, authorization: str | None) -> bool:
        principal = self.authenticate_authorization(authorization)
        if principal is None:
            return False
        current = self.current_principal()
        return current is None or current.user_id == principal.user_id

    def public_users(self) -> list[dict[str, Any]]:
        return [
            {"user_id": item.user_id, "display_name": item.display_name}
            for item in self.principals()
        ]


auth_registry = UserTokenRegistry()
