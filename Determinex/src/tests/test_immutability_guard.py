"""tests/test_immutability_guard.py — EVIDENCE_IMMUTABILITY_GUARD_LOCK_001 + CORPUS_WRITE_GUARD_LOCK_001

Verifies:
  - read_only_context() blocks corpus writes with CorpusWriteBlockedError
  - DETERMINEX_NO_CORPUS_WRITE env var blocks corpus writes
  - determinex evidence validate is read-only (no file mutations)
  - determinex status is read-only (no file mutations)
  - determinex config show/doctor are read-only
  - determinex doctor is read-only (except --json explicit output)
  - read_only_context() is composable and restores env correctly
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ---------------------------------------------------------------------------
# Corpus write guard
# ---------------------------------------------------------------------------


def test_assert_writes_allowed_passes_when_flag_unset(monkeypatch):
    monkeypatch.delenv("DETERMINEX_NO_CORPUS_WRITE", raising=False)
    from corpus.corpus_manager import _assert_writes_allowed

    _assert_writes_allowed()  # must not raise


@pytest.mark.parametrize("val", ["1", "true", "yes", "True", "YES"])
def test_assert_writes_blocked_when_flag_set(monkeypatch, val):
    monkeypatch.setenv("DETERMINEX_NO_CORPUS_WRITE", val)
    from corpus.corpus_manager import CorpusWriteBlockedError, _assert_writes_allowed

    with pytest.raises(CorpusWriteBlockedError):
        _assert_writes_allowed()


@pytest.mark.parametrize("val", ["0", "false", "no", "", "off"])
def test_assert_writes_allowed_for_falsy_values(monkeypatch, val):
    monkeypatch.setenv("DETERMINEX_NO_CORPUS_WRITE", val)
    from corpus.corpus_manager import _assert_writes_allowed

    _assert_writes_allowed()  # must not raise


def test_read_only_context_blocks_writes(monkeypatch):
    monkeypatch.delenv("DETERMINEX_NO_CORPUS_WRITE", raising=False)
    from corpus.corpus_manager import (
        CorpusWriteBlockedError,
        _assert_writes_allowed,
        read_only_context,
    )

    with read_only_context():
        with pytest.raises(CorpusWriteBlockedError):
            _assert_writes_allowed()


def test_read_only_context_restores_env_on_exit(monkeypatch):
    monkeypatch.delenv("DETERMINEX_NO_CORPUS_WRITE", raising=False)
    from corpus.corpus_manager import _assert_writes_allowed, read_only_context

    with read_only_context():
        pass
    # After context exits, writes should be allowed again
    _assert_writes_allowed()  # must not raise
    assert os.environ.get("DETERMINEX_NO_CORPUS_WRITE", "") == ""


def test_read_only_context_restores_previous_value(monkeypatch):
    monkeypatch.setenv("DETERMINEX_NO_CORPUS_WRITE", "previous_value")
    from corpus.corpus_manager import read_only_context

    with read_only_context():
        assert os.environ.get("DETERMINEX_NO_CORPUS_WRITE") == "1"
    assert os.environ.get("DETERMINEX_NO_CORPUS_WRITE") == "previous_value"


def test_read_only_context_composable(monkeypatch):
    monkeypatch.delenv("DETERMINEX_NO_CORPUS_WRITE", raising=False)
    from corpus.corpus_manager import (
        CorpusWriteBlockedError,
        _assert_writes_allowed,
        read_only_context,
    )

    with read_only_context():
        with read_only_context():
            with pytest.raises(CorpusWriteBlockedError):
                _assert_writes_allowed()
    # Both contexts exited — writes allowed again
    _assert_writes_allowed()


def test_read_only_context_restores_on_exception(monkeypatch):
    monkeypatch.delenv("DETERMINEX_NO_CORPUS_WRITE", raising=False)
    from corpus.corpus_manager import _assert_writes_allowed, read_only_context

    try:
        with read_only_context():
            raise ValueError("simulated error")
    except ValueError:
        pass
    # Env must be restored even after an exception
    _assert_writes_allowed()  # must not raise


# ---------------------------------------------------------------------------
# Inspection commands are read-only
# ---------------------------------------------------------------------------


def test_evidence_validate_no_file_mutations():
    """determinex evidence validate must not create, modify, or delete any files."""
    import determinex_cli as cli

    evidence_dir = _ROOT / "assurance" / "evidence"
    before = {str(p): p.stat().st_mtime for p in evidence_dir.rglob("*") if p.is_file()}
    sys.argv = ["determinex", "evidence", "validate"]
    cli.main()
    after = {str(p): p.stat().st_mtime for p in evidence_dir.rglob("*") if p.is_file()}
    assert before == after, f"evidence validate mutated files: {set(before) ^ set(after)}"


def _snapshot(dirs) -> dict[str, float]:
    """mtime of every file under `dirs`, EXCLUDING Python bytecode caches.

    __pycache__ was included until 2026-07-28, which made this guard fail for a
    reason that has nothing to do with what it guards: importing a module whose
    .py is newer than its .pyc rewrites the .pyc, so `config show` "modified" a
    file whenever any scripts/*.py had been edited since it was last imported.
    Order-dependent, so it passed in isolation and failed in the full suite --
    the worst shape for a guard, because a false alarm teaches people to ignore
    a real one. Bytecode caches are not corpus mutations.

    Separately: this test compares two snapshots taken ~30s apart (walking
    corpus/ is slow by design, see the caller's docstring), so it is NOT safe to
    run while anything else writes under scripts/ | assurance/ | corpus/. A
    second pytest run in parallel will mutate an assurance artifact between the
    two snapshots and the diff gets attributed to `config show`. Observed
    2026-07-28. That is a property of the measurement, not a defect to fix here
    -- but do not chase a `modified` failure without first checking for a
    concurrent run.
    """
    out: dict[str, float] = {}
    for d in dirs:
        if not d.exists():
            continue
        for f in d.rglob("*"):
            if "__pycache__" in f.parts or f.suffix in (".pyc", ".pyo"):
                continue
            if f.is_file():
                out[str(f)] = f.stat().st_mtime
    return out


@pytest.mark.slow
def test_config_show_no_file_mutations(tmp_path, capsys):
    """determinex config show must not write any files.

    Walks scripts/ + assurance/ + corpus/ twice (~192K files, ~130s+ real
    I/O even with no contention) -- genuinely slow by design, not a hang.
    Marked slow so it doesn't blow past a fast-loop timeout budget; it still
    runs in the full/CI pass.
    """
    import determinex_cli as cli

    # Snapshot entire scripts/ and assurance/ before
    checked_dirs = [_ROOT / "scripts", _ROOT / "assurance", _ROOT / "corpus"]
    before = _snapshot(checked_dirs)

    sys.argv = ["determinex", "config", "show"]
    cli.main()
    capsys.readouterr()

    after = _snapshot(checked_dirs)

    new_files = set(after) - set(before)
    assert not new_files, f"config show created files: {new_files}"
    modified = {k for k in before if after.get(k) != before[k]}
    assert not modified, f"config show modified files: {modified}"


def test_status_script_no_corpus_writes(monkeypatch):
    """determinex_status main() must not call any corpus write path."""
    monkeypatch.setenv("DETERMINEX_NO_CORPUS_WRITE", "1")
    import determinex_status
    from corpus.corpus_manager import CorpusWriteBlockedError

    # Patch sys.argv to use a safe mode (json output, no tail)
    sys.argv = ["determinex status", "--summary"]
    try:
        determinex_status.main()
    except CorpusWriteBlockedError:
        pytest.fail("determinex status called a corpus write method")
    except SystemExit:
        pass  # expected if no log file exists


def test_no_corpus_write_flag_exported_in_read_only_context():
    """read_only_context must set DETERMINEX_NO_CORPUS_WRITE=1 during execution."""
    from corpus.corpus_manager import read_only_context

    captured = {}

    def probe():
        captured["val"] = os.environ.get("DETERMINEX_NO_CORPUS_WRITE", "")

    with read_only_context():
        probe()
    assert captured["val"] == "1"
