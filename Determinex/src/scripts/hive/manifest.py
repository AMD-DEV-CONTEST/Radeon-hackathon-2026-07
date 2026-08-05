"""
scripts/hive/manifest.py — Manifest data structures, session storage, and WAL
==============================================================================
Moved from determinex_hive.py (lines ~518-701).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

try:
    from hive._log import get_logger as _get_logger  # noqa: F401

    log = _get_logger("hive.manifest")
except ImportError:
    log = logging.getLogger("hive")

# DETERMINEX_ROOT env var is set by the Rust backend (spawn_hive_subprocess) so the
# PyInstaller sidecar — whose __file__ resolves to a temp extraction dir — finds
# the real project root instead of a temp path.
#
# But an env var pointing at the WRONG tree is worse than no env var, and that is not
# hypothetical: .env carried DETERMINEX_ROOT=C:\Dev\Citadel (the pre-rename checkout)
# for two days. _SESSIONS_DIR below is derived from this, so every session created in
# that window wrote its manifest and WAL into the old checkout instead of this one.
# Existence alone could never have caught it — that directory does exist.
_ROOT_MARKER = "litellm_config.yaml"


def _looks_like_repo(p: Path) -> bool:
    return (p / _ROOT_MARKER).is_file()


def resolve_repo_root() -> Path:
    """The project root, preferring whichever candidate actually looks like the repo.

    Three cases, in order, because no single rule covers them all:
      1. DETERMINEX_ROOT points at a real checkout  -> use it (the sidecar's purpose).
      2. It does not, but the derived path does      -> use the derived path and warn;
         this is the stale-pointer case, where obeying the variable silently sends
         sessions into another tree.
      3. Neither looks like a checkout               -> honour DETERMINEX_ROOT anyway.
         In a PyInstaller sidecar the derived path is a temp extraction dir, so
         falling back to it would be strictly worse than trusting the caller.
    """
    derived = Path(__file__).resolve().parent.parent.parent
    raw = os.environ.get("DETERMINEX_ROOT", "").strip()
    if not raw:
        return derived
    env_root = Path(raw).resolve()
    if _looks_like_repo(env_root):
        return env_root
    if _looks_like_repo(derived):
        print(
            f"[determinex] WARNING: DETERMINEX_ROOT={env_root} has no {_ROOT_MARKER} "
            f"and is not a Determinex checkout. Using {derived} instead — sessions "
            f"would otherwise be written to the wrong tree. Fix the value in .env.",
            file=sys.stderr,
        )
        return derived
    return env_root


_ROOT = resolve_repo_root()
_SESSIONS_DIR = _ROOT / "sessions"

# ── Build loop constants (needed by StepRecord defaults) ──────────────────────
DEFAULT_SESSION_BUDGET_USD = 2.00


# ── Manifest data structures ───────────────────────────────────────────────────


@dataclass
class PublicApiSnapshot:
    """Public API surface snapshot — used for DAG invalidation detection."""

    structs: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    fields: dict = field(default_factory=dict)  # struct_name → [field_sig, ...]
    return_types: dict = field(default_factory=dict)  # fn_name → return_type_str


@dataclass
class StepRecord:
    id: int
    instruction: str
    depends_on: list[int] = field(default_factory=list)
    target_file: str = ""
    write_mode: str = "append_to_file"  # new_file|replace_file|append_to_file|replace_function
    target_region: str | None = None
    dsl_context: str = ""
    status: str = "pending"  # pending|in_progress|complete|failed|stale_instruction
    builder_output_path: str = ""
    monitor_verdict: str = ""
    compiler_result: str = ""
    compiler_output: str = ""
    adjudication_score: float = 0.0
    retries: int = 0
    escalations: int = 0
    challenges: int = 0
    quality: str = ""  # training_ready|inconclusive|compile_hacked|""
    correctness_result: str = ""  # pass|fail|compile_hacked|skipped|""
    # Plan B: set True when fast_mode skips live Monitor; offline observer evaluates later.
    offline_observation_pending: bool = False
    offline_observation_result: str = ""  # pending|pass|fail|skipped
    public_api_snapshot: dict | None = None
    compiler_error_hashes: list[str] = field(default_factory=list)  # for quality gate
    # Model Router provenance (DETERMINEX_ROUTE=1): which rung of the ladder actually
    # produced the code the oracle accepted -- {model, tier, escalations, est_cost,
    # samples, passed}. None when routing was off, which is the default.
    #
    # Recorded on the STEP because that is what a cost belongs to: without it there is
    # no way to attribute spend to a tier, so "routing saved X" would be unmeasurable.
    # Safe to add here: load_manifest's G23 migration drops unknown keys and defaults
    # missing ones, and the WAL's atomicity is in the .pending -> .complete rename,
    # not in the field set.
    route_provenance: dict | None = None


@dataclass
class ManifestSession:
    session_id: str
    lang: str
    md_spec_path: str
    project_root: str
    workspace_file_hashes: dict = field(default_factory=dict)
    cargo_toml: str = ""
    scaffolding_validated: bool = False
    steps: list[StepRecord] = field(default_factory=list)
    pending_escalations: list[dict] = field(default_factory=list)
    api_cost_usd: float = 0.0
    session_budget_usd: float = DEFAULT_SESSION_BUDGET_USD
    budget_exhausted: bool = False
    # Plan A: Architect-generated correctness test harness path (relative to project_root).
    # If set, run after every Compiler PASS. compile PASS + tests FAIL → "compile_hacked" DPO label.
    correctness_test_harness: str = ""
    # Plan B: fast mode skips live Monitor to reduce build latency.
    # Steps are queued for offline Monitor evaluation when GPU is idle.
    fast_mode: bool = False
    created_at: str = ""
    updated_at: str = ""


# ── Session storage ────────────────────────────────────────────────────────────


def _session_dir(session_id: str) -> Path:
    return _SESSIONS_DIR / session_id


def _manifest_path(session_id: str) -> Path:
    return _session_dir(session_id) / "manifest.json"


def _steps_dir(session_id: str) -> Path:
    return _session_dir(session_id) / "steps"


def save_manifest(session: ManifestSession) -> None:
    """Persist the manifest to disk. Atomic: write PID-keyed temp → rename.

    G20: Use a PID-keyed temp filename so concurrent saves from different
    processes (e.g. offline observer + live session) never clobber each other's
    temp file before the final rename.
    """
    session.updated_at = datetime.now(UTC).isoformat()
    mpath = _manifest_path(session.session_id)
    mpath.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = mpath.with_name(f"manifest.{os.getpid()}.json.tmp")
    data = asdict(session)
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp_path.replace(mpath)  # atomic on NTFS and POSIX


def load_manifest(session_id: str) -> ManifestSession:
    """Load manifest from disk. Reconstructs StepRecord objects.

    G23: Schema migration — unknown fields are ignored and missing fields use
    dataclass defaults, so old sessions load cleanly after new fields are added.
    """
    data = json.loads(_manifest_path(session_id).read_text(encoding="utf-8"))

    # G23: migrate StepRecord dicts — drop unknown keys, fill missing with defaults
    _step_fields = set(StepRecord.__dataclass_fields__)
    steps: list[StepRecord] = []
    for s in data.pop("steps", []):
        known = {k: v for k, v in s.items() if k in _step_fields}
        steps.append(StepRecord(**known))

    # G23: migrate ManifestSession dict — drop unknown keys
    _session_fields = set(ManifestSession.__dataclass_fields__)
    data = {k: v for k, v in data.items() if k in _session_fields}
    session = ManifestSession(**data)
    session.steps = steps
    return session


def list_sessions() -> list[dict]:
    """Return summary dicts for all known sessions."""
    if not _SESSIONS_DIR.exists():
        return []
    results = []
    for d in sorted(_SESSIONS_DIR.iterdir()):
        mp = d / "manifest.json"
        if mp.exists():
            try:
                data = json.loads(mp.read_text(encoding="utf-8"))
                completed = sum(1 for s in data.get("steps", []) if s.get("status") == "complete")
                total = len(data.get("steps", []))
                results.append(
                    {
                        "session_id": data["session_id"],
                        "lang": data["lang"],
                        "md_spec": data["md_spec_path"],
                        "steps": f"{completed}/{total}",
                        "updated_at": data.get("updated_at", ""),
                        "budget_usd": data.get("api_cost_usd", 0.0),
                    }
                )
            except (json.JSONDecodeError, KeyError):
                pass
    return results


# ── Write-Ahead Log (WAL) ──────────────────────────────────────────────────────


def wal_write_pending(session_id: str, step: StepRecord) -> Path:
    """Write the step's intended state to step_N.pending. Returns the path."""
    sdir = _steps_dir(session_id)
    sdir.mkdir(parents=True, exist_ok=True)
    path = sdir / f"step_{step.id:04d}.pending"
    path.write_text(json.dumps(asdict(step), indent=2), encoding="utf-8")
    log.debug("WAL pending → %s", path.name)
    return path


def wal_complete(session_id: str, step_id: int) -> Path:
    """Atomically rename .pending → .complete. Returns new path."""
    sdir = _steps_dir(session_id)
    src = sdir / f"step_{step_id:04d}.pending"
    dst = sdir / f"step_{step_id:04d}.complete"
    if src.exists():
        src.replace(dst)
        log.debug("WAL complete → %s", dst.name)
    return dst


def wal_fail(session_id: str, step_id: int, error_state: dict) -> Path:
    """Atomically rename .pending → .failed, embedding the error state. Returns new path."""
    sdir = _steps_dir(session_id)
    src = sdir / f"step_{step_id:04d}.pending"
    dst = sdir / f"step_{step_id:04d}.failed"
    if src.exists():
        # Merge error state into the pending content before rename
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        data.update(error_state)
        src.write_text(json.dumps(data, indent=2), encoding="utf-8")
        src.replace(dst)
        log.debug("WAL failed → %s", dst.name)
    return dst


def wal_queue_offline(session_id: str, step: StepRecord) -> Path:
    """
    Plan B: Write step_N.offline_pending marker for async Monitor evaluation.
    The offline observer scans all sessions for these markers when GPU is idle.
    """
    sdir = _steps_dir(session_id)
    sdir.mkdir(parents=True, exist_ok=True)
    path = sdir / f"step_{step.id:04d}.offline_pending"
    path.write_text(json.dumps(asdict(step), indent=2), encoding="utf-8")
    log.debug("Offline observation queued → %s", path.name)
    return path


def wal_complete_offline(session_id: str, step_id: int, result: str) -> Path:
    """
    Rename step_N.offline_pending → step_N.offline_complete after observer finishes.
    `result` is written into the JSON payload for the training pipeline.
    """
    sdir = _steps_dir(session_id)
    src = sdir / f"step_{step_id:04d}.offline_pending"
    dst = sdir / f"step_{step_id:04d}.offline_complete"
    if src.exists():
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        data["offline_observation_result"] = result
        src.write_text(json.dumps(data, indent=2), encoding="utf-8")
        src.replace(dst)
        log.debug("Offline observation complete → %s (result=%s)", dst.name, result)
    return dst


def find_offline_pending(sessions_root: Path | None = None) -> list[tuple[str, int]]:
    """
    Scan all sessions for steps with .offline_pending markers.
    Returns list of (session_id, step_id) tuples sorted by session modification time.
    Used by the offline observer daemon to find work to do.
    """
    root = sessions_root or _SESSIONS_DIR
    results: list[tuple[str, int]] = []
    if not root.exists():
        return results
    for session_dir in sorted(root.iterdir()):
        steps_dir = session_dir / "steps"
        if not steps_dir.exists():
            continue
        for marker in steps_dir.glob("step_*.offline_pending"):
            m = re.search(r"step_(\d+)\.offline_pending", marker.name)
            if m:
                results.append((session_dir.name, int(m.group(1))))
    return results


def wal_recover_pending(session_id: str) -> list[int]:
    """
    On restart: scan for any .pending files.
    Returns list of step IDs that need retry.
    A .pending with invalid JSON (crash during write) is also treated as incomplete.
    """
    sdir = _steps_dir(session_id)
    if not sdir.exists():
        return []
    incomplete = []
    for f in sdir.glob("step_*.pending"):
        step_id_str = re.search(r"step_(\d+)\.pending", f.name)
        if not step_id_str:
            continue
        step_id = int(step_id_str.group(1))
        try:
            json.loads(f.read_text(encoding="utf-8"))
            log.warning("WAL recovery: step %d is incomplete (.pending) → will retry", step_id)
        except (json.JSONDecodeError, OSError):
            log.warning(
                "WAL recovery: step %d has corrupted .pending (crash during write) → will retry",
                step_id,
            )
        incomplete.append(step_id)
    return sorted(incomplete)


# ── Stratagem 1: Session-Level WAL Context Manager ────────────────────────────
#
# The step-level WAL (wal_write_pending / wal_complete / wal_fail) protects
# individual steps.  This session-level WAL protects the *daemon process itself*:
# it writes the active PID before any work begins, so a subsequent restart can
# detect a dead PID, classify the session as orphaned, reset in-progress steps
# to pending, and offer a clean resume — without manual lock-file deletion.

_session_wal_lock = threading.Lock()


def _pid_alive(pid: int) -> bool:
    """Return True if the given PID is still running (cross-platform, no sys.platform branch).

    Uses psutil.pid_exists when available (the preferred path — handles Windows,
    POSIX, and zombie processes correctly).  Falls back to os.kill signal-0 probe
    on POSIX systems where psutil is not installed.
    """
    try:
        import psutil

        return psutil.pid_exists(pid)
    except ImportError:
        pass
    # POSIX fallback: os.kill(pid, 0) probes existence without delivering a signal.
    # On Windows this raises ValueError (signal 0 unsupported); treat that as
    # "uncertain" and return True so we never falsely recover a live session.
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except (PermissionError, OSError, ValueError):
        return True  # alive but inaccessible, or Windows without psutil


class SessionWAL:
    """
    Atomic Write-Ahead Logging context manager for session-level operations.

    Writes the daemon's PID and operation intent to sessions/{id}/session.wal
    BEFORE any work begins.  On clean exit the WAL is renamed to .committed.
    On crash the WAL file remains — the next startup detects the dead PID,
    resets in-progress steps to pending, and enables clean session resume
    without manual lock-file deletion.

    Usage:
        with SessionWAL(session, "run_session") as wal:
            wal.checkpoint(current_step=step.id)
            # ... execute step ...
        # On exit: session.wal → session.wal.committed

    Class-level recovery:
        recovered = SessionWAL.recover_stale()
        for session_id in recovered:
            session = load_manifest(session_id)
            # offer resume to user
    """

    def __init__(self, session: ManifestSession, operation: str, **context):
        self._session = session
        self._operation = operation
        self._context = context
        self._path = _session_dir(session.session_id) / "session.wal"
        self._pid = os.getpid()

    def __enter__(self) -> SessionWAL:
        record = {
            "operation": self._operation,
            "pid": self._pid,
            "started_at": datetime.now(UTC).isoformat(),
            "context": self._context,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Use a PID-prefixed temp name so concurrent __enter__ calls on the same
        # session path don't clobber each other's temp file before the rename.
        _tmp = self._path.with_name(f"session.wal.{os.getpid()}.tmp")
        _tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        _tmp.replace(self._path)
        log.debug(
            "[SessionWAL] opened: session=%s op=%s pid=%d",
            self._session.session_id,
            self._operation,
            self._pid,
        )
        return self

    def checkpoint(self, **state) -> None:
        """Record intermediate state into the WAL. Crash after this point
        loses at most the work done since the last checkpoint."""
        if not self._path.exists():
            return
        try:
            with _session_wal_lock:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                data["last_checkpoint"] = {
                    "timestamp": datetime.now(UTC).isoformat(),
                    **state,
                }
                _tmp = self._path.with_suffix(".wal.tmp")
                _tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
                _tmp.replace(self._path)
        except Exception as _e:
            log.debug("[SessionWAL] checkpoint write failed (non-fatal): %s", _e)

    def __exit__(self, exc_type, exc_val, _exc_tb) -> bool:
        if not self._path.exists():
            return False
        if exc_type is None:
            committed = self._path.with_suffix(".wal.committed")
            try:
                self._path.replace(committed)
                log.debug("[SessionWAL] committed: session=%s", self._session.session_id)
            except OSError as _e:
                log.debug("[SessionWAL] commit rename failed (non-fatal): %s", _e)
        else:
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                data["failed_at"] = datetime.now(UTC).isoformat()
                data["error"] = str(exc_val)
                _tmp = self._path.with_suffix(".wal.tmp")
                _tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
                _tmp.replace(self._path)
                log.debug(
                    "[SessionWAL] failure recorded: session=%s err=%s",
                    self._session.session_id,
                    exc_val,
                )
            except Exception:
                pass
        return False  # never suppress the exception

    @classmethod
    def recover_stale(cls, sessions_root: Path | None = None) -> list[str]:
        """
        Scan all session directories for orphaned WALs (session.wal with a dead PID).
        For each orphan: reset in-progress steps → pending, save manifest, remove WAL.
        Returns list of recovered session IDs so the caller can offer resume to the user.

        Uses atomic rename to claim a WAL before recovery so concurrent daemon
        restarts don't double-process the same session.
        """
        root = sessions_root or _SESSIONS_DIR
        recovered: list[str] = []
        if not root.exists():
            return recovered

        for session_dir in sorted(root.iterdir()):
            wal_path = session_dir / "session.wal"
            if not wal_path.exists():
                continue

            # Claim the WAL atomically — if the rename fails, another process got it
            claiming = wal_path.with_suffix(".wal.recovering")
            try:
                wal_path.replace(claiming)
            except (FileNotFoundError, OSError):
                continue  # another process claimed it first

            try:
                data = json.loads(claiming.read_text(encoding="utf-8"))
                pid = int(data.get("pid", 0))
                session_id = session_dir.name

                if pid and _pid_alive(pid):
                    # Daemon is still running — put the WAL back and skip
                    claiming.replace(wal_path)
                    continue

                # Dead PID — daemon crashed.  Reset in-progress steps.
                manifest_path = session_dir / "manifest.json"
                if manifest_path.exists():
                    try:
                        session = load_manifest(session_id)
                        reset_count = 0
                        for step in session.steps:
                            if step.status == "in_progress":
                                step.status = "pending"
                                reset_count += 1
                        if reset_count:
                            save_manifest(session)
                            log.warning(
                                "[SessionWAL] Recovered orphaned session %s "
                                "(PID %d dead, %d steps reset to pending)",
                                session_id,
                                pid,
                                reset_count,
                            )
                    except Exception as _me:
                        log.warning(
                            "[SessionWAL] Could not reset steps for %s: %s", session_id, _me
                        )

                claiming.unlink(missing_ok=True)
                recovered.append(session_id)

            except Exception as _e:
                log.warning("[SessionWAL] Recovery error for %s: %s", session_dir.name, _e)
                claiming.unlink(missing_ok=True)

        return recovered
