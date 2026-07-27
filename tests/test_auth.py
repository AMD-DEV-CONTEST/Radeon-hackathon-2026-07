import pytest

from xianglens.auth import SessionIssueLimiter, SessionTokenError, SessionTokenManager


def test_session_token_expiry_and_signature_validation() -> None:
    manager = SessionTokenManager("a-long-random-permanent-key-for-tests", ttl_minutes=10)
    token, claims = manager.issue(now=1_000)

    assert manager.verify(token, now=claims.expires_at - 1) == claims
    with pytest.raises(SessionTokenError, match="expired"):
        manager.verify(token, now=claims.expires_at)
    with pytest.raises(SessionTokenError, match="Invalid access token"):
        manager.verify(f"{token[:-1]}x", now=1_001)


def test_session_issue_limiter_returns_retry_delay() -> None:
    limiter = SessionIssueLimiter(limit_per_minute=2)

    assert limiter.retry_after("visitor", now=100.0) == 0
    assert limiter.retry_after("visitor", now=101.0) == 0
    assert limiter.retry_after("visitor", now=102.0) == 58
    assert limiter.retry_after("visitor", now=160.0) == 0
