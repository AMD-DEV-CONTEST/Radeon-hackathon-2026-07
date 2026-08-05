"""Who takes priority in the room, and who goes next.

Ryan, 2026-08-03: *"the corpus should be the authority, and the answers should be looked at
by time, because tokens and prose can slide. There really needs to be a mechanism that allows
for the AIs to not collide and stop working but listen to a foreman and keep pushing to the
end even on APIs."*

Serialising turns stops a COLLISION. It does not answer who is right when participants
disagree, or who goes next when nobody is progressing -- and without those a room degrades
predictably: the last speaker wins by default, agents defer to each other, and the work stops
with everyone still "working".

The load-bearing rule is that authority comes from EVIDENCE, never from seniority, model size,
or how confident the prose sounds. Time is a tiebreak WITHIN a tier and nothing more.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from determinex_foreman import Authority, Foreman, Move, classify  # noqa: E402


def turn(speaker, *, verified=False, n_failures=0, kind="agent", at="2026-08-03T10:00:00", note=""):
    return {
        "speaker": speaker,
        "speaker_kind": kind,
        "verified": verified,
        "n_failures": n_failures,
        "finished_at": at,
        "note": note,
    }


# ── what backs a claim ──────────────────────────────────────────────────────────────────


def test_a_passing_oracle_is_the_top_authority():
    assert classify(turn("claude-code", verified=True)) is Authority.ORACLE


def test_the_corpus_outranks_any_agents_prose():
    """Ryan named it the authority precisely so confidence cannot outvote what is known."""
    assert classify(turn("corpus", kind="corpus")) is Authority.CORPUS
    assert Authority.CORPUS > Authority.PROSE


def test_an_oracle_rejection_outranks_prose():
    """"This exact approach fails with these 3 errors" is evidence. A room that discards it
    re-proposes the same thing forever."""
    assert classify(turn("codex", n_failures=3)) is Authority.REFUTED
    assert Authority.REFUTED > Authority.PROSE


def test_confident_prose_is_still_the_bottom_tier():
    assert classify(turn("codex", note="Fixed it! All tests pass now.")) is Authority.PROSE


def test_status_is_read_from_the_record_not_the_text():
    """A turn's own prose is the one thing that cannot describe its status honestly."""
    lying = turn("codex", verified=False, n_failures=4, note="everything passes now")
    assert classify(lying) is Authority.REFUTED


# ── time is a tiebreak, not a promotion ─────────────────────────────────────────────────


def test_later_wins_within_the_same_tier():
    fm = Foreman()
    fm.observe(turn("claude-code", verified=True, at="2026-08-03T10:00:00"))
    fm.observe(turn("codex", verified=True, at="2026-08-03T10:05:00"))
    assert fm.authoritative().speaker == "codex"


def test_time_never_promotes_prose_over_a_verified_result():
    """The whole point: tokens and prose slide, evidence does not."""
    fm = Foreman()
    fm.observe(turn("claude-code", verified=True, at="2026-08-03T10:00:00"))
    fm.observe(turn("codex", at="2026-08-03T23:59:00", note="actually I think it should be X"))
    top = fm.authoritative()
    assert top.speaker == "claude-code"
    assert top.authority is Authority.ORACLE


def test_corpus_is_not_outvoted_by_a_later_agent_opinion():
    fm = Foreman()
    fm.observe(turn("corpus", kind="corpus", at="2026-08-03T10:00:00"))
    fm.observe(turn("codex", at="2026-08-03T11:00:00", note="I disagree"))
    assert fm.authoritative().speaker == "corpus"


# ── arbitration ─────────────────────────────────────────────────────────────────────────


def test_same_tier_disagreement_is_arbitrated_and_the_reason_names_the_evidence():
    fm = Foreman()
    fm.observe(turn("claude-code", n_failures=5, at="2026-08-03T10:00:00"))
    fm.observe(turn("codex", n_failures=4, at="2026-08-03T10:05:00"))
    r = fm.next_move(["claude-code", "codex"])
    assert r.directive is Move.ARBITRATE
    assert r.assign_to == "codex"
    assert "oracle rejection" in r.because


def test_an_agent_contradicting_a_passing_oracle_is_not_a_conflict():
    """It is simply wrong, and `authoritative()` says so without ceremony."""
    fm = Foreman()
    fm.observe(turn("claude-code", verified=True, n_failures=0))
    fm.observe(turn("codex", note="I would do it differently"))
    assert fm.conflict() is None


# ── keep pushing ────────────────────────────────────────────────────────────────────────


def test_a_verified_zero_failure_result_ends_the_room():
    fm = Foreman()
    fm.observe(turn("claude-code", verified=True, n_failures=0))
    r = fm.next_move(["claude-code", "codex"])
    assert r.directive is Move.PROCEED and r.assign_to is None
    assert "Nothing outranks that" in r.because


def test_a_stalled_room_hands_the_floor_to_someone_who_has_not_failed_at_it():
    fm = Foreman()
    for _ in range(4):
        fm.observe(turn("claude-code", n_failures=7))
    r = fm.next_move(["claude-code", "codex", "local-ollama"])
    assert r.directive is Move.UNSTICK
    assert r.assign_to != "claude-code"
    assert "has not moved the number" in r.because


def test_a_room_making_too_little_progress_escalates_rather_than_grinding():
    """The rate rule's OUT_OF_PROPORTION, carried through to the people in the room."""
    fm = Foreman()
    for n in (42, 41, 40, 39, 38):
        fm.observe(turn("claude-code", n_failures=n))
    r = fm.next_move(["claude-code", "codex"])
    assert r.directive is Move.ESCALATE
    assert "not enough of it" in r.because
    assert "toolchain" in r.because or "stronger model" in r.because


def test_a_healthy_room_rotates_so_one_agent_cannot_hold_the_floor():
    fm = Foreman()
    fm.observe(turn("claude-code", n_failures=9))
    fm.observe(turn("claude-code", n_failures=6))
    r = fm.next_move(["claude-code", "codex"])
    assert r.directive is Move.PROCEED
    assert r.assign_to == "codex"


def test_talking_does_not_manufacture_a_plateau():
    """A corpus lookup or a user message makes no edits. Counting them as rounds that removed
    nothing would invent a stall out of people talking."""
    fm = Foreman()
    fm.observe(turn("claude-code", n_failures=9))
    for _ in range(6):
        fm.observe(turn("corpus", kind="corpus"))
        fm.observe(turn("user", kind="user"))
    r = fm.next_move(["claude-code", "codex"])
    assert r.directive is not Move.ESCALATE


def test_an_empty_room_still_answers():
    r = Foreman().next_move(["claude-code", "codex"])
    assert r.directive is Move.PROCEED and r.assign_to == "claude-code"


def test_the_ruling_always_carries_a_reason():
    fm = Foreman()
    fm.observe(turn("claude-code", n_failures=3))
    assert fm.next_move(["claude-code", "codex"]).because.strip()
