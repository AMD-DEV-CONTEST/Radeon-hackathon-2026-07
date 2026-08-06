"""Egress guarantee — the structural claim that separates VEIL from tools
that promise not to phone home.

The promise is only credible if it can be tested, and the test must be able to
fail. This file ensures that a backdoor or a library upgrade that adds an
external call would be caught before demo day.
"""
from __future__ import annotations

import pytest

from veil.security.egress import EgressBlocked, check_host, egress_self_test


class TestAllowlist:
    def test_localhost_passes(self):
        assert check_host("http://localhost:8000/v1/models")

    def test_127_0_0_1_passes(self):
        assert check_host("http://127.0.0.1:6333/collections")

    def test_ipv6_loopback_passes(self):
        assert check_host("http://[::1]:8000/")

    def test_external_host_raises(self):
        with pytest.raises(EgressBlocked, match="not in the allowlist"):
            check_host("https://api.openai.com/v1/chat/completions")

    def test_sneaky_localhost_wannabe_raises(self):
        # "localhost.evil.com" contains the string "localhost" but is not loopback.
        with pytest.raises(EgressBlocked):
            check_host("http://localhost.evil.com/")

    def test_dns_rebinding_attempt_raises(self):
        # A hostname that might resolve to 127.0.0.1 now but something else later.
        with pytest.raises(EgressBlocked):
            check_host("http://anything-but-literal-loopback.test/")

    @pytest.mark.asyncio
    async def test_self_test_blocks_external_call(self):
        result = await egress_self_test("https://api.anthropic.com/v1/models")
        assert result.blocked, "Egress guard did not block an external request."
        assert "EgressBlocked" in result.detail or "allowlist" in result.detail


class TestTransportEnforcement:
    """The guard lives in the transport, so redirects and library retries are
    covered automatically — no second HTTP client can bypass it."""

    def test_redirects_are_not_followed(self):
        from veil.security.egress import guarded_async_client

        # If vLLM or Qdrant ever returned a 301 to an attacker-controlled URL,
        # the client would not follow it — a redirect is an egress attempt.
        client = guarded_async_client(timeout=1.0)
        assert client.follow_redirects is False

    def test_proxy_environment_variables_are_ignored(self):
        from veil.security.egress import guarded_async_client

        # HTTP_PROXY / HTTPS_PROXY would otherwise route every "local" call
        # through a third party.
        client = guarded_async_client(timeout=1.0)
        assert client.trust_env is False

    def test_transport_is_the_guarded_one(self):
        from veil.security.egress import GuardedTransport, guarded_async_client

        client = guarded_async_client(timeout=1.0)
        assert isinstance(client._transport, GuardedTransport)
