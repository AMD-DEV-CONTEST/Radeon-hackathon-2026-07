from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Callable

from privateops.models import Confirmation, PermissionDecision

BLOCKED_TERMS = {
    "api key",
    "private key",
    "secret",
    "token",
    "password",
    "credential",
    "remote server",
    "upload secrets",
}

CONFIRM_TERMS = {
    "delete",
    "remove",
    "rewrite",
    "overwrite",
    "send email",
    "execute",
    "run command",
    "install",
    "modify",
    "file changes",
}

SAFE_TERMS = {
    "summarize",
    "explain",
    "search",
    "review",
    "read",
    "compare",
    "plan",
}


def _matches(text: str, terms: set[str]) -> list[str]:
    return sorted(term for term in terms if term in text)


def classify_intent(prompt: str) -> PermissionDecision:
    text = prompt.lower()
    blocked = _matches(text, BLOCKED_TERMS)
    if blocked and any(term in text for term in {"send", "upload", "remote server", "share"}):
        return PermissionDecision(
            level="blocked",
            reason="Potential secret exfiltration was detected.",
            requires_confirmation=True,
            matched_terms=blocked,
        )

    confirm = _matches(text, CONFIRM_TERMS)
    if confirm:
        return PermissionDecision(
            level="confirm",
            reason="The request appears to involve file changes or external side effects.",
            requires_confirmation=True,
            matched_terms=confirm,
        )

    safe = _matches(text, SAFE_TERMS)
    return PermissionDecision(
        level="safe",
        reason="Read-only or planning request; no external side effects detected.",
        requires_confirmation=False,
        matched_terms=safe,
    )


class ConfirmationStore:
    def __init__(
        self,
        ttl_seconds: int = 120,
        clock: Callable[[], datetime] | None = None,
    ):
        self.ttl_seconds = ttl_seconds
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._pending: dict[str, tuple[str, datetime]] = {}

    def issue(self, action: str) -> Confirmation:
        now = self.clock()
        expires_at = now + timedelta(seconds=self.ttl_seconds)
        token = secrets.token_urlsafe(24)
        self._pending[token] = (action, expires_at)
        return Confirmation(token=token, action=action, expires_at=expires_at.isoformat())

    def consume(self, token: str, action: str) -> bool:
        pending = self._pending.get(token)
        if not pending:
            return False
        expected_action, expires_at = pending
        if expected_action != action:
            return False
        self._pending.pop(token, None)
        return self.clock() <= expires_at
