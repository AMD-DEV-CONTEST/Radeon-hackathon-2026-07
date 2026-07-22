"""Flight Recorder: an append-only, hash-chained audit log of every agent
action (tool calls, confirm-gate decisions, turn boundaries). Ships behind
AETHERIS_AUDIT_ENABLED (default on) -- flip to "false" for an instant,
byte-identical rollback to the pre-Blackbox agent loop.

Each entry: {"seq", "ts", "session_id", "type", "actor", "payload",
"prev_hash", "hash"}. `hash` = sha256(canonical_json(entry minus "hash")).
Genesis is a fixed constant, not session-derived -- simpler, with no real
loss of tamper-resistance (an attacker who can rewrite the whole file can
recompute either form). What the chain protects and doesn't protect is
documented in docs/BLACKBOX.md (Fase F), not repeated here.

Entries never store raw file/command content (invariant I5) -- only a
length and a SHA-256 digest, so the log itself can't leak what the agent
actually read or wrote even if it's shared with someone (see UC-01: the
whole point is a client can hand this file to a third party).

scripts/audit_verify.py deliberately DUPLICATES the chain-walk in
verify_chain() below rather than importing this module, so a judge can
verify a session's log with zero Aetheris install -- keep the two in sync
by hand if the entry shape ever changes.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from core.atomic_io import atomic_write_text
from core.utils.constants import AUDIT_DIR

GENESIS_HASH = hashlib.sha256(b"aetheris-flight-recorder-genesis-v1").hexdigest()


def audit_enabled() -> bool:
    return os.getenv("AETHERIS_AUDIT_ENABLED", "true").lower() == "true"


def _canonical_json(obj: Dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _log_path(session_id: str) -> Path:
    return Path(AUDIT_DIR) / f"{session_id}.jsonl"


def _head_path(session_id: str) -> Path:
    return Path(AUDIT_DIR) / f"{session_id}.head"


def log_path_for(session_id: str) -> str:
    """Public accessor for the GET /api/audit/{id}/verify endpoint --
    avoids reaching into the underscore-prefixed _log_path directly from
    app.py."""
    return str(_log_path(session_id))


class FlightRecorder:
    """One instance per session_id -- see get_recorder(). The JSONL itself
    is opened in plain append mode with an explicit flush()+fsync() per
    write (NOT atomic_write_text, which does a full temp-file-then-replace
    rewrite -- that would make every single append cost O(log size)
    instead of O(1)). Only the tiny `.head` sidecar uses atomic_write_text,
    since it's rewritten in full every time and needs to never be
    half-written."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._lock = threading.Lock()
        Path(AUDIT_DIR).mkdir(parents=True, exist_ok=True)
        self._log_path = _log_path(session_id)
        self._head_path = _head_path(session_id)
        self._seq, self._head = self._load_tail()

    def _load_tail(self) -> Tuple[int, str]:
        if self._head_path.exists():
            try:
                data = json.loads(self._head_path.read_text(encoding="utf-8"))
                return int(data["seq"]), str(data["hash"])
            except Exception:
                pass  # sidecar missing/corrupt -- fall back to walking the real log once
        return self._recover_tail_from_log()

    def _recover_tail_from_log(self) -> Tuple[int, str]:
        if not self._log_path.exists():
            return 0, GENESIS_HASH
        seq, head = 0, GENESIS_HASH
        with open(self._log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                seq, head = entry["seq"], entry["hash"]
        return seq, head

    def append(self, entry_type: str, payload: Dict, actor: str = "system") -> Dict:
        with self._lock:
            self._seq += 1
            entry = {
                "seq": self._seq,
                "ts": time.time(),
                "session_id": self.session_id,
                "type": entry_type,
                "actor": actor,
                "payload": payload,
                "prev_hash": self._head,
            }
            entry_hash = hashlib.sha256(_canonical_json(entry).encode("utf-8")).hexdigest()
            entry["hash"] = entry_hash
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(_canonical_json(entry) + "\n")
                f.flush()
                os.fsync(f.fileno())
            atomic_write_text(self._head_path, json.dumps({"seq": self._seq, "hash": entry_hash}))
            self._head = entry_hash
            return entry

    def read_all(self, since_seq: int = 0) -> List[Dict]:
        if not self._log_path.exists():
            return []
        entries = []
        with open(self._log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if entry.get("seq", 0) > since_seq:
                    entries.append(entry)
        return entries

    @property
    def head_seq(self) -> int:
        return self._seq


_recorders: Dict[str, FlightRecorder] = {}
_recorders_lock = threading.Lock()


def get_recorder(session_id: str) -> FlightRecorder:
    """Process-local cache, one FlightRecorder per session_id. Not shared
    cross-process -- fine here, this backend is a single resident process
    per user (Fase 4.5 architecture), never multiple workers."""
    with _recorders_lock:
        rec = _recorders.get(session_id)
        if rec is None:
            rec = FlightRecorder(session_id)
            _recorders[session_id] = rec
        return rec


def verify_chain(log_path: str) -> Tuple[bool, List[str]]:
    """In-process verifier backing GET /api/audit/{session_id}/verify.
    Mirrors scripts/audit_verify.py's standalone logic -- see this
    module's docstring for why that's a deliberate duplication, not
    reuse."""
    errors: List[str] = []
    path = Path(log_path)
    if not path.exists():
        return True, []
    head = GENESIS_HASH
    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                errors.append(f"line {line_num}: invalid JSON")
                return False, errors
            if entry.get("prev_hash") != head:
                errors.append(f"seq {entry.get('seq')}: prev_hash mismatch, chain broken")
                return False, errors
            claimed_hash = entry.get("hash")
            recomputed = dict(entry)
            recomputed.pop("hash", None)
            real_hash = hashlib.sha256(_canonical_json(recomputed).encode("utf-8")).hexdigest()
            if real_hash != claimed_hash:
                errors.append(f"seq {entry.get('seq')}: hash mismatch, entry tampered")
                return False, errors
            head = claimed_hash
    return True, errors


async def audited_tool_call(
    session_id: Optional[str],
    tool_name: str,
    tool_content: str,
    owner: Optional[str],
    handler: Callable,
    on_entry: Optional[Callable[[Dict], None]] = None,
) -> Dict:
    """The single wrapper used at both TOOL_REGISTRY dispatch call sites
    (agent.py's auto-run path for non-gated tools, and app.py's
    POST /api/tools/execute for gated ones after approval). Preserves the
    exact try/except-returns-error-dict semantics both call sites already
    had, so this is a safe drop-in whether or not AETHERIS_AUDIT_ENABLED is
    set -- the flag only controls whether the append() calls happen, never
    whether the tool itself runs or what it returns.

    `on_entry`, if given, is called synchronously with each FlightRecorder
    entry as it's appended -- used by stream_agent() to also surface these
    live as `audit_entry` SSE events during an active turn, without this
    function needing to know anything about SSE itself."""
    enabled = audit_enabled() and bool(session_id)
    actor = owner or "unknown"
    if enabled:
        entry = get_recorder(session_id).append(
            "tool_call",
            {"tool": tool_name, "content_len": len(tool_content), "content_digest": _digest(tool_content)},
            actor=actor,
        )
        if on_entry:
            on_entry(entry)
    try:
        result = await handler(tool_content, owner, session_id)
    except Exception as e:
        result = {"error": str(e), "exit_code": 1}
    if enabled:
        result_text = json.dumps(result, sort_keys=True, ensure_ascii=False)
        entry = get_recorder(session_id).append(
            "tool_result",
            {
                "tool": tool_name,
                "exit_code": result.get("exit_code"),
                "result_len": len(result_text),
                "result_digest": _digest(result_text),
            },
            actor=actor,
        )
        if on_entry:
            on_entry(entry)
    return result
