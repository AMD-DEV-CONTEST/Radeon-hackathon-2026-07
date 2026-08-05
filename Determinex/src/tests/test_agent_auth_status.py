""" "Logged in" must mean the agent can actually answer, not that a file exists.

FOUND BY RUNNING THEM 2026-07-31. All three cloud agents were probed through the same path the chat
room uses -- `determinex_agents.py resolve <agent> --chat`, then spawn. claude-code answered "OK" in
5.4s. codex answered "OK" in 7.7s. gemini-cli failed in 2.0s with rc=41:

    Please set an Auth method in your C:\\Users\\ryang\\.gemini\\settings.json or specify one of the
    following environment variables before running: GEMINI_API_KEY, GOOGLE_GENAI_USE_VERTEXAI,
    GOOGLE_GENAI_USE_GCA

Determinex's roster was reporting that agent as `logged_in: true, plan: "Google account"`, because
the check was "does oauth_creds.json exist and is it non-empty". The credentials were real; there
was no settings.json at all, so the CLI refused before making a single network call. That refusal is
deterministic and local, which makes it exactly the kind of thing the cheap status can know -- it
was simply not being looked at.

The same class as everything else this release pass turned up: a check reporting an outcome it never
established. This is the narrow, honest boundary -- a selected auth method plus a credential source
is checkable for free; whether the account is *entitled* to the product is not, and only the live
probe can find that (it is what surfaced Google's IneligibleTierError afterwards).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import determinex_agents as agents  # noqa: E402


@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    """An isolated HOME with no gemini state, and no auth env vars leaking in.

    Also reports every probed CLI as installed. These tests are about reading AUTH STATE
    off disk, and `_cheap_status` returns early with logged_in=False when the binary is
    absent -- so on a machine without the gemini CLI (every CI runner) the fixture's
    carefully written credentials were never consulted and the test asserted nothing about
    the code it names. Whether a CLI is installed is a different question, covered by
    `test_the_status_call_never_raises_on_the_real_machine`, which deliberately uses the
    real machine.
    """
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(agents.shutil, "which", lambda name, *a, **k: f"/usr/local/bin/{name}")
    for name in agents._GEMINI_AUTH_ENV:
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def _write(home: Path, *, creds: bool = False, settings: dict | None = None) -> None:
    g = home / ".gemini"
    g.mkdir(parents=True, exist_ok=True)
    if creds:
        (g / "oauth_creds.json").write_text('{"access_token": "x"}', encoding="utf-8")
    if settings is not None:
        (g / "settings.json").write_text(json.dumps(settings), encoding="utf-8")


class TestGeminiAuthState:
    def test_credentials_without_an_auth_method_is_not_logged_in(self, fake_home):
        """The measured regression, stated exactly."""
        _write(fake_home, creds=True)

        ok, method, detail = agents._gemini_auth_state()

        assert ok is False, "credentials alone were reported as logged in; the CLI refuses"
        assert method == ""
        assert "no auth method selected" in detail
        assert "settings.json" in detail and "GEMINI_API_KEY" in detail, (
            "a user told they are not logged in needs to be told what to set"
        )

    def test_credentials_plus_a_selected_method_is_logged_in(self, fake_home):
        _write(
            fake_home,
            creds=True,
            settings={"security": {"auth": {"selectedType": "oauth-personal"}}},
        )

        ok, method, detail = agents._gemini_auth_state()

        assert ok is True
        assert method == "oauth-personal"
        assert "not live-verified" in detail, (
            "the cheap check cannot know entitlement; it must not imply it did"
        )

    def test_the_legacy_settings_key_is_accepted(self, fake_home):
        """0.51 reads security.auth.selectedType and still migrates selectedAuthType."""
        _write(fake_home, creds=True, settings={"selectedAuthType": "oauth-personal"})
        ok, method, _ = agents._gemini_auth_state()
        assert (ok, method) == (True, "oauth-personal")

    def test_no_credentials_says_to_sign_in(self, fake_home):
        _write(fake_home, settings={"security": {"auth": {"selectedType": "oauth-personal"}}})
        ok, _method, detail = agents._gemini_auth_state()
        assert ok is False
        assert "no stored credentials" in detail

    def test_nothing_at_all_is_not_logged_in(self, fake_home):
        ok, method, detail = agents._gemini_auth_state()
        assert (ok, method) == (False, "")
        assert detail

    @pytest.mark.parametrize(
        "var", ["GEMINI_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_GENAI_USE_GCA"]
    )
    def test_an_env_var_is_both_method_and_credential(self, fake_home, monkeypatch, var):
        """No settings.json and no creds file needed -- the env var carries both halves."""
        monkeypatch.setenv(var, "value")

        ok, method, detail = agents._gemini_auth_state()

        assert ok is True
        assert method == var
        assert var in detail

    def test_a_whitespace_env_var_does_not_count(self, fake_home, monkeypatch):
        """Set-but-empty is the empty-credential shape this codebase guards elsewhere."""
        monkeypatch.setenv("GEMINI_API_KEY", "   ")
        ok, _method, _detail = agents._gemini_auth_state()
        assert ok is False

    def test_an_unreadable_settings_file_is_not_a_crash(self, fake_home):
        """A hand-edited settings.json must not make the roster unopenable."""
        _write(fake_home, creds=True)
        (fake_home / ".gemini" / "settings.json").write_text("{ not json", encoding="utf-8")

        ok, method, detail = agents._gemini_auth_state()

        assert (ok, method) == (False, "")
        assert "no auth method selected" in detail

    def test_settings_holding_a_non_object_is_not_a_crash(self, fake_home):
        _write(fake_home, creds=True)
        (fake_home / ".gemini" / "settings.json").write_text("[1,2,3]", encoding="utf-8")
        ok, _method, _detail = agents._gemini_auth_state()
        assert ok is False

    def test_an_empty_credentials_file_does_not_count(self, fake_home):
        g = fake_home / ".gemini"
        g.mkdir(parents=True)
        (g / "oauth_creds.json").write_text("", encoding="utf-8")
        (g / "settings.json").write_text(
            json.dumps({"security": {"auth": {"selectedType": "oauth-personal"}}}), encoding="utf-8"
        )

        ok, _method, detail = agents._gemini_auth_state()

        assert ok is False
        assert "no stored credentials" in detail


class TestTheRosterUsesIt:
    def test_the_gemini_row_follows_the_auth_state(self, fake_home):
        _write(fake_home, creds=True)  # credentials, no method

        row = agents._cheap_status(agents._AGENTS["gemini-cli"])

        assert row["auth_known"] is True, "we do know the answer; the answer is no"
        assert row["logged_in"] is False
        assert row["plan"] == "", "a plan name next to a broken auth reads as working"
        assert "no auth method selected" in row["detail"]

    def test_a_configured_gemini_reports_logged_in(self, fake_home):
        _write(
            fake_home,
            creds=True,
            settings={"security": {"auth": {"selectedType": "oauth-personal"}}},
        )

        row = agents._cheap_status(agents._AGENTS["gemini-cli"])

        assert row["logged_in"] is True
        assert row["plan"] == "Google account"

    def test_the_status_call_never_raises_on_the_real_machine(self):
        """Whatever this host's state is, the roster has to open."""
        for name in ("claude-code", "codex", "gemini-cli", "local-ollama"):
            row = agents._cheap_status(agents._AGENTS[name])
            assert row["name"] == name
            assert isinstance(row["logged_in"], bool)
            assert isinstance(row["detail"], str)
