"""
Permission control & privacy protection layer (AMD Track 2 capability #3).

Ported as-is (logic unchanged) from the production RugBuster scoring facade's
worker-to-engine auth (read-only reference: rugbuster-scoring-engine/rugbuster_scoring_engine/auth.py).
It was already chain-agnostic and secret-free, so this is a direct copy with
docs added to make its role in the agent explicit.

Every call into the CIA orchestrator (src/orchestrator.py) that crosses a
process/network boundary (e.g. a REST wrapper calling the agent) is expected
to carry an HMAC-SHA256 signature over (timestamp + "." + body), verified
here with a bounded clock-skew window and constant-time comparison. This is
what "permission control" means in this submission: only callers holding the
shared secret can invoke the agent's tools, and no request is trusted based
on network origin alone. Secret rotation (current + previous) lets the
deployer rotate the HMAC secret without a hard cutover.
"""

from __future__ import annotations

import hashlib
import hmac
import time

MAX_CLOCK_SKEW_SECONDS = 60


def sign(body: bytes, timestamp: str, secret: str) -> str:
    return hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def verify(body: bytes, timestamp: str, signature: str, current_secret: str, previous_secret: str | None = None) -> bool:
    try:
        if abs(time.time() - int(timestamp)) > MAX_CLOCK_SKEW_SECONDS:
            return False
    except (TypeError, ValueError):
        return False
    for secret in (current_secret, previous_secret):
        if secret and hmac.compare_digest(sign(body, timestamp, secret), signature):
            return True
    return False
