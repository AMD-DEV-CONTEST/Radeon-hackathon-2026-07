"""SessionMemory.history() — the context window the model actually sees.

These tests exist because a "sort order cleanup" silently turned the recency
window inside out: history() started returning the OLDEST n turns instead of
the NEWEST n. Nothing crashed, no log line appeared — the model simply stopped
seeing what it had just said once a session passed `limit` turns, and answers
drifted off-topic and repeated questions.

Two independent properties are asserted separately, because the regression was
caused by fixing one (tie order) and breaking the other (recency) in the same
edit:

  1. recency  — the window holds the LAST n turns
  2. tie order — turns sharing a `ts` keep insertion order

A short smoke test can never catch #1: with fewer than `limit` turns both the
correct and the broken query return the same rows.
"""
import pytest

from screwshell.memory.stores import SessionMemory


@pytest.fixture()
def mem(tmp_path):
    return SessionMemory(str(tmp_path), session_id="s1")


def test_history_returns_the_most_recent_turns_not_the_oldest(mem):
    """20 turns, limit=12 -> turn-09..turn-20 (the tail), never turn-01..turn-12.

    This is the regression that `ORDER BY ts ASC LIMIT ?` introduced. The bug
    only appears once the session is LONGER than the limit, which is exactly
    when multi-turn memory starts to matter.
    """
    for i in range(1, 21):
        mem.add_turn("user", f"turn-{i:02d}")

    got = [t["content"] for t in mem.history(limit=12)]

    assert len(got) == 12
    assert got == [f"turn-{i:02d}" for i in range(9, 21)], (
        "history() must return the TAIL of the conversation; returning the head "
        "means the model never sees its own latest turns (silent amnesia)"
    )
    assert got[-1] == "turn-20", "the newest turn must always be present"


def test_history_is_ordered_oldest_first(mem):
    """The window is chronological, so the prompt reads like a transcript."""
    for i in range(1, 6):
        mem.add_turn("user", f"turn-{i:02d}")

    got = [t["content"] for t in mem.history(limit=12)]

    assert got == ["turn-01", "turn-02", "turn-03", "turn-04", "turn-05"]


def test_history_order_is_stable_for_turns_sharing_a_timestamp(mem):
    """Turns sharing a `ts` must keep insertion order.

    `_now()` is `round(time.time(), 3)`, so collisions happen whenever two turns
    land in the same millisecond — a fast backend, a batched replay, or a
    coarser clock. That is the original bug: `ORDER BY ts DESC` + `reversed()`
    let SQLite return tied rows in an arbitrary order, flipping question and
    answer. rowid (monotonic insertion order) is the tiebreak.

    The collision is written directly rather than hoped for: a plain
    `add_turn` loop commits ~30ms apart on this machine and never ties, so a
    timing-dependent version of this test would pass while asserting nothing.
    """
    written = [f"burst-{i}" for i in range(5)]
    for c in written:
        mem.db.execute("INSERT INTO turns VALUES (?,?,?,?,?)",
                       ("s1", 1000.0, "user", c, "{}"))
    mem.db.commit()

    tss = {r[0] for r in mem.db.execute(
        "SELECT ts FROM turns WHERE session=?", ("s1",)).fetchall()}
    assert tss == {1000.0}, "precondition: every row must share one ts"

    got = [t["content"] for t in mem.history(limit=12)]

    assert got == written, "tied timestamps must fall back to insertion order"


def test_history_keeps_recency_when_the_newest_turns_are_tied(mem):
    """Recency and tie-order must hold TOGETHER, not one at a time.

    The naive tail query `ORDER BY ts DESC LIMIT n` reversed in Python gets this
    wrong: among rows tied on `ts` it may cut the window at an arbitrary point.
    Here the last six turns all share a timestamp and the window holds four, so
    the query has to break the tie by rowid *before* truncating.
    """
    for i in range(1, 5):
        mem.db.execute("INSERT INTO turns VALUES (?,?,?,?,?)",
                       ("s1", 100.0 + i, "user", f"old-{i}", "{}"))
    for i in range(1, 7):
        mem.db.execute("INSERT INTO turns VALUES (?,?,?,?,?)",
                       ("s1", 900.0, "user", f"tied-{i}", "{}"))
    mem.db.commit()

    got = [t["content"] for t in mem.history(limit=4)]

    assert got == ["tied-3", "tied-4", "tied-5", "tied-6"], (
        "the window must be the last four rows in insertion order, even when "
        "they are indistinguishable by timestamp"
    )


def test_history_alternating_roles_survive_the_window(mem):
    """A realistic user/assistant transcript keeps pairing after truncation.

    Guards the combination of both properties: a tail window that also gets the
    tie order wrong would return the right turns with question and answer
    swapped — worse than useless as context.
    """
    for i in range(1, 11):
        mem.add_turn("user", f"q{i}")
        mem.add_turn("assistant", f"a{i}")

    got = mem.history(limit=6)

    assert [t["role"] for t in got] == [
        "user", "assistant", "user", "assistant", "user", "assistant"]
    assert [t["content"] for t in got] == ["q8", "a8", "q9", "a9", "q10", "a10"]


def test_history_is_scoped_to_its_session(tmp_path):
    """Sessions share one DB file; the window must not leak across them."""
    a = SessionMemory(str(tmp_path), session_id="alpha")
    b = SessionMemory(str(tmp_path), session_id="beta")
    a.add_turn("user", "alpha-1")
    b.add_turn("user", "beta-1")
    b.add_turn("user", "beta-2")

    assert [t["content"] for t in a.history()] == ["alpha-1"]
    assert [t["content"] for t in b.history()] == ["beta-1", "beta-2"]


def test_history_on_empty_session_returns_empty_list(mem):
    assert mem.history() == []
