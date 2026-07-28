"""
Unit tests for the Time-Travel CLI (aetheris undo) and the per-project session id it shares with `aetheris chat`.

Every case here encodes a rule that was found empirically against a real
backend and a real git repo while building the command, not one invented
from reading the code.
"""

import types

import pytest

from aetheris_cli.commands import undo as undo_mod
from aetheris_cli.commands.undo import _restorable_turns, undo_command
from aetheris_cli.session_id import project_session_id


# --------------------------------------------------------------------------
# session id derivation
# --------------------------------------------------------------------------


def test_session_id_is_path_spelling_independent():
    """`aetheris chat` hashes os.getcwd() while `aetheris undo -p ...`
    hashes what the user typed. Before normalization those produced
    different ids for one folder, so undo reported "no checkpoints" for
    edits sitting right there."""
    a = project_session_id(r"C:\proj\demo")
    b = project_session_id("C:/proj/demo")
    c = project_session_id("C:/proj/demo/")
    assert a == b == c


def test_session_id_distinguishes_different_projects():
    assert project_session_id("C:/proj/one") != project_session_id("C:/proj/two")


def test_session_id_prefix_separates_chat_from_run():
    """`aetheris run` keeps its own timeline, so a one-shot run never
    renumbers turns on top of an interactive session's shadow ref."""
    same_dir = "C:/proj/demo"
    assert project_session_id(same_dir) != project_session_id(same_dir, prefix="cli-run")


# --------------------------------------------------------------------------
# checkpoint resolution
# --------------------------------------------------------------------------


def _snap(turn_id, message, paths=("f.txt",)):
    return {"turn_id": turn_id, "message": message, "paths": list(paths), "commit": "deadbeef", "ts": 0}


def test_restorable_turns_only_counts_pre_snapshots():
    """A `post:` snapshot is the state AFTER an edit -- never a valid
    "restore to before this" target (mirrors the backend's own filter in
    _earliest_pre_snapshots_from_turn)."""
    snaps = [_snap(2, "post: write_file f.txt"), _snap(1, "pre: write_file f.txt")]
    assert _restorable_turns(snaps) == [1]


def test_restorable_turns_is_newest_first_and_tolerates_gaps():
    """Turn ids are not contiguous -- a turn that only reads files writes
    no snapshot -- so --last N indexes this list rather than doing
    arithmetic on the turn number."""
    snaps = [_snap(7, "pre: a"), _snap(3, "pre: b"), _snap(2, "post: c")]
    assert _restorable_turns(snaps) == [7, 3]


def test_restorable_turns_ignores_unstamped_snapshots():
    """Snapshots taken with no turn (older logs, or writes made outside a
    request) can never be checkpoint boundaries."""
    assert _restorable_turns([_snap(None, "pre: legacy")]) == []


# --------------------------------------------------------------------------
# undo_command behavior, against a fake client
# --------------------------------------------------------------------------


class _FakeClient:
    def __init__(self, snapshots, diffs=None):
        self._snapshots = snapshots
        self._diffs = diffs if diffs is not None else []
        self.restored_turn = None

    def set_project_path(self, path, chat_id=None):
        return {"status": "success", "path": path}

    def list_snapshots(self, session_id):
        return {"snapshots": self._snapshots}

    def preview_checkpoint(self, session_id, turn_id):
        return {"diffs": self._diffs}

    def restore_checkpoint(self, session_id, turn_id):
        self.restored_turn = turn_id
        return {"result": {"output": "Restored 1 file(s)", "exit_code": 0, "restored": ["f.txt"]}}


@pytest.fixture
def patched(monkeypatch):
    """Swaps in a fake client + an always-available backend, so these stay
    fast unit tests rather than requiring a live GPU-backed server."""
    def _install(client):
        monkeypatch.setattr(undo_mod, "AetherisClient", lambda *a, **k: client)
        monkeypatch.setattr(undo_mod, "check_backend_availability", lambda c: (True, "ok"))
        return client
    return _install


def test_undo_reports_cleanly_when_there_are_no_checkpoints(patched, capsys, tmp_path):
    patched(_FakeClient(snapshots=[]))
    rc = undo_command(session_id="s", project_dir=str(tmp_path))
    assert rc == 0
    assert "No Time-Travel checkpoints" in capsys.readouterr().out


def test_undo_rejects_last_beyond_available_checkpoints(patched, capsys, tmp_path):
    patched(_FakeClient(snapshots=[_snap(1, "pre: write_file f.txt")]))
    rc = undo_command(session_id="s", last=5, project_dir=str(tmp_path))
    assert rc == 2
    assert "only has 1 restorable checkpoint" in capsys.readouterr().err


def test_undo_rejects_zero_or_negative_last(patched, capsys, tmp_path):
    patched(_FakeClient(snapshots=[_snap(1, "pre: x")]))
    assert undo_command(session_id="s", last=0, project_dir=str(tmp_path)) == 2


def test_undo_last_n_targets_the_nth_newest_checkpoint(patched, tmp_path):
    """--last 1 is the newest editing turn, --last 2 the one before it --
    verified end to end against a real repo (V3 -> V2 -> V1 -> ORIGINAL)."""
    client = patched(_FakeClient(
        snapshots=[_snap(3, "pre: a"), _snap(2, "pre: b"), _snap(1, "pre: c")],
        diffs=[{"path": "f.txt", "diff": "--- a\n+++ b\n-V3\n+V2\n"}],
    ))
    undo_command(session_id="s", last=2, assume_yes=True, project_dir=str(tmp_path))
    assert client.restored_turn == 2


def test_undo_treats_empty_diff_text_as_a_no_op(patched, capsys, tmp_path):
    """preview returns one entry per touched path even when that path
    already matches the snapshot, with an EMPTY diff string. Counting
    entries instead of real content made a repeated `undo --last 1`
    confidently print "Restored 1 file(s)" while changing nothing."""
    client = patched(_FakeClient(
        snapshots=[_snap(1, "pre: write_file f.txt")],
        diffs=[{"path": "f.txt", "diff": ""}],
    ))
    rc = undo_command(session_id="s", assume_yes=True, project_dir=str(tmp_path))
    assert rc == 0
    assert client.restored_turn is None, "must not restore when nothing actually differs"
    assert "Already there" in capsys.readouterr().out


def test_undo_dry_run_never_restores(patched, capsys, tmp_path):
    client = patched(_FakeClient(
        snapshots=[_snap(1, "pre: write_file f.txt")],
        diffs=[{"path": "f.txt", "diff": "--- a\n+++ b\n-V1\n+ORIGINAL\n"}],
    ))
    rc = undo_command(session_id="s", dry_run=True, project_dir=str(tmp_path))
    assert rc == 0
    assert client.restored_turn is None
    assert "[--dry-run]" in capsys.readouterr().out


def test_undo_list_only_never_restores(patched, capsys, tmp_path):
    client = patched(_FakeClient(snapshots=[_snap(2, "pre: a"), _snap(1, "pre: b")]))
    rc = undo_command(session_id="s", list_only=True, project_dir=str(tmp_path))
    assert rc == 0
    assert client.restored_turn is None
    out = capsys.readouterr().out
    assert "2 restorable" in out and "--last 1" in out and "--last 2" in out


def test_undo_declined_at_the_confirm_gate_changes_nothing(patched, monkeypatch, capsys, tmp_path):
    client = patched(_FakeClient(
        snapshots=[_snap(1, "pre: write_file f.txt")],
        diffs=[{"path": "f.txt", "diff": "--- a\n+++ b\n-V1\n+ORIGINAL\n"}],
    ))
    monkeypatch.setattr("builtins.input", lambda: "n")
    rc = undo_command(session_id="s", project_dir=str(tmp_path))
    assert rc == 4
    assert client.restored_turn is None
    assert "cancelled" in capsys.readouterr().out.lower()


def test_undo_aborted_input_is_treated_as_decline(patched, monkeypatch, tmp_path):
    """Ctrl-C / EOF at the prompt must never be read as approval."""
    client = patched(_FakeClient(
        snapshots=[_snap(1, "pre: write_file f.txt")],
        diffs=[{"path": "f.txt", "diff": "-V1\n+ORIGINAL\n"}],
    ))

    def _boom():
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", _boom)
    assert undo_command(session_id="s", project_dir=str(tmp_path)) == 4
    assert client.restored_turn is None
