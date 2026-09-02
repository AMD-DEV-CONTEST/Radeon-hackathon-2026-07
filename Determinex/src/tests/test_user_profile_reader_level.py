"""The prescreen decides how Determinex talks, never what it can do.

Ryan, 2026-08-03: "add a prescreen asking level of expertise ... more technical, middle tech
(mix) or no tech but better on prose, and lets drive the user session that way."

Determinex says a lot to its user -- what an oracle verified, why a build was refused, what a
spec is still missing. All of it was written for one reader. For anyone else the product is
not wrong, it is unreadable, which lands in the same place: they stop.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import determinex_user_profile as P  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "_PROFILE_PATH", tmp_path / "profile.json")


def test_the_question_itself_contains_no_jargon():
    """A question asking how technical you are must not require technical vocabulary to
    answer. If the prose reader cannot parse the prescreen, the prescreen has already failed
    the only person it exists for."""
    blob = " ".join(
        [P.PRESCREEN["question"], P.PRESCREEN["note"]]
        + [c["label"] + " " + c["blurb"] for c in P.PRESCREEN["choices"]]
    ).lower()
    for jargon in ("api", "oracle", "dag", "stdout", "cli", "token", "endpoint", "repo", "config"):
        assert jargon not in blob, f"the prescreen uses the word {jargon!r}"


def test_it_asks_once_and_a_default_is_not_an_answer():
    """A defaulted profile must not be mistaken for a deliberate choice, or the tool either
    nags forever or silently assumes."""
    assert P.should_prescreen() is True
    assert P.load().level == P.MIXED  # a safe default to operate under meanwhile
    P.set_level(P.PROSE)
    assert P.should_prescreen() is False
    assert P.load().level == P.PROSE


def test_prose_never_sees_an_identifier():
    """No model ids, paths, flags or exit codes. This is the whole promise of that level."""
    assert P.show_identifiers(P.PROSE) is False
    out = P.say("The build passed.", "cargo build exited 0", level=P.PROSE)
    assert out == "The build passed."
    assert "cargo" not in out


def test_technical_gets_the_real_thing():
    out = P.say("The build passed.", "cargo build exited 0", level=P.TECHNICAL)
    assert out == "cargo build exited 0"


def test_mixed_leads_with_the_sentence_and_carries_the_detail():
    out = P.say("The build passed.", "cargo build exited 0", level=P.MIXED)
    assert out.startswith("The build passed.")
    assert "cargo build exited 0" in out


def test_the_plain_sentence_is_the_required_argument():
    """`say(plain, technical="")` on purpose. If the technical string were required and the
    plain one optional, every message in the product would end up being the raw one -- which
    is exactly the state this module was written to fix."""
    import inspect

    params = list(inspect.signature(P.say).parameters.values())
    assert params[0].name == "plain" and params[0].default is inspect.Parameter.empty
    assert params[1].name == "technical" and params[1].default == ""
    # and a message with no technical variant must still render at every level
    for lvl in P.LEVELS:
        assert P.say("Something happened.", level=lvl) == "Something happened."


def test_the_level_changes_density_not_capability():
    """A tool that quietly does less for people who read less is a worse tool wearing a
    friendlier face. The level may only affect how much is shown."""
    assert P.detail_density(P.TECHNICAL) == "full"
    assert P.detail_density(P.MIXED) == "summary"
    assert P.detail_density(P.PROSE) == "headline"
    assert set(P.LEVELS) == {P.TECHNICAL, P.MIXED, P.PROSE}


def test_an_unknown_level_is_refused_rather_than_silently_defaulted():
    with pytest.raises(ValueError):
        P.set_level("expert")


def test_a_corrupt_profile_falls_back_instead_of_crashing_the_app(tmp_path, monkeypatch):
    """A broken settings file must never be the reason someone cannot open the product."""
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(P, "_PROFILE_PATH", bad)
    prof = P.load()
    assert prof.level == P.MIXED and prof.answered is False


def test_the_prescreen_ships_the_current_level_with_the_question(tmp_path, monkeypatch):
    """One call answers both "must I ask?" and "how do I speak until they answer?".

    A caller forced into a second round trip for the level is a caller that skips it and
    defaults to the developer wording -- which is the outcome the prescreen exists to prevent.
    """
    monkeypatch.setenv("DETERMINEX_PROFILE", str(tmp_path / "profile.json"))
    import importlib

    import determinex_user_profile as up

    importlib.reload(up)

    payload = {**up.PRESCREEN, "needed": not up.load().answered, "level": up.load().level}

    assert payload["needed"] is True
    assert payload["level"] == up.MIXED, "an unanswered prescreen must not look like a choice"

    up.set_level(up.PROSE)
    after = {**up.PRESCREEN, "needed": not up.load().answered, "level": up.load().level}
    assert after == {**up.PRESCREEN, "needed": False, "level": up.PROSE}
