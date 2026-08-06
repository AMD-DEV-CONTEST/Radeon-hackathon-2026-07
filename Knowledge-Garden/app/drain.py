"""app/drain.py — cross-process drain/maintenance protocol (normative contract §6).

Primitives:
  - `acquire_maintenance_lock`: EXCLUSIVE flock on maintenance.lock (maintenance ops ONLY; API never touches it).
  - `writer_enter`/`writer_exit`: RACE-FREE write admission — reconcile_stale() FIRST, then SHARED flock on
    drain.lock, then re-read drain.state.json while holding it (must be `accepting`), then bump the in-flight
    writer counter; hold SH through the DB transaction.
  - `acquire_drain`: EXCLUSIVE flock on drain.lock with a 30s bound on ACQUISITION itself.
  - `wait_drained`: poll the in-flight writer counter to zero (flock-probing would self-deadlock under EX).
  - `DrainLease`: context manager performing EX -> draining -> zero in-flight -> drained -> body -> accepting -> release.
  - `reconcile_stale`: EPERM-safe, handles BOTH `draining` and `drained`.
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

ACCEPTING = "accepting"
DRAINING = "draining"
DRAINED = "drained"

DRAIN_STATE_FILE = os.environ.get("LC_DRAIN_STATE_FILE", "/persistent/learning-companion/data/drain.state.json")
DRAIN_LOCK_FILE = os.environ.get("LC_DRAIN_LOCK_FILE", "/persistent/learning-companion/data/drain.lock")
MAINTENANCE_LOCK_FILE = os.environ.get("LC_MAINTENANCE_LOCK_FILE",
                                       "/persistent/learning-companion/data/maintenance.lock")
WRITER_COUNT_FILE = os.environ.get("LC_WRITER_COUNT_FILE",
                                   "/persistent/learning-companion/data/writer_count.json")

ACQUIRE_DRAIN_TIMEOUT_S = 30
WAIT_DRAINED_TIMEOUT_S = 30
MAINTENANCE_LOCK_TIMEOUT_S = 10


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _state_path() -> Path:
    p = Path(DRAIN_STATE_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _read_state() -> dict:
    p = _state_path()
    if not p.exists():
        return {"state": ACCEPTING, "owner_token": None, "owner_pid": None,
                "owner_start_time": None, "started_at": None}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {"state": ACCEPTING, "owner_token": None, "owner_pid": None,
                "owner_start_time": None, "started_at": None}


def _write_state(state: dict) -> None:
    p = _state_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False))
    os.replace(tmp, p)


def _reset_state() -> None:
    _write_state({"state": ACCEPTING, "owner_token": None, "owner_pid": None,
                  "owner_start_time": None, "started_at": None})


def _proc_start_time(pid: int) -> Optional[float]:
    try:
        return os.stat(f"/proc/{pid}").st_ctime
    except OSError:
        return None


def _kill0(pid: int) -> str:
    """Return 'live' | 'eperm' | 'esrch' for kill(pid, 0)."""
    try:
        os.kill(pid, 0)
        return "live"
    except PermissionError:
        return "eperm"
    except ProcessLookupError:
        return "esrch"


def _flock_free(path: Path) -> bool:
    """True if no other process holds an EXCLUSIVE flock on the file."""
    if not path.exists():
        return True
    fd = os.open(path, os.O_RDWR)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
            return True
        except OSError:
            return False
    finally:
        os.close(fd)


def reconcile_stale() -> str:
    """EPERM-safe reconciliation of `draining`/`drained` (contract §6)."""
    state = _read_state()
    if state["state"] not in (DRAINING, DRAINED):
        return state["state"]
    pid = state.get("owner_pid")
    if not isinstance(pid, int):
        return state["state"]  # malformed PID -> fail-closed
    lock_free = _flock_free(Path(DRAIN_LOCK_FILE))
    k = _kill0(pid)
    if k == "eperm":
        return state["state"]  # live-or-unknown: fail-closed
    if k == "live":
        cur = _proc_start_time(pid)
        owner_start = state.get("owner_start_time")
        if cur is None or owner_start is None:
            return state["state"]  # unreadable /proc or missing start time -> fail-closed
        if cur == owner_start:
            return state["state"]  # same process still alive
        if lock_free:
            _reset_state()
            return ACCEPTING
        return state["state"]
    # k == "esrch": owner absent
    if lock_free:
        _reset_state()
        return ACCEPTING
    return state["state"]


# ---- in-flight writer accounting -----------------------------------------------------

def _read_count() -> int:
    p = Path(WRITER_COUNT_FILE)
    if not p.exists():
        return 0
    try:
        return int(json.loads(p.read_text())["in_flight"])
    except (json.JSONDecodeError, OSError, KeyError, ValueError):
        return 0


def _atomic_write(path: Path, content: str) -> None:
    """Atomic write with a UNIQUE temp file (safe under concurrent writers)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class _CounterLock:
    """EXCLUSIVE flock around the writer-count file to serialize read-modify-write."""

    def __enter__(self):
        p = Path(WRITER_COUNT_FILE + ".lock")
        p.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(p, os.O_RDWR | os.O_CREAT)
        fcntl.flock(self._fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc) -> None:
        fcntl.flock(self._fd, fcntl.LOCK_UN)
        os.close(self._fd)


def _write_count(n: int) -> None:
    _atomic_write(Path(WRITER_COUNT_FILE), json.dumps({"in_flight": n}))


def writer_enter():
    """RACE-FREE admission: reconcile first, SH drain.lock, re-read state, bump counter."""
    reconcile_stale()
    p = Path(DRAIN_LOCK_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise RuntimeError("drain in progress: write admission denied")
    try:
        if _read_state()["state"] != ACCEPTING:
            raise RuntimeError("drain in progress: write admission denied")
        with _CounterLock():
            _write_count(_read_count() + 1)
        return fd
    except Exception:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        raise


def writer_exit(fd: int) -> None:
    with _CounterLock():
        _write_count(max(0, _read_count() - 1))
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


# ---- maintenance lock ----------------------------------------------------------------

def acquire_maintenance_lock():
    """EXCLUSIVE maintenance.lock with timeout (maintenance ops only)."""
    p = Path(MAINTENANCE_LOCK_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_RDWR | os.O_CREAT)
    deadline = time.monotonic() + MAINTENANCE_LOCK_TIMEOUT_S
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            if time.monotonic() >= deadline:
                os.close(fd)
                raise TimeoutError("maintenance.lock busy")
            time.sleep(0.05)


def release_maintenance_lock(fd: int) -> None:
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


# ---- drain ---------------------------------------------------------------------------

def acquire_drain():
    """EXCLUSIVE drain.lock with a 30s bound on ACQUISITION itself."""
    p = Path(DRAIN_LOCK_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_RDWR | os.O_CREAT)
    deadline = time.monotonic() + ACQUIRE_DRAIN_TIMEOUT_S
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            if time.monotonic() >= deadline:
                os.close(fd)
                raise TimeoutError("drain.lock busy (acquisition timeout)")
            time.sleep(0.05)


def release_drain(fd: int) -> None:
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


def set_drain_state(state: str, token: str) -> None:
    _write_state({
        "state": state,
        "owner_token": token,
        "owner_pid": os.getpid(),
        "owner_start_time": _proc_start_time(os.getpid()) or time.time(),
        "started_at": _now(),
    })


def wait_drained(timeout: float = WAIT_DRAINED_TIMEOUT_S) -> None:
    """Under EXCLUSIVE drain.lock, wait until in-flight writer count reaches zero."""
    deadline = time.monotonic() + timeout
    while _read_count() > 0:
        if time.monotonic() >= deadline:
            raise TimeoutError("wait_drained timed out")
        time.sleep(0.05)


class DrainLease:
    """Full drain context manager: EX -> draining -> zero in-flight -> drained -> body -> accepting -> release."""

    def __init__(self, token: str = "lease") -> None:
        self.token = token
        self._drain_fd: Optional[int] = None

    def __enter__(self) -> "DrainLease":
        self._drain_fd = acquire_drain()
        try:
            set_drain_state(DRAINING, self.token)
            wait_drained()
            set_drain_state(DRAINED, self.token)
        except Exception:
            _reset_state()
            if self._drain_fd is not None:
                release_drain(self._drain_fd)
            raise
        return self

    def __exit__(self, *exc) -> None:
        _reset_state()
        if self._drain_fd is not None:
            release_drain(self._drain_fd)
