"""scripts/run_ledger.py — universal append-only event ledger for all long Determinex jobs.

Design: JSONL is the source of truth, SQLite is a rebuildable index.

  - Each run gets a JSONL file at logs/ledger/{run_id}.jsonl.
    Every event (task started, task completed, score, failure family, artifact)
    appends one line. Never edits. Survives any crash.
  - SQLite index at logs/determinex_ledger.db is rebuilt from the JSONL files on
    startup (or `--rebuild`). Used by the live monitor / cockpit for fast
    queries (joins, aggregates, time-windowed rollups).

Event shape (matches the directive verbatim):

    {
      "run_id":    "mass_run_v2_base",
      "task_id":   "psampaz__go-mod-outdated.bb79367",
      "phase":     "scaffold" | "pack" | "eval" | "classify" | "report" | "build" | ...
      "status":    "started" | "completed" | "failed" | "skipped",
      "score":     17.0,                          # 0..100, optional
      "failures":  {"rc_2_unknown_option": 412},  # family -> count, optional
      "artifact":  "path/to/eval.json",           # optional
      "timestamp": "2026-05-13T20:51:00Z",
      "extra":     {...}                          # free-form
    }

Producers:
  - ProgramBench eval (via scripts/failure_classifier.py watcher)
  - SWE-bench ablation runs
  - Rosetta A/B (rosetta_vs_text_eval.py --json output)
  - micro eval, sidecar smoke, release CI

Consumers:
  - scripts/programbench_live_monitor.py (cockpit feed)
  - scripts/programbench_patch_advisor.py (recommender)
  - Future frontend Benchmark Lab tab (subscribes to monitor's JSON stream)

CLI:
    python scripts/run_ledger.py --append-event '{...}'
    python scripts/run_ledger.py --rebuild
    python scripts/run_ledger.py --summary
    python scripts/run_ledger.py --backfill-pb-eval-jsons
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DETERMINEX_ROOT = Path(os.environ.get("DETERMINEX_ROOT", Path(__file__).resolve().parents[1]))
LEDGER_DIR = DETERMINEX_ROOT / "logs" / "ledger"
SQLITE_PATH = DETERMINEX_ROOT / "logs" / "determinex_ledger.db"

# Files whose sha256 is recorded as part of run provenance — extend per executor.
SCAFFOLD_TEMPLATE_FILES_DEFAULT = (
    DETERMINEX_ROOT / "scripts" / "mass_run_v2_scaffold.py",
    DETERMINEX_ROOT / "scripts" / "mass_run_v2_pack.py",
)


# ---------------------------------------------------------------------------
# Event model
# ---------------------------------------------------------------------------


@dataclass
class LedgerEvent:
    """One row of the ledger. JSON-serializable.

    Required:    run_id, phase, status, timestamp
    Conventional: task_id, score, failures, artifact, extra
    """

    run_id: str
    phase: str
    status: str
    timestamp: str = field(
        default_factory=lambda: (
            datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        )
    )
    task_id: str | None = None
    score: float | None = None
    failures: dict[str, int] | None = None
    artifact: str | None = None
    extra: dict[str, Any] | None = None

    def to_json(self) -> str:
        return json.dumps(_compact(asdict(self)), default=str, separators=(",", ":"))


def _compact(d: dict) -> dict:
    """Drop None values so JSONL lines stay tight."""
    return {k: v for k, v in d.items() if v is not None}


# ---------------------------------------------------------------------------
# SQLite schema (rebuildable index)
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL,
    phase        TEXT NOT NULL,
    status       TEXT NOT NULL,
    timestamp    TEXT NOT NULL,
    task_id      TEXT,
    score        REAL,
    failures_json TEXT,
    artifact     TEXT,
    extra_json   TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_run         ON events(run_id);
CREATE INDEX IF NOT EXISTS idx_events_run_task    ON events(run_id, task_id);
CREATE INDEX IF NOT EXISTS idx_events_run_phase   ON events(run_id, phase);
CREATE INDEX IF NOT EXISTS idx_events_timestamp   ON events(timestamp);

CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    kind          TEXT,
    started_at    TEXT,
    last_seen_at  TEXT,
    n_events      INTEGER DEFAULT 0
);
"""


def _open_db(path: Path = SQLITE_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(_SCHEMA)
    return conn


# ---------------------------------------------------------------------------
# JSONL writer (source of truth)
# ---------------------------------------------------------------------------


def _jsonl_path(run_id: str) -> Path:
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in run_id)
    return LEDGER_DIR / f"{safe}.jsonl"


def append_event(event: LedgerEvent, sqlite_path: Path | None = None) -> Path:
    """Append one event to its run's JSONL, then mirror into the SQLite index.

    Returns the JSONL path. JSONL write is atomic (line is one fsync); SQLite
    update happens after — if it fails, the next `--rebuild` recovers it.

    sqlite_path resolves at CALL time so test monkeypatches of SQLITE_PATH
    flow through to every read/write path consistently.
    """
    if sqlite_path is None:
        sqlite_path = SQLITE_PATH
    jp = _jsonl_path(event.run_id)
    with jp.open("a", encoding="utf-8") as f:
        f.write(event.to_json())
        f.write("\n")
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass

    # Mirror into SQLite — best-effort, JSONL is authoritative
    try:
        conn = _open_db(sqlite_path)
        with _conn_tx(conn):
            _insert_event(conn, event)
            _bump_run_seen(conn, event)
        conn.close()
    except sqlite3.Error as e:
        print(f"[ledger] sqlite mirror failed (jsonl already wrote): {e}", file=sys.stderr)

    return jp


@contextmanager
def _conn_tx(conn: sqlite3.Connection):
    conn.execute("BEGIN")
    try:
        yield
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _insert_event(conn: sqlite3.Connection, event: LedgerEvent) -> None:
    conn.execute(
        """INSERT INTO events
           (run_id, phase, status, timestamp, task_id, score, failures_json, artifact, extra_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            event.run_id,
            event.phase,
            event.status,
            event.timestamp,
            event.task_id,
            event.score,
            json.dumps(event.failures, default=str) if event.failures else None,
            event.artifact,
            json.dumps(event.extra, default=str) if event.extra else None,
        ),
    )


def _bump_run_seen(conn: sqlite3.Connection, event: LedgerEvent) -> None:
    row = conn.execute("SELECT 1 FROM runs WHERE run_id = ?", (event.run_id,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO runs(run_id, kind, started_at, last_seen_at, n_events) VALUES (?, ?, ?, ?, 1)",
            (
                event.run_id,
                (event.extra or {}).get("kind") if event.extra else None,
                event.timestamp,
                event.timestamp,
            ),
        )
    else:
        conn.execute(
            "UPDATE runs SET last_seen_at = ?, n_events = n_events + 1 WHERE run_id = ?",
            (event.timestamp, event.run_id),
        )


# ---------------------------------------------------------------------------
# Rebuild the SQLite index from JSONL (recovery path)
# ---------------------------------------------------------------------------


def _git_sha(short: bool = False) -> str | None:
    """Capture current git HEAD sha. None if not in a git repo or git missing."""
    import subprocess

    try:
        args = ["git", "rev-parse"] + (["--short=12"] if short else []) + ["HEAD"]
        r = subprocess.run(
            args, cwd=str(DETERMINEX_ROOT), capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _git_dirty() -> bool | None:
    """True if the working tree has uncommitted changes; None on error."""
    import subprocess

    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(DETERMINEX_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0:
            return bool(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _file_sha256(path: Path) -> str | None:
    """Sha256 of a file. None if missing/unreadable."""
    import hashlib

    if not path.is_file():
        return None
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def record_run_meta(
    *,
    run_id: str,
    base_run_id: str | None = None,
    scaffold_version: str | None = None,
    patch_family: str | None = None,
    output_root: str | None = None,
    git_sha: str | None = None,
    scaffold_files: tuple[Path, ...] = SCAFFOLD_TEMPLATE_FILES_DEFAULT,
    representative_artifact: Path | None = None,
    notes: str | None = None,
    retroactive: bool = False,
) -> LedgerEvent:
    """Record provenance for a run BEFORE the first eval lands.

    Required directive fields:
        run_id, base_run_id, git_sha, scaffold_version, patch_family, output_root

    Auto-captured if not supplied:
        git_sha            from `git rev-parse HEAD`
        git_dirty          true if working tree has uncommitted changes
        scaffold_sha256    sha256 of each file in scaffold_files (byte-level proof)

    The event is emitted as phase='meta' status='recorded'. Without this row,
    downstream delta analysis (base vs iter1 vs iter2) is ambiguous about which
    scaffold produced which numbers. This is the integrity anchor for every
    cross-run comparison the cockpit ever makes.
    """
    if git_sha is None:
        git_sha = _git_sha()
    git_dirty = _git_dirty()

    scaffold_hashes = {p.name: _file_sha256(p) for p in scaffold_files}

    # Representative artifact: byte-level proof of what actually shipped from
    # this run. Critical for retroactive stamping where the scaffold file on
    # disk has been edited since the run started — the artifact never changes
    # post-fact, so it's the honest ground truth.
    representative = None
    if representative_artifact is not None:
        artifact_path = Path(representative_artifact)
        representative = {
            "path": str(artifact_path).replace("\\", "/"),
            "sha256": _file_sha256(artifact_path),
            "exists": artifact_path.is_file(),
            "size": artifact_path.stat().st_size if artifact_path.is_file() else None,
        }

    meta = {
        "base_run_id": base_run_id,
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "scaffold_version": scaffold_version,
        "scaffold_sha256": scaffold_hashes,
        "representative_artifact": representative,
        "patch_family": patch_family,
        "output_root": output_root,
        "retroactive": retroactive,
    }
    if notes:
        meta["notes"] = notes

    event = LedgerEvent(
        run_id=run_id,
        phase="meta",
        status="recorded",
        extra=meta,
    )
    append_event(event)
    return event


def query_run_meta(run_id: str, sqlite_path: Path | None = None) -> dict | None:
    """Return the most recent meta event for a run, or None if never recorded.

    sqlite_path resolves at CALL time (not import time) so tests can monkeypatch
    the module-level SQLITE_PATH between calls and have reads honor the patch.
    Production callers pass None (default) and get the global path.
    """
    if sqlite_path is None:
        sqlite_path = SQLITE_PATH
    if not sqlite_path.exists():
        return None
    conn = _open_db(sqlite_path)
    try:
        row = conn.execute(
            """SELECT extra_json, timestamp FROM events
               WHERE run_id = ? AND phase = 'meta'
               ORDER BY timestamp DESC LIMIT 1""",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    try:
        d = json.loads(row[0]) if row[0] else {}
    except (json.JSONDecodeError, TypeError):
        d = {}
    d["meta_recorded_at"] = row[1]
    return d


def rebuild_index(sqlite_path: Path | None = None) -> dict:
    """Drop the SQLite index and rebuild it from every JSONL under LEDGER_DIR.

    Returns counts dict for diagnostics. JSONL files are never touched.
    """
    if sqlite_path is None:
        sqlite_path = SQLITE_PATH
    if sqlite_path.exists():
        sqlite_path.unlink()
    conn = _open_db(sqlite_path)
    counts = {"runs": 0, "events": 0, "errors": 0}
    if not LEDGER_DIR.exists():
        conn.close()
        return counts

    for jp in sorted(LEDGER_DIR.glob("*.jsonl")):
        with _conn_tx(conn):
            for line in jp.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    event = LedgerEvent(
                        run_id=d["run_id"],
                        phase=d["phase"],
                        status=d["status"],
                        timestamp=d.get("timestamp") or datetime.now(UTC).isoformat(),
                        task_id=d.get("task_id"),
                        score=d.get("score"),
                        failures=d.get("failures"),
                        artifact=d.get("artifact"),
                        extra=d.get("extra"),
                    )
                    _insert_event(conn, event)
                    _bump_run_seen(conn, event)
                    counts["events"] += 1
                except (KeyError, ValueError, sqlite3.Error) as e:
                    counts["errors"] += 1
                    print(f"[ledger] skipped bad line in {jp.name}: {e}", file=sys.stderr)
        counts["runs"] += 1
    conn.close()
    return counts


# ---------------------------------------------------------------------------
# Reader API (used by monitor + advisor)
# ---------------------------------------------------------------------------


def query_run_summary(run_id: str, sqlite_path: Path | None = None) -> dict:
    """Roll up a single run: # tasks completed, score distribution, top families."""
    if sqlite_path is None:
        sqlite_path = SQLITE_PATH
    if not sqlite_path.exists():
        rebuild_index(sqlite_path)
    conn = _open_db(sqlite_path)
    try:
        rows = conn.execute(
            """SELECT task_id, phase, status, score, failures_json, artifact, timestamp
               FROM events WHERE run_id = ? ORDER BY timestamp""",
            (run_id,),
        ).fetchall()
    finally:
        conn.close()

    by_task: dict[str, list[dict]] = {}
    for r in rows:
        d = {
            "task_id": r[0],
            "phase": r[1],
            "status": r[2],
            "score": r[3],
            "failures_json": r[4],
            "artifact": r[5],
            "timestamp": r[6],
        }
        by_task.setdefault(r[0] or "_global", []).append(d)

    # Tasks considered "completed" if they have an eval event with status=completed
    completed_tasks = []
    scores = []
    family_totals: dict[str, int] = {}
    for task_id, events in by_task.items():
        if task_id == "_global":
            continue
        evs = [e for e in events if e["phase"] == "eval" and e["status"] == "completed"]
        if not evs:
            continue
        e = evs[-1]
        completed_tasks.append(task_id)
        if e["score"] is not None:
            scores.append(e["score"])
        if e["failures_json"]:
            try:
                fams = json.loads(e["failures_json"])
                for k, v in fams.items():
                    family_totals[k] = family_totals.get(k, 0) + int(v)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

    return {
        "run_id": run_id,
        "completed_tasks": len(completed_tasks),
        "scores": scores,
        "rolling_avg": round(sum(scores) / len(scores), 1) if scores else 0.0,
        "top_families": sorted(family_totals.items(), key=lambda kv: -kv[1])[:15],
    }


def query_runs(sqlite_path: Path | None = None) -> list[dict]:
    """Return high-level info for every known run."""
    if sqlite_path is None:
        sqlite_path = SQLITE_PATH
    if not sqlite_path.exists():
        rebuild_index(sqlite_path)
    conn = _open_db(sqlite_path)
    try:
        rows = conn.execute(
            "SELECT run_id, kind, started_at, last_seen_at, n_events FROM runs ORDER BY last_seen_at DESC"
        ).fetchall()
    finally:
        conn.close()
    return [
        {"run_id": r[0], "kind": r[1], "started_at": r[2], "last_seen_at": r[3], "n_events": r[4]}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Backfill: existing ProgramBench eval JSONs -> ledger events
# ---------------------------------------------------------------------------


def backfill_programbench_eval_jsons(
    run_id: str = "mass_run_v2_base",
    eval_root: Path = Path("T:/determinex-programbench/mass_run_v2_base"),
) -> int:
    """Scan an existing programbench eval dir and replay each *.eval.json as a
    'phase=eval status=completed' event. Idempotent — re-running de-dupes by
    artifact path.
    """
    if not eval_root.exists():
        print(f"[ledger] eval_root missing: {eval_root}", file=sys.stderr)
        return 0

    existing_artifacts = _existing_eval_artifacts(run_id)
    n_added = 0
    for ej in sorted(eval_root.glob("*/*.eval.json")):
        artifact = str(ej).replace("\\", "/")
        if artifact in existing_artifacts:
            continue
        try:
            d = json.loads(ej.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        results = d.get("test_results", [])
        passed = sum(1 for r in results if r.get("status") == "passed")
        failed = sum(1 for r in results if r.get("status") == "failure")
        total = passed + failed
        score = round(100 * passed / total, 1) if total else 0.0

        # Family histogram via the same classifier the live one uses
        families = _classify_failures(results)

        task_id = ej.stem.replace(".eval", "")
        # Get the file's mtime as a stable backfill timestamp
        mtime = ej.stat().st_mtime
        ts = (
            datetime.fromtimestamp(mtime, tz=UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )

        event = LedgerEvent(
            run_id=run_id,
            task_id=task_id,
            phase="eval",
            status="completed",
            timestamp=ts,
            score=score,
            failures=dict(families) if families else None,
            artifact=artifact,
            extra={"passed": passed, "failed": failed, "total": total, "backfill": True},
        )
        append_event(event)
        n_added += 1
    return n_added


def _existing_eval_artifacts(run_id: str, sqlite_path: Path | None = None) -> set[str]:
    """Set of artifact paths already recorded for this run's eval phase."""
    if sqlite_path is None:
        sqlite_path = SQLITE_PATH
    if not sqlite_path.exists():
        return set()
    conn = _open_db(sqlite_path)
    try:
        rows = conn.execute(
            "SELECT artifact FROM events WHERE run_id = ? AND phase = 'eval' AND artifact IS NOT NULL",
            (run_id,),
        ).fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows}


# Failure classification routes through the single-source-of-truth taxonomy
# at scripts/determinex_pb_taxonomy.py. This module's previous local _FAMILY_RX
# was an identical duplicate; removed during the round-1 dedup so the cockpit
# cannot disagree with the live classifier on which family a test belongs to.
def _classify_failures(test_results: Iterable[dict]) -> Counter[str]:
    # Lazy import: keeps run_ledger.py importable even when running from a
    # location where the taxonomy module isn't on sys.path yet (e.g. early in
    # the CLI before the bootstrap insert).
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from determinex_pb_taxonomy import classify_test_results

    return classify_test_results(test_results)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli():
    ap = argparse.ArgumentParser(description="Determinex universal run ledger")
    ap.add_argument("--append-event", help="JSON event blob to append (single-line JSON)")
    ap.add_argument("--rebuild", action="store_true", help="rebuild SQLite index from JSONL")
    ap.add_argument("--summary", help="print summary for one run_id (or --summary=all)")
    ap.add_argument(
        "--backfill-pb-eval-jsons",
        action="store_true",
        help="ingest existing mass_run_v2_base/*.eval.json files as events",
    )
    ap.add_argument(
        "--record-run-meta",
        action="store_true",
        help="record provenance for a run (call BEFORE its eval phase starts)",
    )
    ap.add_argument("--base-run-id", help="anchor run this run is being compared against")
    ap.add_argument(
        "--scaffold-version", help="human label for the scaffold variant, e.g. clap_unknown_arg_v1"
    )
    ap.add_argument("--patch-family", help="failure family the scaffold patch targets")
    ap.add_argument("--output-root", help="where artifacts for this run land")
    ap.add_argument(
        "--representative-artifact",
        help="path to one artifact actually produced by this run (sha256 is captured)",
    )
    ap.add_argument(
        "--retroactive",
        action="store_true",
        help="mark meta as retroactively recorded (after the run started)",
    )
    ap.add_argument("--notes", help="free-form note attached to meta")
    ap.add_argument("--query-meta", help="print meta JSON for a run_id")
    ap.add_argument("--run-id", default="mass_run_v2_base", help="run_id for backfill")
    ap.add_argument(
        "--eval-root",
        type=Path,
        default=Path("T:/determinex-programbench/mass_run_v2_base"),
        help="eval dir for backfill",
    )
    args = ap.parse_args()

    if args.append_event:
        d = json.loads(args.append_event)
        evt = LedgerEvent(
            run_id=d["run_id"],
            phase=d["phase"],
            status=d["status"],
            timestamp=d.get("timestamp")
            or datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            task_id=d.get("task_id"),
            score=d.get("score"),
            failures=d.get("failures"),
            artifact=d.get("artifact"),
            extra=d.get("extra"),
        )
        jp = append_event(evt)
        print(f"appended to {jp}")
        return

    if args.rebuild:
        counts = rebuild_index()
        print(json.dumps({"rebuilt": True, **counts}, indent=2))
        return

    if args.record_run_meta:
        if not args.run_id and not args.summary:
            raise SystemExit("--record-run-meta requires --run-id <id>")
        evt = record_run_meta(
            run_id=args.run_id,
            base_run_id=args.base_run_id,
            scaffold_version=args.scaffold_version,
            patch_family=args.patch_family,
            output_root=args.output_root,
            representative_artifact=Path(args.representative_artifact)
            if args.representative_artifact
            else None,
            notes=args.notes,
            retroactive=args.retroactive,
        )
        print(json.dumps({"recorded": True, **(evt.extra or {})}, indent=2, default=str))
        return

    if args.query_meta:
        m = query_run_meta(args.query_meta)
        print(json.dumps(m or {"error": "no meta recorded"}, indent=2, default=str))
        return

    if args.backfill_pb_eval_jsons:
        n = backfill_programbench_eval_jsons(run_id=args.run_id, eval_root=args.eval_root)
        print(
            json.dumps(
                {"backfilled": n, "run_id": args.run_id, "eval_root": str(args.eval_root)}, indent=2
            )
        )
        return

    if args.summary:
        if args.summary == "all":
            print(json.dumps({"runs": query_runs()}, indent=2, default=str))
        else:
            print(json.dumps(query_run_summary(args.summary), indent=2, default=str))
        return

    ap.print_help()


if __name__ == "__main__":
    _cli()
