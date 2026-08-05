#!/usr/bin/env python3
"""scripts/corpus_sentinel.py — Corpus Sentinel: the corpus talks without being asked.

Problem: corpus/programbench/build_knowledge.json is inert. It only "speaks" when
something reads it on demand. Nothing watches it, computes over what changed, and
tells anyone in real time. This is the fix — shaped like chrono_daemon.py's
poll -> evaluate -> emit loop, but pointed at the corpus instead of developer state.

Loop:
    poll watched corpus file(s) for content changes (per-top-level-key value diff,
    with list/dict sub-diffing so a change buried in a 16-item list or a large
    nested object is localized, not lost in truncation), debounced per key
    (DEBOUNCE_SECONDS) so a burst of rapid edits to the same key coalesces into
    one accumulated report instead of firing a model call per poll
        -> for each changed key, ask a LOCAL model (Ollama, zero-cost, no external
           call) for a one-line verdict-first "what changed and why it matters"
        -> print it immediately (real-time console) + append to an insight ledger
        -> optionally push it out via the existing determinex_notify.py webhook
           (Discord/Slack/Telegram) if DETERMINEX_NOTIFY_URL is set

This is a SUMMARIZER/WATCHER, not an oracle -- the model's verdict is an insight
prompt, not a claim of ground truth. It never blocks a write and never mutates the
corpus itself.

Usage:
    python3 scripts/corpus_sentinel.py                      # watch the default corpus, loop forever
    python3 scripts/corpus_sentinel.py --once                # single pass then exit (for cron/CI)
    python3 scripts/corpus_sentinel.py --watch path/to/other.json --interval 10
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from providers import local_ollama  # noqa: E402

log = logging.getLogger("corpus_sentinel")

DEFAULT_WATCH = ["corpus/programbench/build_knowledge.json"]
DEFAULT_MODEL = "determinex-observer-v6-dsl:latest"  # Monitor role: diagnosis/adjudication, per project role assignments
FALLBACK_MODEL = "qwen2.5-coder:7b-instruct"
DEBOUNCE_SECONDS = 20.0  # coalesce rapid repeat edits to the same key into one report
STATE_DIR = Path("logs/corpus_sentinel")
STATE_FILE = STATE_DIR / "state.json"
LEDGER_FILE = STATE_DIR / "insights.jsonl"
PID_FILE = STATE_DIR / "sentinel.pid"

_PROMPT_TRUNCATE = 1200

_SYSTEM_PROMPT = (
    "You are a terse engineering monitor watching a JSON knowledge corpus for changes. "
    "You will be shown a key name and its OLD and NEW value (possibly truncated). "
    "Reply with ONE or TWO sentences, verdict first: state what actually changed and why "
    "someone tracking this project should care -- a status flip (e.g. candidate_untried -> "
    "shipped), a number that moved, a new risk, a contradiction with something else. "
    "Do NOT restate the raw diff or describe the JSON structure. If the change looks "
    "cosmetic/non-substantive, say so plainly in one short sentence instead of padding."
)


_ID_FIELD_CANDIDATES = ["lever_id", "key", "id", "target", "order", "name"]


def _snapshot(path: Path) -> dict:
    """Returns key -> actual value (not a hash) so later diffs can localize
    exactly what changed inside a large list/dict instead of truncating blind."""
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.warning("could not read/parse %s: %s", path, e)
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _truncate(value) -> str:
    s = json.dumps(value, indent=2, ensure_ascii=False, default=str)
    if len(s) > _PROMPT_TRUNCATE:
        return s[:_PROMPT_TRUNCATE] + "\n...(truncated)"
    return s


def _diff(old: dict, new: dict) -> list[tuple[str, str]]:
    changes = []
    for k in new:
        if k not in old:
            changes.append((k, "added"))
        elif new[k] != old[k]:
            changes.append((k, "modified"))
    for k in old:
        if k not in new:
            changes.append((k, "removed"))
    return changes


def _find_id_field(item: dict) -> str | None:
    for candidate in _ID_FIELD_CANDIDATES:
        if candidate in item:
            return candidate
    return None


def _localize_change(old_val, new_val, depth: int = 0) -> str:
    """Instead of dumping the whole (possibly huge) old/new value truncated blind,
    try to isolate exactly which list-item or dict-key actually changed, so the
    model is shown the delta, not a haystack it might truncate right past."""
    if depth > 2:
        return f"OLD:\n{_truncate(old_val)}\n\nNEW:\n{_truncate(new_val)}"

    if isinstance(old_val, list) and isinstance(new_val, list) and old_val and new_val:
        if all(isinstance(x, dict) for x in old_val + new_val):
            id_field = _find_id_field(old_val[0])
            if id_field and all(id_field in x for x in old_val + new_val):
                old_by_id = {x[id_field]: x for x in old_val}
                new_by_id = {x[id_field]: x for x in new_val}
                lines = []
                for k in new_by_id:
                    if k not in old_by_id:
                        lines.append(
                            f"LIST ITEM ADDED ({id_field}={k}):\n{_truncate(new_by_id[k])}"
                        )
                    elif new_by_id[k] != old_by_id[k]:
                        sub = _localize_change(old_by_id[k], new_by_id[k], depth + 1)
                        lines.append(f"LIST ITEM CHANGED ({id_field}={k}):\n{sub}")
                for k in old_by_id:
                    if k not in new_by_id:
                        lines.append(
                            f"LIST ITEM REMOVED ({id_field}={k}):\n{_truncate(old_by_id[k])}"
                        )
                return "\n\n".join(lines) if lines else "(list reordered, no item content changed)"

    if isinstance(old_val, dict) and isinstance(new_val, dict):
        sub_changes = _diff(old_val, new_val)
        lines = []
        for k, change_type in sub_changes:
            if change_type == "added":
                lines.append(f"FIELD ADDED ({k}):\n{_truncate(new_val[k])}")
            elif change_type == "removed":
                lines.append(f"FIELD REMOVED ({k}):\n{_truncate(old_val[k])}")
            else:
                sub = _localize_change(old_val[k], new_val[k], depth + 1)
                lines.append(f"FIELD CHANGED ({k}):\n{sub}")
        return "\n\n".join(lines) if lines else "(no field-level delta detected)"

    return f"OLD:\n{_truncate(old_val)}\n\nNEW:\n{_truncate(new_val)}"


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(STATE_FILE)


def _append_ledger(record: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LEDGER_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _notify_webhook(message: str) -> None:
    if not os.environ.get("DETERMINEX_NOTIFY_URL"):
        return
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import determinex_notify  # noqa: PLC0415

        determinex_notify.post(
            os.environ["DETERMINEX_NOTIFY_URL"],
            determinex_notify.discord_payload(message, level="info", tool="corpus_sentinel"),
        )
    except Exception as e:
        log.warning("webhook push failed (non-fatal): %s", e)


class CorpusSentinel:
    def __init__(
        self,
        watch_paths: list[Path],
        model: str = DEFAULT_MODEL,
        interval: float = 15.0,
    ):
        self.watch_paths = watch_paths
        self.model = model
        self.interval = interval
        self.state = _load_state()

    def _ask_model(self, key: str, change_type: str, old_val, new_val) -> str:
        if change_type == "added":
            body = f"NEW VALUE:\n{_truncate(new_val)}"
        elif change_type == "removed":
            body = f"REMOVED VALUE:\n{_truncate(old_val)}"
        else:
            body = _localize_change(old_val, new_val)
        user = f"KEY: {key}\nCHANGE TYPE: {change_type}\n\n{body}"
        text = local_ollama.generate(_SYSTEM_PROMPT, user, model=self.model)
        if not text:
            text = local_ollama.generate(_SYSTEM_PROMPT, user, model=FALLBACK_MODEL)
        return text or f"(model unavailable) {change_type}: {key}"

    def run_once(self) -> int:
        n_events = 0
        state_dirty = False
        now = time.time()
        for path in self.watch_paths:
            path_key = str(path)
            first_time_seeing_this_file = path_key not in self.state
            new_snapshot = _snapshot(path)
            if not new_snapshot:
                continue
            if first_time_seeing_this_file:
                # Cold start: everything already in the file predates the sentinel --
                # establish the baseline silently, don't report pre-existing content
                # as if it just "changed".
                self.state[path_key] = {"reported": new_snapshot, "pending_since": {}}
                state_dirty = True
                print(
                    f"corpus_sentinel: baseline established for {path} "
                    f"({len(new_snapshot)} keys), reporting from next change onward",
                    flush=True,
                )
                continue

            file_state = self.state[path_key]
            if "reported" not in file_state:  # migrate old flat-snapshot state format
                file_state = {"reported": file_state, "pending_since": {}}
            reported = file_state["reported"]
            pending_since = file_state["pending_since"]

            # Diff against the last REPORTED baseline, not the last poll -- this is
            # what makes debouncing correct: a burst of edits to the same key
            # accumulates into one full diff instead of being sliced into several
            # partial, back-to-back model calls.
            changes = _diff(reported, new_snapshot)
            still_pending_keys = {key for key, _ in changes}
            for key in list(pending_since):
                if key not in still_pending_keys:
                    del pending_since[
                        key
                    ]  # value settled back to its reported state before debounce fired

            for key, change_type in changes:
                first_seen = pending_since.setdefault(key, now)
                if now - first_seen < DEBOUNCE_SECONDS:
                    continue  # still within the debounce window, wait for it to settle
                old_val = reported.get(key)
                new_val = new_snapshot.get(key)
                insight = self._ask_model(key, change_type, old_val, new_val)
                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                line = f"[{ts}] CORPUS SENTINEL — {path.name}:{key} ({change_type}) — {insight}"
                print(line, flush=True)
                _append_ledger(
                    {
                        "ts": ts,
                        "file": path_key,
                        "key": key,
                        "change_type": change_type,
                        "insight": insight,
                    }
                )
                _notify_webhook(f"`{path.name}:{key}` ({change_type}) — {insight}")
                n_events += 1
                reported[key] = new_val
                del pending_since[key]

            self.state[path_key] = {"reported": reported, "pending_since": pending_since}
            state_dirty = True
        if state_dirty:
            _save_state(self.state)
        return n_events

    def run_forever(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
        print(
            f"corpus_sentinel: watching {[str(p) for p in self.watch_paths]} "
            f"every {self.interval}s using model={self.model} (pid={os.getpid()})",
            flush=True,
        )
        try:
            while True:
                try:
                    self.run_once()
                except Exception as e:
                    log.error("sentinel pass failed (continuing): %s", e)
                time.sleep(self.interval)
        finally:
            if PID_FILE.exists() and PID_FILE.read_text(encoding="utf-8").strip() == str(
                os.getpid()
            ):
                PID_FILE.unlink()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--watch", action="append", default=None, help="corpus JSON file to watch (repeatable)"
    )
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--interval", type=float, default=15.0)
    ap.add_argument("--once", action="store_true", help="single pass then exit")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    watch_paths = [Path(p) for p in (args.watch or DEFAULT_WATCH)]
    sentinel = CorpusSentinel(watch_paths, model=args.model, interval=args.interval)

    if args.once:
        n = sentinel.run_once()
        print(f"corpus_sentinel: {n} change(s) processed", flush=True)
        return 0

    sentinel.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
