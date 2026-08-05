"""One boolean was carrying four different facts. This is the differentiation.

Ryan, on being told the same Google account works in Antigravity and not through gemini-cli: "so we
need a way to differentiate it all yes?" Yes -- and 2026-07-31 produced three distinct states on one
machine within an hour, all of which `logged_in: true` reported identically:

    claude-code   credential present, provider honours it, answered in 5.4s
    gemini-cli    credential present, no auth method selected -> refused locally, no network call
    gemini-cli    credential present AND method selected, and the PROVIDER refused the client:
                  "IneligibleTierError: This client is no longer supported for Gemini Code Assist
                  for individuals"

The third is the one that matters most. No local check can ever discover it -- the credential is
valid and its token literally refreshed on the attempt -- and its remedy (a different auth method
entirely) resembles neither "log in" nor "install the CLI". Collapsing it into "logged in" told the
user the agent was ready; collapsing it into "auth error" would tell them to re-authenticate, which
cannot work.

So readiness is a named state, a live verdict is remembered rather than re-inferred, and the states
that require a real call are only ever set BY a real call.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import determinex_agents as agents  # noqa: E402


@pytest.fixture()
def probe_store(tmp_path, monkeypatch):
    """Point the store at a temp file so tests never read this machine's real verdicts."""
    store = tmp_path / "agent_probe_results.json"
    monkeypatch.setattr(agents, "_probe_store_path", lambda: store)
    return store


def _row(**over):
    row = {"installed": True, "logged_in": True, "detail": ""}
    row.update(over)
    return row


class TestProbeStore:
    def test_a_verdict_round_trips(self, probe_store):
        agents.record_probe_result("codex", "ok", "replied OK", at="2026-07-31T18:00:00Z")
        assert agents.last_probe_result("codex") == {
            "status": "ok",
            "detail": "replied OK",
            "at": "2026-07-31T18:00:00Z",
        }

    def test_an_unprobed_agent_has_no_verdict(self, probe_store):
        assert agents.last_probe_result("codex") == {}

    def test_a_later_verdict_replaces_the_earlier_one(self, probe_store):
        agents.record_probe_result("codex", "ok", "fine")
        agents.record_probe_result("codex", "quota_exhausted", "out of credits")
        assert agents.last_probe_result("codex")["status"] == "quota_exhausted"

    def test_agents_do_not_overwrite_each_other(self, probe_store):
        agents.record_probe_result("codex", "ok", "a")
        agents.record_probe_result("claude-code", "quota_exhausted", "b")
        assert agents.last_probe_result("codex")["status"] == "ok"
        assert agents.last_probe_result("claude-code")["status"] == "quota_exhausted"

    def test_a_corrupt_store_reads_as_never_probed(self, probe_store):
        probe_store.parent.mkdir(parents=True, exist_ok=True)
        probe_store.write_text("{ not json", encoding="utf-8")
        assert agents.last_probe_result("codex") == {}

    def test_a_corrupt_store_can_still_be_written_to(self, probe_store):
        """A roster that cannot record today's probe because of yesterday's junk is stuck."""
        probe_store.parent.mkdir(parents=True, exist_ok=True)
        probe_store.write_text("[]", encoding="utf-8")
        agents.record_probe_result("codex", "ok")
        assert agents.last_probe_result("codex")["status"] == "ok"

    def test_a_timestamp_is_always_recorded(self, probe_store):
        """A claim of "verified" is worthless without when."""
        entry = agents.record_probe_result("codex", "ok")
        assert entry["at"].endswith("Z")
        assert len(entry["at"]) == 20


class TestReadinessDifferentiates:
    def test_a_missing_cli_is_not_a_login_problem(self, probe_store):
        state, _ = agents._readiness(_row(installed=False, logged_in=False), "cursor-agent")
        assert state == agents.READY_NOT_INSTALLED

    def test_no_credentials(self, probe_store):
        state, _ = agents._readiness(_row(logged_in=False, detail="no stored credentials"), "aider")
        assert state == agents.READY_NO_CREDENTIALS

    def test_a_missing_auth_method_is_its_own_state(self, probe_store):
        """Distinct from no_credentials: the credential exists and is perfectly good."""
        state, evidence = agents._readiness(
            _row(
                logged_in=False,
                detail="credentials found but no auth method selected -- gemini-cli will refuse",
            ),
            "gemini-cli",
        )
        assert state == agents.READY_NO_AUTH_METHOD
        assert "auth method" in evidence

    def test_credentials_alone_are_unverified_not_working(self, probe_store):
        """The overclaim, named: nothing has confirmed the provider accepts them."""
        state, evidence = agents._readiness(_row(detail="stored credentials found"), "codex")
        assert state == agents.READY_CREDENTIALS_UNVERIFIED
        assert evidence

    def test_a_passing_probe_makes_it_verified_and_says_when(self, probe_store):
        agents.record_probe_result("codex", "ok", "replied OK", at="2026-07-31T18:00:00Z")
        state, evidence = agents._readiness(_row(), "codex")
        assert state == agents.READY_VERIFIED
        assert "2026-07-31T18:00:00Z" in evidence

    def test_a_provider_refusal_outranks_perfect_local_credentials(self, probe_store):
        """THE case. The credentials are valid and refresh; Google declines the client."""
        agents.record_probe_result(
            "gemini-cli",
            "provider_refused",
            "IneligibleTierError: no longer supported for Gemini Code Assist for individuals",
            at="2026-07-31T18:08:00Z",
        )

        state, evidence = agents._readiness(
            _row(detail="auth method 'oauth-personal', stored credentials found"), "gemini-cli"
        )

        assert state == agents.READY_PROVIDER_REFUSED, (
            "the local credentials looked perfect, which is precisely why this must not read as ready"
        )
        assert "IneligibleTier" in evidence

    def test_quota_exhaustion_outranks_local_credentials_too(self, probe_store):
        agents.record_probe_result("codex", "quota_exhausted", "credits depleted")
        state, _ = agents._readiness(_row(detail="Logged in using ChatGPT"), "codex")
        assert state == agents.READY_QUOTA_EXHAUSTED

    def test_a_failed_probe_is_reported_as_failed(self, probe_store):
        agents.record_probe_result("codex", "timeout", "no response in 45s")
        state, evidence = agents._readiness(_row(), "codex")
        assert state == agents.READY_FAILED
        assert "45s" in evidence

    def test_an_unknown_probe_status_does_not_become_a_claim(self, probe_store):
        """A status a future version emits must not be guessed into verified."""
        agents.record_probe_result("codex", "some_future_status", "?")
        state, _ = agents._readiness(_row(), "codex")
        assert state == agents.READY_CREDENTIALS_UNVERIFIED

    def test_a_stale_pass_does_not_survive_uninstalling_the_cli(self, probe_store):
        agents.record_probe_result("codex", "ok", "replied OK")
        state, _ = agents._readiness(_row(installed=False, logged_in=False), "codex")
        assert state == agents.READY_NOT_INSTALLED

    def test_every_state_is_one_of_the_declared_names(self, probe_store):
        declared = {
            agents.READY_NOT_INSTALLED,
            agents.READY_NO_CREDENTIALS,
            agents.READY_NO_AUTH_METHOD,
            agents.READY_CREDENTIALS_UNVERIFIED,
            agents.READY_VERIFIED,
            agents.READY_PROVIDER_REFUSED,
            agents.READY_QUOTA_EXHAUSTED,
            agents.READY_FAILED,
        }
        for status in (
            "ok",
            "provider_refused",
            "quota_exhausted",
            "auth_error",
            "timeout",
            "error",
            "nonsense",
            "",
        ):
            agents.record_probe_result("codex", status, "d")
            state, _ = agents._readiness(_row(), "codex")
            assert state in declared, f"{status!r} produced an undeclared readiness {state!r}"


class TestTheRosterCarriesIt:
    def test_every_row_has_a_readiness_and_evidence(self, probe_store):
        for row in agents._agents_status_json():
            assert row["readiness"], f"{row['name']} has no readiness"
            assert row["readiness_evidence"], (
                f"{row['name']} claims {row['readiness']} with nothing to back it"
            )

    def test_the_probe_columns_exist_even_when_never_probed(self, probe_store):
        for row in agents._agents_status_json():
            assert "last_probe_status" in row
            assert "last_probe_at" in row

    def test_logged_in_is_kept_for_existing_callers(self, probe_store):
        for row in agents._agents_status_json():
            assert isinstance(row["logged_in"], bool)

    def test_a_refused_agent_reports_both_facts_at_once(self, probe_store):
        """The shape of the answer to Ryan's question: logged in AND refused, together."""
        agents.record_probe_result("gemini-cli", "provider_refused", "IneligibleTierError: ...")
        row = next(r for r in agents._agents_status_json() if r["name"] == "gemini-cli")
        if not row["installed"]:
            pytest.skip("gemini-cli is not installed on this host")
        assert row["readiness"] == agents.READY_PROVIDER_REFUSED
        assert row["last_probe_status"] == "provider_refused"
