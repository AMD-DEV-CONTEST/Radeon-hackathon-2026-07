"""The chrono daemon must never park the build that feeds it.

THE BUG, found 2026-07-31 by running a hive session, not by reading code. Two sessions stalled at
the same point -- right after step 2's Compiler Oracle reported PASS -- and would have stalled
forever. Symptoms: identical CPU time across samples fifteen minutes apart, no child process, no
container, Ollama idle and answering unrelated requests in 24s, no error, no timeout, nothing in any
log after the PASS line.

Diagnosis needed `faulthandler.dump_traceback_later(150, repeat=True)`, which named both halves in
one dump:

    Thread (poll):  chrono_daemon._write_snapshot  <- line 650
                    chrono_daemon._poll_loop       <- line 644
    Thread (main):  chrono_daemon.record_compile_result  <- line 548
                    hive.executor.execute_step           <- line 1042

`_poll_loop` held `self._lock` and called `_write_snapshot()`, which takes `self._lock` itself. The
lock was a plain `threading.Lock`, so the poll thread deadlocked against itself while holding it,
and the main thread blocked behind it the moment the oracle recorded a compile result. Recording
that result is the FIRST thing that happens after a PASS, which is why it always presented as
"hangs right after the compiler succeeds".

Four wrong guesses came first -- Ollama, Docker, VRAM pressure, the thermal governor -- because all
four can also present as "stopped, no message". Hence these tests: they assert the property
("a poll tick cannot block a compile record") rather than any of those theories, and they run
against a real daemon with a real poll thread, because a mocked lock cannot deadlock.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import chrono_daemon  # noqa: E402

# Long enough for a real thread to be observed, short enough not to pad the suite.
FAST_POLL = 0.02
CALL_BUDGET = 5.0


def _focus(daemon, path: str | None = None) -> str:
    """Put the daemon in the state the poll loop acts on: a current buffer.

    `update_buffer` is the real entry point (there is no set_active_buffer) and it takes the file
    CONTENT, because it computes an AST hash. Kept tiny so tree-sitter parsing is not what these
    tests measure.
    """
    path = path or str(_ROOT / "scripts" / "chrono_daemon.py")
    daemon.update_buffer(buffer_path=path, file_content="x = 1\n", language="python")
    return path


@pytest.fixture()
def daemon(tmp_path, monkeypatch):
    """A real daemon on a temp DB with a fast poll interval, stopped on the way out."""
    monkeypatch.setattr(chrono_daemon, "CHRONO_POLL_SECONDS", FAST_POLL)
    d = chrono_daemon.ChronoDaemon(db_path=tmp_path / "chrono.db", session_id="deadlock-test")
    try:
        yield d
    finally:
        try:
            d.stop()
        except Exception:
            pass


def _call_with_deadline(fn, *args, budget: float = CALL_BUDGET, **kwargs) -> bool:
    """-> True if fn returned within budget. A deadlocked call never returns, so time it out."""
    done = threading.Event()

    def run():
        try:
            fn(*args, **kwargs)
        finally:
            done.set()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return done.wait(timeout=budget)


class TestTheLockIsReentrant:
    def test_the_lock_survives_being_taken_twice_in_one_thread(self, daemon):
        """The narrow fact the deadlock turned on. A plain Lock fails this and hangs."""
        acquired_twice = False
        with daemon._lock:
            acquired_twice = daemon._lock.acquire(timeout=1.0)
            if acquired_twice:
                daemon._lock.release()
        assert acquired_twice, (
            "self._lock is not reentrant -- any method that takes it and then calls a helper that "
            "also takes it deadlocks the thread WHILE HOLDING IT, which parks every other caller"
        )

    def test_a_snapshot_can_be_written_while_holding_the_lock(self, daemon):
        """Exactly what _poll_loop used to do."""
        _focus(daemon)

        def held():
            with daemon._lock:
                daemon._write_snapshot()

        assert _call_with_deadline(held), "writing a snapshot under the lock deadlocked"


class TestThePollLoopCannotBlockTheBuild:
    def test_recording_a_compile_result_returns_while_the_poll_thread_runs(self, daemon):
        """The regression as the build experiences it.

        The oracle calls record_compile_result after every attempt. With the poll thread alive and a
        buffer set -- the state the poll loop acts on -- this call has to return.
        """
        _focus(daemon)
        daemon.start()
        time.sleep(FAST_POLL * 6)  # let several poll ticks land first

        assert _call_with_deadline(
            daemon.record_compile_result,
            buffer_path=str(_ROOT / "scripts" / "chrono_daemon.py"),
            function_signature="fn main()",
            failed=False,
        ), (
            "record_compile_result did not return -- this is the 19-minute stall: a poll tick "
            "deadlocked holding the lock and the compiler-oracle path blocked behind it"
        )

    def test_many_compile_results_all_return(self, daemon):
        """A session records one per attempt per step; the stall hit on step 2, not step 1."""
        path = _focus(daemon)
        daemon.start()

        for i in range(12):
            assert _call_with_deadline(
                daemon.record_compile_result,
                buffer_path=path,
                function_signature=f"fn step_{i}()",
                failed=bool(i % 3),
                budget=3.0,
            ), f"record_compile_result blocked on call {i}"
            time.sleep(FAST_POLL)

    def test_a_poll_tick_between_two_records_does_not_block_the_second(self, daemon):
        """The precise interleaving: tick lands between attempts."""
        path = _focus(daemon)
        daemon.start()

        assert _call_with_deadline(
            daemon.record_compile_result,
            buffer_path=path,
            function_signature="a",
            failed=True,
            budget=3.0,
        )
        time.sleep(FAST_POLL * 4)
        assert _call_with_deadline(
            daemon.record_compile_result,
            buffer_path=path,
            function_signature="a",
            failed=False,
            budget=3.0,
        ), "the second record blocked -- a poll tick had taken the lock and not given it back"

    def test_the_daemon_stops_cleanly_after_all_that(self, daemon):
        """A deadlocked poll thread never observes _running=False, so stop() hangs on join."""
        _focus(daemon)
        daemon.start()
        time.sleep(FAST_POLL * 4)

        assert _call_with_deadline(daemon.stop, budget=8.0), (
            "stop() blocked joining the poll thread"
        )


class TestThePollLoopDoesNotHoldTheLockAcrossTheWrite:
    def test_the_source_reads_the_flag_under_the_lock_and_writes_outside_it(self):
        """A source check, deliberately, because the shape is the bug.

        Re-entrancy makes the old code survivable, so a behavioural test alone would pass on it
        while it still held the lock across a disk write -- stalling the oracle path that calls
        record_compile_result once per attempt.
        """
        import inspect

        src = inspect.getsource(chrono_daemon.ChronoDaemon._poll_loop)
        body = src.split('"""')[-1]  # past the docstring, which discusses the old shape
        raw = [ln for ln in body.splitlines() if ln.strip()]

        lock_idx = next(i for i, ln in enumerate(raw) if "with self._lock" in ln)
        write_idx = next(i for i, ln in enumerate(raw) if "_write_snapshot()" in ln)
        assert write_idx > lock_idx, "expected the write after the guarded read"

        # "Inside the `with`" means every line between the two stays indented deeper than the
        # `with` itself. Comparing only the two lines' indents is not enough: the write legitimately
        # sits inside a following `if`, which is deeper than the `with` while being outside it.
        indent = lambda ln: len(ln) - len(ln.lstrip())  # noqa: E731
        lock_indent = indent(raw[lock_idx])
        dedented = any(indent(ln) <= lock_indent for ln in raw[lock_idx + 1 : write_idx + 1])
        assert dedented, (
            "_write_snapshot() is still inside `with self._lock:` -- that is the original deadlock, "
            "and with an RLock it degrades to holding the lock across a disk write instead"
        )
