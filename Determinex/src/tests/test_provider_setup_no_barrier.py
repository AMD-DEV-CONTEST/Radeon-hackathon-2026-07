"""The first-run setup screen, judged by the least technical plausible user.

Ryan, 2026-08-03: *"I'm giving the world a magic box. The magic believers will try it and
something simple shouldn't fuck it up for them."* And: *"be dubious of the technical part,
like verify it all works so the average person doesn't get angry at an error."*

Every test here guards a rule that was BROKEN in the shipped wizard, not a hypothetical:

  * a machine with Claude, ChatGPT and 38 local models still led with "Get a key"
  * `ready` was going to mean "a credential exists", which for a depleted Google key means a
    green check followed by a failure on the user's first real request
  * Google appeared as a blank password field while the account it would use was sitting in
    `~/.gemini/google_accounts.json`
  * seven providers were seven equal blank fields, in alphabetical order

The detection functions are patched in every test. A setup report that changes its verdict
when someone installs Ollama is a report whose tests prove nothing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import determinex_provider_setup as ps  # noqa: E402


@pytest.fixture
def machine(monkeypatch):
    """A blank machine. Each test turns on only what it is about."""
    state = {"models": [], "ollama_up": False, "clis": {}, "keys": set(), "google": ("", "")}

    monkeypatch.setattr(ps, "_load_env_file", lambda: None)
    monkeypatch.setattr(ps, "_ollama_models", lambda: (state["models"], state["ollama_up"]))
    monkeypatch.setattr(ps, "_cli_readiness", lambda n: state["clis"].get(n, ("", "")))
    monkeypatch.setattr(ps, "_env_key", lambda *names: any(n in state["keys"] for n in names))
    monkeypatch.setattr(ps, "_google_identity", lambda: state["google"])
    monkeypatch.setattr(ps.shutil, "which", lambda n: None)
    return state


def _by_id(report):
    return {o["id"]: o for o in report.options}


# ── the screen's job is to END ──────────────────────────────────────────────────────────


def test_a_finished_setup_recommends_nothing(machine):
    """The exact bug: three working providers, and the screen still sold a fourth."""
    machine["models"] = ["qwen2.5-coder:7b"]
    machine["clis"] = {"claude-code": ("verified", "me@example.com"),
                       "codex": ("verified", "Logged in")}

    report = ps.build_report()

    assert report.recommended is None, (
        f"nothing left to do, but the screen still recommends {report.recommended}"
    )
    assert report.ready_count == 3
    assert "ready to go" in report.headline.lower()


def test_an_empty_machine_leads_with_exactly_one_action(machine):
    report = ps.build_report()

    assert report.ready_count == 0
    assert report.recommended is not None
    assert report.headline.startswith("One step"), report.headline


def test_local_wins_ties_because_it_needs_no_account(machine):
    """Ranked by what the user must understand — and local cannot expire or run out."""
    machine["ollama_up"] = True

    rec = ps.build_report().recommended

    assert rec["id"] == "local"
    assert rec["private"] is True


# ── ready means a call succeeded, never "a credential exists" ───────────────────────────


def test_a_saved_key_is_never_reported_ready(machine):
    """Proven on this repo: a valid GEMINI_API_KEY with zero credits looks identical."""
    machine["keys"] = {"GEMINI_API_KEY", "OPENROUTER_API_KEY"}

    opts = _by_id(ps.build_report())

    for pid in ("google", "openrouter"):
        assert opts[pid]["ready"] is False, f"{pid} claimed ready on a key nobody called"
        assert opts[pid]["readiness"] == "credentials_unverified"
        assert "test it" in opts[pid]["action_label"].lower()


def test_a_signed_in_cli_the_provider_refuses_is_not_ready(machine):
    """gemini-cli's standing lesson: perfect credentials, every call refused."""
    machine["clis"] = {"claude-code": ("provider_refused", "IneligibleTierError")}

    claude = _by_id(ps.build_report())["claude-code"]

    assert claude["ready"] is False
    assert claude["readiness"] == "provider_refused"
    assert "refusing" in claude["action_label"].lower()


def test_a_slow_ollama_is_not_reported_as_no_models(machine):
    """"I could not ask" must never render as "the answer is none"."""
    machine["ollama_up"] = True  # daemon reachable, zero models returned

    local = _by_id(ps.build_report())["local"]

    assert local["readiness"] == "credentials_unverified"
    assert local["readiness"] != "not_installed"


# ── Google is one row, and it is sign-in shaped ─────────────────────────────────────────


def test_google_is_exactly_one_option(machine):
    """It used to be a blank password field; gemini-cli made it two stories about one vendor."""
    machine["google"] = ("me@example.com", "gemini")

    google = [o for o in ps.build_report().options if o["id"] == "google"]

    assert len(google) == 1, f"expected one Google row, got {len(google)}"


def test_google_offers_sign_in_not_a_key_field(machine):
    machine["google"] = ("me@example.com", "gemini")

    google = _by_id(ps.build_report())["google"]

    assert google["signin"] is True
    assert google["group"] == "start_here"
    assert google["action"] == "google_signin"
    assert google["effort"] == ps.EFFORT_SIGN_IN
    assert "me@example.com" in google["what_it_means"]


def test_google_says_why_the_cli_path_is_dead_without_offering_it(machine):
    """Silence here sends someone to debug a CLI whose credentials are fine."""
    machine["google"] = ("me@example.com", "gemini")
    machine["clis"] = {"gemini-cli": ("provider_refused", "IneligibleTierError")}

    report = ps.build_report()

    assert "gemini-cli" not in _by_id(report), "a dead path was offered as an option"
    assert "no longer serves it" in _by_id(report)["google"]["what_it_means"]


def test_antigravity_alone_still_counts_as_signed_in_to_google(machine, monkeypatch, tmp_path):
    """The piggyback: Antigravity has no headless entrypoint, but it proves the account."""
    machine["google"] = ("", "antigravity")

    google = _by_id(ps.build_report())["google"]

    assert google["action"] == "google_signin"
    assert google["title"] == "Sign in with Google"


def test_google_identity_reads_the_gemini_account_file(monkeypatch, tmp_path):
    (tmp_path / ".gemini").mkdir()
    (tmp_path / ".gemini" / "google_accounts.json").write_text(
        json.dumps({"active": "someone@example.com", "old": []}), encoding="utf-8"
    )
    monkeypatch.setattr(ps.Path, "home", staticmethod(lambda: tmp_path))

    assert ps._google_identity() == ("someone@example.com", "gemini")


def test_google_identity_is_silent_when_nothing_is_installed(monkeypatch, tmp_path):
    """A guess about who the user is would be worse than no name at all."""
    monkeypatch.setattr(ps.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "nope"))

    assert ps._google_identity() == ("", "")


# ── don't ask twice for the same vendor ─────────────────────────────────────────────────


def test_a_key_row_covered_by_a_signed_in_cli_says_so(machine):
    """Otherwise "Sign in with Claude" and "Anthropic — get a key" read as two chores."""
    machine["clis"] = {"claude-code": ("verified", "me@example.com")}

    anthropic = _by_id(ps.build_report())["anthropic"]

    assert anthropic["covered_by"] == "claude-code"
    assert "already signed in" in anthropic["what_it_means"]


def test_key_rows_stay_out_of_start_here(machine):
    """Tier 3 is collapsed by default; a first-time user should never have to meet it."""
    opts = ps.build_report().options

    for o in opts:
        if o["effort"] == ps.EFFORT_PASTE_KEY and o["id"] != "google":
            assert o["group"] == "advanced", f"{o['id']} put a key field in front of a beginner"


# ── choosing a model without reading a model name ───────────────────────────────────────


def test_every_provider_uses_the_same_three_words(machine):
    """Claude has 3 models, Google 4, OpenAI several. The user learns the vocabulary once."""
    for provider in ps.MODEL_CHOICES:
        tiers = [c["tier"] for c in ps.model_choices(provider)]
        assert tiers == [ps.FAST, ps.BALANCED, ps.DEEP], f"{provider} broke the vocabulary"


def test_no_choice_shows_a_raw_model_id_as_its_label():
    """`claude-sonnet-4-6` is not a decision. The id is for the runtime, the label for a human."""
    for provider in ps.MODEL_CHOICES:
        for choice in ps.model_choices(provider):
            assert choice["label"] != choice["id"]
            assert choice["help"], f"{provider}/{choice['tier']} offers no reason to pick it"


def test_the_cheapest_choice_is_the_default():
    for provider in ps.MODEL_CHOICES:
        defaults = [c for c in ps.model_choices(provider) if c["default"]]
        assert len(defaults) == 1 and defaults[0]["tier"] == ps.FAST


def test_a_local_model_that_is_not_downloaded_says_so():
    """Hiding it leaves the user wondering why they have fewer options than the screenshot."""
    choices = ps.model_choices("local", installed=["qwen2.5-coder:1.5b-instruct"])

    assert choices[0]["installed"] is True
    assert choices[-1]["installed"] is False
    assert "download" in choices[-1]["help"].lower()


# ── verification tells the truth about what it did ──────────────────────────────────────


def test_verify_refuses_to_fake_a_test_for_a_sign_in_option():
    """A green check for a path nobody exercised is the failure this project keeps finding."""
    result = ps.verify("claude-code")

    assert result["ok"] is False
    assert "signing in" in result["detail"]


def test_google_signin_action_names_the_account_and_says_it_is_free(machine, monkeypatch):
    monkeypatch.setattr(ps, "_google_identity", lambda: ("me@example.com", "gemini"))

    result = ps.run_action("google", "google_signin")

    assert result["ok"] is True
    assert "me@example.com" in result["detail"]
    assert "no card" in result["detail"]
