"""Permission enforcement at the HTTP layer.

Role separation only matters if it is enforced. These tests assert that a
REDACTOR cannot request reasoning, and that the API refuses rather than
returning an empty field.
"""
from __future__ import annotations

import pytest

from veil.security.auth import CAPABILITIES, STORE, PermissionDenied, require
from veil.types import Role


@pytest.fixture
def sessions():
    STORE.set_credential(Role.AUDITOR, "auditor-pass")
    STORE.set_credential(Role.REDACTOR, "redactor-pass")
    STORE.set_credential(Role.VIEWER, "viewer-pass")
    return {
        Role.AUDITOR: STORE.login(Role.AUDITOR, "auditor-pass"),
        Role.REDACTOR: STORE.login(Role.REDACTOR, "redactor-pass"),
        Role.VIEWER: STORE.login(Role.VIEWER, "viewer-pass"),
    }


class TestCapabilityMatrix:
    def test_auditor_can_view_reasoning(self, sessions):
        require(sessions[Role.AUDITOR], "view_reasoning")

    def test_redactor_cannot_view_reasoning(self, sessions):
        with pytest.raises(PermissionDenied, match="view_reasoning"):
            require(sessions[Role.REDACTOR], "view_reasoning")

    def test_viewer_can_only_view_final_state(self, sessions):
        require(sessions[Role.VIEWER], "view_risk_score")
        with pytest.raises(PermissionDenied):
            require(sessions[Role.VIEWER], "view_findings")

    def test_redactor_can_propose_and_apply_edits(self, sessions):
        require(sessions[Role.REDACTOR], "propose_edits")
        require(sessions[Role.REDACTOR], "apply_edits")

    def test_only_auditor_can_view_audit_log(self, sessions):
        require(sessions[Role.AUDITOR], "view_audit")
        for role in (Role.REDACTOR, Role.VIEWER):
            with pytest.raises(PermissionDenied):
                require(sessions[role], "view_audit")


class TestSessionLifecycle:
    def test_passphrase_hash_is_salted_and_not_reversible(self):
        from veil.security.auth import hash_passphrase, verify_passphrase

        salt_a, digest_a = hash_passphrase("secret123")
        salt_b, digest_b = hash_passphrase("secret123")
        # Same passphrase, different salts, different digests.
        assert salt_a != salt_b and digest_a != digest_b
        assert verify_passphrase("secret123", salt_a, digest_a)
        assert not verify_passphrase("secret124", salt_a, digest_a)

    def test_wrong_passphrase_is_refused(self):
        from veil.security.auth import AuthError

        STORE.set_credential(Role.AUDITOR, "correct")
        with pytest.raises(AuthError, match="Invalid"):
            STORE.login(Role.AUDITOR, "wrong")

    def test_session_expires(self, sessions):
        s = sessions[Role.VIEWER]
        s.expires_at = 0
        assert s.expired

    def test_expired_session_is_refused_on_resolve(self, sessions):
        from veil.security.auth import AuthError

        s = sessions[Role.VIEWER]
        s.expires_at = 0
        with pytest.raises(AuthError, match="expired"):
            STORE.resolve(s.token)

    def test_forged_token_signature_is_refused(self, sessions):
        from veil.security.auth import AuthError

        real = sessions[Role.VIEWER].token
        raw, _, _ = real.rpartition(":")
        forged = raw.replace("viewer", "auditor") + ":" + "0" * 32
        with pytest.raises(AuthError, match="signature"):
            STORE.resolve(forged)

    def test_bootstrap_generates_distinct_random_passphrases(self):
        creds = STORE.bootstrap()
        assert set(creds) == {r.value for r in Role}
        assert len(set(creds.values())) == len(creds)
        assert all(len(p) >= 10 for p in creds.values())


class TestRoleProjectionAtHTTP:
    """The HTTP layer must call `Finding.redacted_for(role)` before JSON
    serialisation, or reasoning leaks to REDACTOR through the wire."""

    def test_context_project_strips_reasoning_for_redactor(self, sessions):
        from veil.security.auth import AuthContext
        from veil.types import Finding, Tier

        ctx = AuthContext(sessions[Role.REDACTOR])
        findings = [
            Finding(
                persona="Data-Broker", tier=Tier.CORRELATIONAL,
                claim="Role + city + tenure = 3 candidates",
                reasoning="Census data shows...",
                candidate_set_size=3,
            )
        ]
        projected = ctx.project(findings)
        assert "reasoning" not in projected[0]
        assert projected[0]["claim"] is not None

    def test_audit_actor_identifies_role_without_leaking_the_token(self, sessions):
        from veil.security.auth import AuthContext

        ctx = AuthContext(sessions[Role.AUDITOR])
        assert ctx.audit_actor.startswith("auditor:")
        assert sessions[Role.AUDITOR].token not in ctx.audit_actor
