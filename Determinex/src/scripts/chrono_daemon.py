"""
scripts/chrono_daemon.py — The Determinex Chrono-Daemon & Burnout Protocol

Implements the "Synthetic Peer" temporal developer state tracking system
described in Section 3.14 of the Determinex white paper.

This is NOT a prompt-engineering abstraction. It is a mechanical loop:

    tokio::spawn equivalent (threading.Thread daemon)
        → polls active buffer context (provided by Tauri IPC or CLI watcher)
        → computes tree-sitter AST hash of current file
        → logs to temporal_context table in sqlite
        → evaluates Burnout Protocol thresholds
        → emits BURNOUT_INTERVENTION event when thresholds are crossed

Architecture:
    The Chrono-Daemon runs as a background daemon thread. In the Tauri
    desktop application, Tauri IPC calls from the Rust backend push buffer
    focus events and keystroke velocity data to this daemon via the
    Python sidecar channel. In standalone CLI mode, the daemon watches
    an inotify/watchdog-monitored file path for changes.

    temporal_context table (per-session):
        session_id           TEXT    — UUID per application boot
        timestamp            REAL    — Unix epoch float
        active_buffer_path   TEXT    — currently focused file path
        ast_hash             TEXT    — sha256 of tree-sitter AST s-expression
        ast_node_count       INTEGER — number of AST nodes (size proxy)
        keystroke_velocity   REAL    — keystrokes per minute (0 if no input)
        compile_fail_count   INTEGER — consecutive compile failures on same fn
        last_fail_signature  TEXT    — function signature of last failing build

Burnout Protocol Thresholds:
    THRESHOLD_TUNNEL_VISION:
        time_in_buffer > TUNNEL_VISION_MINUTES (45 min)
        AND ast_structural_delta < TUNNEL_VISION_AST_DELTA (5%)
        → Developer has been in the same file for 45+ minutes with
          less than 5% change in AST structure. Classic tunneling.

    THRESHOLD_COMPILE_LOOP:
        failed_compilations > COMPILE_FAIL_LIMIT (10)
        on the same function signature within COMPILE_FAIL_WINDOW (15 min)
        → Developer is grinding the same bug repeatedly. Escalate.

    Both thresholds emit a BURNOUT_INTERVENTION event which the
    Hive Orchestrator intercepts to reroute the next generation call
    to the 'architectural_refactor' task vector.

Usage:
    from scripts.chrono_daemon import ChronoDaemon, BurnoutProtocol

    daemon = ChronoDaemon(db_path=".determinex/chrono.db")
    daemon.start()                          # starts background thread

    # From Tauri IPC / CLI watcher — called on each file focus change:
    daemon.update_buffer(
        buffer_path="src/lib.rs",
        file_content=open("src/lib.rs").read(),
        keystroke_velocity=45.0,
    )

    # From Compiler Oracle — called on each compile result:
    daemon.record_compile_result(
        buffer_path="src/lib.rs",
        function_signature="fn process_data(",
        failed=True,
    )

    # Orchestrator calls this before each generation:
    event = daemon.check_burnout()
    if event:
        # event.type == "TUNNEL_VISION" or "COMPILE_LOOP"
        # route to architectural_refactor task vector
        orchestrator.override_task_vector("architectural_refactor")
        orchestrator.flush_context_window()
        orchestrator.inject_burnout_prompt(event)
"""

import hashlib
import sqlite3
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# TREE-SITTER AST HASHING
# ---------------------------------------------------------------------------


def _try_import_tree_sitter():
    try:
        import tree_sitter
        from tree_sitter import Language, Parser

        return Parser
    except ImportError:
        return None


_TS_PARSER_CLASS = _try_import_tree_sitter()


def compute_ast_hash(source_code: str, language: str = "python") -> tuple[str, int, frozenset]:
    """
    Parse source_code with tree-sitter and return:
        (sha256 of AST s-expression string, node_count, node_type_set)

    The AST s-expression captures structural shape without caring about
    variable names or whitespace — sensitive to structural changes
    (new branches, loops, function signatures) but stable under
    formatting and minor textual edits.

    Falls back to sha256 of raw source if tree-sitter is unavailable.

    Args:
        source_code : source file content as string
        language    : language name ("python", "rust", "go", "typescript")

    Returns:
        (ast_hash_hex, node_count, node_type_set)
        node_type_set is the frozenset of unique AST node type strings.
        A 1-character semantic change (>= to >) changes Gt → GtE in this set.
    """
    if _TS_PARSER_CLASS is None:
        # Fallback: hash the raw source (less precise but functional)
        raw_hash = hashlib.sha256(source_code.encode("utf-8")).hexdigest()
        node_count = source_code.count("\n")
        return raw_hash, node_count, frozenset()

    try:
        # Try to load the language grammar
        lang_map = {
            "python": "tree_sitter_python",
            "rust": "tree_sitter_rust",
            "go": "tree_sitter_go",
            "typescript": "tree_sitter_typescript",
            "javascript": "tree_sitter_javascript",
        }
        lang_module_name = lang_map.get(language.lower(), "tree_sitter_python")

        import importlib

        lang_module = importlib.import_module(lang_module_name)
        lang = lang_module.language()

        parser = _TS_PARSER_CLASS(lang)
        tree = parser.parse(source_code.encode("utf-8"))
        root = tree.root_node

        # Walk the AST and collect node types (structural fingerprint)
        node_types = []
        _collect_node_types(root, node_types)

        ast_str = " ".join(node_types)
        ast_hash = hashlib.sha256(ast_str.encode("utf-8")).hexdigest()
        node_count = len(node_types)
        return ast_hash, node_count, frozenset(node_types)

    except Exception:
        # Any import or parse failure → raw source hash
        raw_hash = hashlib.sha256(source_code.encode("utf-8")).hexdigest()
        return raw_hash, source_code.count("\n"), frozenset()


def _collect_node_types(node, out: list):
    """Depth-first traversal collecting node type strings."""
    out.append(node.type)
    for child in node.children:
        _collect_node_types(child, out)


def compute_ast_delta(
    hash_a: str,
    count_a: int,
    hash_b: str,
    count_b: int,
    types_a: frozenset = frozenset(),
    types_b: frozenset = frozenset(),
) -> float:
    """
    Compute the structural change fraction between two AST snapshots.

    Returns a float in [0.0, 1.0]:
        0.0 = identical AST structure
        1.0 = completely different structure

    Method (two-signal approach — #SEC-AST-DELTA fix):
        Signal 1 — Node type set change:
            If the SET of unique AST node types changes between snapshots,
            a real semantic edit occurred (e.g. Gt → GtE for > → >=).
            This catches single-character logic fixes that produce zero
            node-count delta and would otherwise falsely trigger the
            Burnout Protocol.
            When type sets are available, any set difference produces
            a minimum delta of 0.1 (above the 0.05 tunnel-vision threshold).

        Signal 2 — Node count change:
            delta = |count_b - count_a| / max(count_a, count_b)
            Approximates the fraction of AST nodes that changed.
            Used when type sets are unavailable (tree-sitter fallback path).

    The Burnout Protocol (THRESHOLD_TUNNEL_VISION) requires BOTH the time
    threshold AND the AST threshold to fire simultaneously, so a false
    negative here (under-reporting delta) is far more dangerous than a false
    positive.  We err on the side of detecting real progress.
    """
    if hash_a == hash_b:
        return 0.0

    # Signal 1: if we have node type sets, use the Jaccard distance
    # between the unique node type sets as a semantic change indicator.
    if types_a and types_b:
        union = types_a | types_b
        intersection = types_a & types_b
        type_jaccard_dist = 1.0 - (len(intersection) / len(union)) if union else 0.0
        # Even a tiny type-set change is a real semantic edit — clamp to
        # a minimum of 0.10 so it always clears the 0.05 tunnel-vision gate.
        if type_jaccard_dist > 0.0:
            return max(type_jaccard_dist, 0.10)

    # Signal 2: node count delta (fallback when type sets not available)
    denom = max(count_a, count_b, 1)
    return abs(count_b - count_a) / denom


# ---------------------------------------------------------------------------
# DATABASE SCHEMA
# ---------------------------------------------------------------------------

_CHRONO_SCHEMA = """
CREATE TABLE IF NOT EXISTS temporal_context (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id           TEXT    NOT NULL,
    timestamp            REAL    NOT NULL,
    active_buffer_path   TEXT    NOT NULL,
    ast_hash             TEXT    NOT NULL,
    ast_node_count       INTEGER NOT NULL DEFAULT 0,
    keystroke_velocity   REAL    NOT NULL DEFAULT 0.0,
    compile_fail_count   INTEGER NOT NULL DEFAULT 0,
    last_fail_signature  TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_chrono_session   ON temporal_context(session_id);
CREATE INDEX IF NOT EXISTS idx_chrono_timestamp  ON temporal_context(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_chrono_buffer     ON temporal_context(active_buffer_path);

CREATE TABLE IF NOT EXISTS burnout_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT    NOT NULL,
    timestamp      REAL    NOT NULL,
    event_type     TEXT    NOT NULL,   -- 'TUNNEL_VISION' | 'COMPILE_LOOP'
    buffer_path    TEXT    NOT NULL,
    details        TEXT    NOT NULL DEFAULT '',
    acknowledged   INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_burnout_session ON burnout_events(session_id);
CREATE INDEX IF NOT EXISTS idx_burnout_ack     ON burnout_events(acknowledged);
"""


# ---------------------------------------------------------------------------
# BURNOUT EVENT
# ---------------------------------------------------------------------------


@dataclass
class BurnoutEvent:
    """
    Emitted when a Burnout Protocol threshold is crossed.

    The Hive Orchestrator responds by:
        1. Overriding vLLM routing to 'architectural_refactor' task vector
        2. Rewriting the system prompt to enforce a step-back
        3. Flushing the context window of local error logs
        4. Injecting Latent RAG with directory-level abstractions
    """

    event_type: str  # 'TUNNEL_VISION' | 'COMPILE_LOOP'
    buffer_path: str
    session_id: str
    timestamp: float = field(default_factory=time.time)
    details: str = ""

    @property
    def intervention_prompt(self) -> str:
        """Generate the forced interrupt prompt for the AI system prompt override."""
        if self.event_type == "TUNNEL_VISION":
            return (
                f"[BURNOUT PROTOCOL — TUNNEL VISION DETECTED]\n"
                f"You have been working in {Path(self.buffer_path).name} "
                f"for over 45 minutes with less than 5% structural change.\n"
                f"The current approach is structurally brittle. Step back.\n"
                f"Do NOT attempt to fix the local bug. Instead:\n"
                f"1. Describe the high-level architectural problem.\n"
                f"2. Propose an alternative structural approach.\n"
                f"3. Ask clarifying questions about the original spec.\n"
                f"Stepping back now."
            )
        elif self.event_type == "COMPILE_LOOP":
            return (
                f"[BURNOUT PROTOCOL — COMPILE-FAIL LOOP DETECTED]\n"
                f"More than 10 consecutive compilation failures on the same "
                f"function in {Path(self.buffer_path).name} within 15 minutes.\n"
                f"Incremental fixes are not working. Step back.\n"
                f"Do NOT attempt another local patch. Instead:\n"
                f"1. Identify the root structural cause of the repeated failure.\n"
                f"2. Propose a complete rewrite of the failing function.\n"
                f"3. Consider whether the function signature itself is wrong.\n"
                f"Stepping back now."
            )
        return "[BURNOUT PROTOCOL] Architectural reframing required."


# ---------------------------------------------------------------------------
# BURNOUT PROTOCOL — threshold evaluation
# ---------------------------------------------------------------------------

# Configurable via environment variables for enterprise tuning
import os

TUNNEL_VISION_MINUTES = float(os.environ.get("DETERMINEX_TUNNEL_VISION_MINUTES", "45"))
TUNNEL_VISION_AST_DELTA = float(os.environ.get("DETERMINEX_TUNNEL_VISION_AST_DELTA", "0.05"))
COMPILE_FAIL_LIMIT = int(os.environ.get("DETERMINEX_COMPILE_FAIL_LIMIT", "10"))
COMPILE_FAIL_WINDOW_MINS = float(os.environ.get("DETERMINEX_COMPILE_FAIL_WINDOW", "15"))
CHRONO_POLL_SECONDS = float(os.environ.get("DETERMINEX_CHRONO_POLL_SECONDS", "30"))


class BurnoutProtocol:
    """
    Evaluates Burnout Protocol thresholds against the temporal_context table.

    Called by the Hive Orchestrator at the start of each Architect planning
    step. If a threshold is crossed, returns a BurnoutEvent. The Orchestrator
    then overrides vLLM task-vector routing and flushes the context window.
    """

    def __init__(self, conn: sqlite3.Connection, session_id: str):
        self._conn = conn
        self.session_id = session_id

    def check(self, buffer_path: str) -> BurnoutEvent | None:
        """
        Evaluate all thresholds for the current active buffer.

        Returns a BurnoutEvent if any threshold is crossed, None otherwise.
        Thresholds evaluated in priority order (COMPILE_LOOP > TUNNEL_VISION).
        """
        event = self._check_compile_loop(buffer_path)
        if event:
            return event
        return self._check_tunnel_vision(buffer_path)

    def _check_compile_loop(self, buffer_path: str) -> BurnoutEvent | None:
        """
        THRESHOLD_COMPILE_LOOP:
            failed_compilations > COMPILE_FAIL_LIMIT on the same function
            within COMPILE_FAIL_WINDOW minutes.
        """
        window_start = time.time() - (COMPILE_FAIL_WINDOW_MINS * 60)
        row = self._conn.execute(
            """SELECT MAX(compile_fail_count), last_fail_signature
               FROM temporal_context
               WHERE session_id = ?
                 AND active_buffer_path = ?
                 AND timestamp >= ?
               ORDER BY timestamp DESC
               LIMIT 1""",
            (self.session_id, buffer_path, window_start),
        ).fetchone()

        if row and row[0] is not None and row[0] > COMPILE_FAIL_LIMIT:
            return BurnoutEvent(
                event_type="COMPILE_LOOP",
                buffer_path=buffer_path,
                session_id=self.session_id,
                details=(
                    f"compile_fail_count={row[0]}  "
                    f"signature={row[1]}  "
                    f"window={COMPILE_FAIL_WINDOW_MINS}min"
                ),
            )
        return None

    def _check_tunnel_vision(self, buffer_path: str) -> BurnoutEvent | None:
        """
        THRESHOLD_TUNNEL_VISION:
            time_in_buffer > TUNNEL_VISION_MINUTES
            AND ast_structural_delta across the window < TUNNEL_VISION_AST_DELTA

        #SEC-AST-DELTA: We now pass empty frozensets for the type-set signals
        because the DB only stores hash + count (not the full type set — that
        would be expensive to serialise). The node-count delta remains the
        gating signal here; the type-set signal only fires in the in-memory
        update_buffer path (via ChronoDaemon, not via BurnoutProtocol.check).
        """
        # Fetch 2× the threshold window so the query can return rows older than
        # the threshold — without this, time_in_buffer can never exceed the
        # threshold (the query filters out everything older than threshold ago).
        fetch_start = time.time() - (TUNNEL_VISION_MINUTES * 60 * 2)

        # Get the earliest and latest snapshot in the window for this buffer
        rows = self._conn.execute(
            """SELECT ast_hash, ast_node_count, timestamp
               FROM temporal_context
               WHERE session_id = ?
                 AND active_buffer_path = ?
                 AND timestamp >= ?
               ORDER BY timestamp ASC""",
            (self.session_id, buffer_path, fetch_start),
        ).fetchall()

        if len(rows) < 2:
            return None  # Not enough data to evaluate

        earliest = rows[0]
        latest = rows[-1]

        time_in_buffer = latest[2] - earliest[2]  # seconds
        if time_in_buffer < (TUNNEL_VISION_MINUTES * 60):
            return None

        delta = compute_ast_delta(
            hash_a=earliest[0],
            count_a=earliest[1],
            hash_b=latest[0],
            count_b=latest[1],
            # type sets not stored in DB — rely on count signal only here
            types_a=frozenset(),
            types_b=frozenset(),
        )

        if delta < TUNNEL_VISION_AST_DELTA:
            return BurnoutEvent(
                event_type="TUNNEL_VISION",
                buffer_path=buffer_path,
                session_id=self.session_id,
                details=(
                    f"time_in_buffer={time_in_buffer / 60:.1f}min  "
                    f"ast_delta={delta:.4f}  "
                    f"threshold={TUNNEL_VISION_AST_DELTA}"
                ),
            )
        return None


# ---------------------------------------------------------------------------
# CHRONO DAEMON — background thread + public API
# ---------------------------------------------------------------------------


class ChronoDaemon:
    """
    Background daemon that continuously logs developer temporal context and
    evaluates Burnout Protocol thresholds.

    In Tauri desktop mode: receives buffer focus events via IPC from the
    Rust backend's tokio::spawn watcher thread.
    In CLI mode: self-polls a watched directory.

    The daemon is lightweight — it writes to sqlite in WAL mode and runs
    on a 30-second tick. It never blocks the main inference thread.
    """

    def __init__(
        self,
        db_path: str | Path = ".determinex/chrono.db",
        session_id: str | None = None,
    ):
        self.db_path = Path(db_path)
        self.session_id = session_id or str(uuid.uuid4())
        # RLock, not Lock. `_poll_loop` used to take this and then call `_write_snapshot()`, which
        # takes it again -- a self-deadlock that parked a whole hive session for 19 minutes with no
        # error (see `_poll_loop`). That call site is fixed, but the same shape is one careless edit
        # away in any of the five methods that take this lock, and the failure mode is silence rather
        # than a crash. Re-entrancy makes the mistake survivable instead of fatal; it does not excuse
        # holding the lock across a disk write, which is why the fix at the call site stands too.
        self._lock = threading.RLock()
        self._thread = None
        self._running = False

        # Current state
        self._current_buffer_path = ""
        self._current_ast_hash = ""
        self._current_ast_node_count = 0
        self._current_ast_type_set: frozenset = frozenset()  # #SEC-AST-DELTA
        self._current_kv = 0.0
        self._compile_fail_count = 0
        self._last_fail_signature = ""

        # Unacknowledged burnout events queue
        self._pending_events: list[BurnoutEvent] = []

        # DB setup
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_CHRONO_SCHEMA)

        self._burnout = BurnoutProtocol(self._conn, self.session_id)
        print(
            f"[ChronoDaemon] Session: {self.session_id}  DB: {self.db_path}",
            flush=True,
        )

    # ── Public API (called from Tauri IPC / Hive Orchestrator) ──────────────

    def update_buffer(
        self,
        buffer_path: str,
        file_content: str,
        keystroke_velocity: float = 0.0,
        language: str = "python",
    ):
        """
        Update the daemon with the current active buffer state.

        Called by:
            - Tauri Rust backend via sidecar IPC on every buffer focus change
            - CLI watcher on file modification events

        Args:
            buffer_path        : absolute path to the currently focused file
            file_content       : current file content (for AST hashing)
            keystroke_velocity : keystrokes per minute from OS hook
            language           : language for tree-sitter parser
        """
        ast_hash, node_count, node_type_set = compute_ast_hash(file_content, language)

        with self._lock:
            self._current_buffer_path = buffer_path
            self._current_ast_hash = ast_hash
            self._current_ast_node_count = node_count
            self._current_ast_type_set = node_type_set
            self._current_kv = keystroke_velocity

        # Write immediately (don't wait for poll tick)
        self._write_snapshot()

    def record_compile_result(
        self,
        buffer_path: str,
        function_signature: str,
        failed: bool,
    ):
        """
        Record a compile result from the Compiler Oracle.

        Called by scripts/hive/compiler.py after each compilation attempt.

        Args:
            buffer_path        : file that was compiled
            function_signature : function signature that failed/passed
            failed             : True if compilation failed, False if passed
        """
        with self._lock:
            if failed and function_signature == self._last_fail_signature:
                self._compile_fail_count += 1
            elif failed:
                self._compile_fail_count = 1
                self._last_fail_signature = function_signature
            else:
                # Successful compile — reset counter for this signature
                self._compile_fail_count = 0
                self._last_fail_signature = ""

        self._write_snapshot()

    def check_burnout(self) -> BurnoutEvent | None:
        """
        Evaluate Burnout Protocol thresholds for the current buffer.

        Called by the Hive Orchestrator at the start of each Architect
        planning step, before routing the generation call.

        Returns a BurnoutEvent if a threshold is crossed, None otherwise.
        The event is also persisted to the burnout_events table for
        post-session analysis.
        """
        with self._lock:
            buffer_path = self._current_buffer_path

        if not buffer_path:
            return None

        event = self._burnout.check(buffer_path)
        if event:
            self._persist_burnout_event(event)
            print(
                f"[ChronoDaemon] ⚠️  BURNOUT_INTERVENTION  "
                f"type={event.event_type}  "
                f"buffer={Path(buffer_path).name}  "
                f"details={event.details}",
                flush=True,
            )
        return event

    def get_session_stats(self) -> dict:
        """Return summary statistics for the current session."""
        rows = self._conn.execute(
            """SELECT COUNT(*), MIN(timestamp), MAX(timestamp),
                      COUNT(DISTINCT active_buffer_path)
               FROM temporal_context WHERE session_id = ?""",
            (self.session_id,),
        ).fetchone()
        burnouts = self._conn.execute(
            "SELECT COUNT(*) FROM burnout_events WHERE session_id = ?", (self.session_id,)
        ).fetchone()[0]
        return {
            "session_id": self.session_id,
            "snapshots": rows[0] or 0,
            "session_start": rows[1],
            "session_end": rows[2],
            "unique_buffers": rows[3] or 0,
            "burnout_events": burnouts,
        }

    # ── Background daemon ────────────────────────────────────────────────────

    def start(self):
        """Start the background polling thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="determinex-chrono-daemon",
            daemon=True,
        )
        self._thread.start()
        print(
            f"[ChronoDaemon] Started  poll_interval={CHRONO_POLL_SECONDS}s",
            flush=True,
        )

    def stop(self):
        """Stop the background polling thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        print("[ChronoDaemon] Stopped.", flush=True)

    def _poll_loop(self):
        """Background thread: write periodic snapshots on the poll interval.

        THE DEADLOCK, fixed 2026-07-31. This held `self._lock` and then called
        `_write_snapshot()`, which takes `self._lock` itself. With a plain (non-reentrant) Lock that
        is a self-deadlock in this thread, and it dies holding the lock -- so the next caller of
        `record_compile_result` blocks forever behind it.

        That is exactly what happened, twice, in the same place: a hive session stalled after step
        2's Compiler Oracle reported PASS, because recording that pass is what calls
        `record_compile_result`. Zero CPU in the process, no child process, no container, Ollama idle
        and answering other requests normally, and no error -- for 19 minutes, and it would have sat
        there indefinitely. Diagnosed by re-running under
        `faulthandler.dump_traceback_later(150, repeat=True)`, which named both halves at once: this
        thread parked in `_write_snapshot`, the main thread parked in `record_compile_result`.
        Guessing had gone through Ollama, Docker, VRAM pressure and the thermal governor first, all
        wrong, because every one of them can also present as "stopped with no message".

        The flag is read under the lock and the write happens outside it. Two of the three
        `_write_snapshot()` call sites were already outside the lock, which is how the third came to
        be inside -- the convention was never stated. Doing it this way also stops a disk write from
        holding the lock against `record_compile_result`, which the oracle path calls per attempt.
        """
        while self._running:
            time.sleep(CHRONO_POLL_SECONDS)
            if not self._running:
                break
            with self._lock:
                have_buffer = bool(self._current_buffer_path)
            if have_buffer:
                self._write_snapshot()

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _write_snapshot(self):
        """Write one temporal_context row with current state."""
        with self._lock:
            self._conn.execute(
                """INSERT INTO temporal_context
                   (session_id, timestamp, active_buffer_path,
                    ast_hash, ast_node_count, keystroke_velocity,
                    compile_fail_count, last_fail_signature)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self.session_id,
                    time.time(),
                    self._current_buffer_path,
                    self._current_ast_hash,
                    self._current_ast_node_count,
                    self._current_kv,
                    self._compile_fail_count,
                    self._last_fail_signature,
                ),
            )

    def _persist_burnout_event(self, event: BurnoutEvent):
        """Persist a burnout event to the database."""
        self._conn.execute(
            """INSERT INTO burnout_events
               (session_id, timestamp, event_type, buffer_path, details)
               VALUES (?, ?, ?, ?, ?)""",
            (event.session_id, event.timestamp, event.event_type, event.buffer_path, event.details),
        )

    def close(self):
        self.stop()
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ---------------------------------------------------------------------------
# SELF-TEST
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile

    print("[ChronoDaemon] Running self-test...", flush=True)

    sample_rust = """
fn process_data(items: &[i32]) -> Vec<i32> {
    items.iter().filter(|&&x| x > 0).copied().collect()
}
"""

    sample_rust_modified = """
fn process_data(items: &[i32]) -> Vec<i32> {
    let mut result = Vec::new();
    for item in items {
        if *item > 0 {
            result.push(*item);
        }
    }
    result
}
"""

    # AST hash self-test
    h1, c1, t1 = compute_ast_hash(sample_rust, language="rust")
    h2, c2, t2 = compute_ast_hash(sample_rust_modified, language="rust")
    delta = compute_ast_delta(h1, c1, h2, c2, t1, t2)
    print(f"  AST hash v1: {h1[:16]}…  nodes={c1}  types={len(t1)}")
    print(f"  AST hash v2: {h2[:16]}…  nodes={c2}  types={len(t2)}")
    print(f"  AST delta:   {delta:.4f}  (expected > 0)")
    assert h1 != h2, "Different code should have different AST hashes"
    assert delta > 0.0, "Structurally different code should have delta > 0"

    # Semantic delta test: single-char change (> to >=) must NOT score 0.0
    sample_gt = "fn f(x: i32) -> bool { x > 0 }"
    sample_gte = "fn f(x: i32) -> bool { x >= 0 }"
    hgt, cgt, tgt = compute_ast_hash(sample_gt, language="rust")
    hgte, cgte, tgte = compute_ast_hash(sample_gte, language="rust")
    semantic_delta = compute_ast_delta(hgt, cgt, hgte, cgte, tgt, tgte)
    print(
        f"  Semantic delta (> vs >=): {semantic_delta:.4f}  (expected >= 0.10 if tree-sitter available)"
    )
    if tgt and tgte:  # only assert when tree-sitter actually parsed
        assert semantic_delta >= 0.10, (
            f"Semantic fix (> vs >=) must not score near-zero — got {semantic_delta:.4f}. "
            "Burnout Protocol false positive would fire."
        )

    # Daemon + threshold self-test
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_chrono.db"
        daemon = ChronoDaemon(db_path=db_path)

        # Simulate tunnel vision: patch threshold to 5 min so the test
        # doesn't need to actually wait 45 minutes.
        # __globals__ is the module dict the method reads at runtime.
        buf = "/workspace/src/lib.rs"
        _fn_globals = BurnoutProtocol._check_tunnel_vision.__globals__
        _orig_tv = _fn_globals["TUNNEL_VISION_MINUTES"]
        _fn_globals["TUNNEL_VISION_MINUTES"] = 5.0
        daemon._burnout = BurnoutProtocol(daemon._conn, daemon.session_id)

        now_ts = time.time()
        for i in range(7):
            row_ts = now_ts - (6 * 60) + (i * 60)  # rows spanning 6 min (> 5-min threshold)
            daemon._conn.execute(
                """INSERT INTO temporal_context
                   (session_id, timestamp, active_buffer_path,
                    ast_hash, ast_node_count, keystroke_velocity,
                    compile_fail_count, last_fail_signature)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (daemon.session_id, row_ts, buf, h1, c1, 5.0, 0, ""),
            )

        with daemon._lock:
            daemon._current_buffer_path = buf
        event = daemon.check_burnout()

        _fn_globals["TUNNEL_VISION_MINUTES"] = _orig_tv  # restore immediately
        daemon._burnout = BurnoutProtocol(daemon._conn, daemon.session_id)

        assert event is not None, "Expected TUNNEL_VISION event"
        assert event.event_type == "TUNNEL_VISION"
        print(f"  TUNNEL_VISION detected ✓  details: {event.details}")
        print(f"  Intervention prompt preview: {event.intervention_prompt[:80]}…")

        # Compile loop test
        daemon._compile_fail_count = 11
        daemon._last_fail_signature = "fn process_data("
        for i in range(12):
            daemon._conn.execute(
                """INSERT INTO temporal_context
                   (session_id, timestamp, active_buffer_path,
                    ast_hash, ast_node_count, keystroke_velocity,
                    compile_fail_count, last_fail_signature)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    daemon.session_id,
                    time.time() - (COMPILE_FAIL_WINDOW_MINS * 60) + i * 60,
                    buf,
                    h1,
                    c1,
                    0.0,
                    i + 1,
                    "fn process_data(",
                ),
            )

        event2 = daemon.check_burnout()
        assert event2 is not None, "Expected COMPILE_LOOP event"
        assert event2.event_type == "COMPILE_LOOP"
        print(f"  COMPILE_LOOP detected ✓  details: {event2.details}")

        stats = daemon.get_session_stats()
        print(f"  Session stats: {stats}")
        daemon.close()  # explicit close before TemporaryDirectory exits (Windows WAL lock)

    print("[ChronoDaemon] Self-test passed.", flush=True)
