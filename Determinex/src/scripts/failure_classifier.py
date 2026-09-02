"""scripts/failure_classifier.py — continuous failure-family classifier.

Watches the ProgramBench eval-JSON dir; on each NEW *.eval.json, parses the test
results, classifies each failure into one of ~20 families, and appends a single
ledger event with the score + family histogram.

Idempotent — already-classified files are detected by artifact path in the
ledger and skipped.

Modes:
    --once         scan once, classify all unseen files, exit (use after a
                   heartbeat batch lands; cheap, ~50ms per file).
    --watch        poll every --interval seconds. Use as a background service.
                   Exits when the watch dir has not changed for --quiet-secs.

Families (Tier 1 — appears in 130+ of 157 residual ProgramBench repos):
    rc_2_unknown_option, rc_2_missing_arg, help_text_mismatch, version_format,
    stdin_handling, empty_input, invalid_value, file_not_found, multiple_inputs,
    no_color_negation

Tier 2 (60-110 repos):
    output_flag, config_file, json_io, format_flag, list_subcommand,
    filter_flag, check_mode, export_flag, hash_executable_fail

Unmatched failures go to the `other` bucket — the advisor uses the size of
`other` to estimate per-tool tail work.

The regex set is centralized here. Both run_ledger.py and any future consumer
(monitor, advisor, frontend) call `classify_eval_json()` from this module so
the family taxonomy is single-source.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Re-use the ledger writer + central taxonomy
sys.path.insert(0, str(Path(__file__).resolve().parent))
# Family taxonomy lives in determinex_pb_taxonomy. Re-exported here for
# backwards-compatibility with callers that imported these symbols from
# scripts/failure_classifier.py before the dedup. Marked F401 because the
# names are part of this module's public API even though this file doesn't
# use them internally any more.
from determinex_pb_taxonomy import (  # type: ignore[import-not-found]  # noqa: F401
    FAMILY_PATTERNS,
    classify_one,
    classify_test_results,
)
from run_ledger import (  # type: ignore[import-not-found]
    LedgerEvent,
    _existing_eval_artifacts,
    append_event,
)

__all__ = [
    "FAMILY_PATTERNS",
    "classify_one",
    "classify_test_results",
    "classify_eval_json",
    "scan_once",
    "watch",
]


def classify_eval_json(path: Path, run_id: str) -> LedgerEvent | None:
    """Parse one eval JSON and return a ledger event. None if the file is broken."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    results = d.get("test_results", [])
    passed = sum(1 for r in results if r.get("status") == "passed")
    failed = sum(1 for r in results if r.get("status") == "failure")
    skipped = sum(1 for r in results if r.get("status") == "skipped")
    total = passed + failed
    score = round(100 * passed / total, 1) if total else 0.0
    families = classify_test_results(results)

    task_id = path.stem.replace(".eval", "")
    mtime = path.stat().st_mtime
    ts = datetime.fromtimestamp(mtime, tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    return LedgerEvent(
        run_id=run_id,
        task_id=task_id,
        phase="eval",
        status="completed",
        timestamp=ts,
        score=score,
        failures=dict(families) if families else None,
        artifact=str(path).replace("\\", "/"),
        extra={"passed": passed, "failed": failed, "skipped": skipped, "total": total},
    )


# ---------------------------------------------------------------------------
# Scan / watch loop
# ---------------------------------------------------------------------------


def scan_once(eval_root: Path, run_id: str) -> dict:
    """Find every *.eval.json under eval_root not already in the ledger; classify + emit."""
    if not eval_root.exists():
        return {
            "scanned": 0,
            "added": 0,
            "skipped": 0,
            "errors": 0,
            "reason": f"missing dir: {eval_root}",
        }

    seen = _existing_eval_artifacts(run_id)
    added = skipped = errors = 0
    for ej in sorted(eval_root.glob("*/*.eval.json")):
        artifact = str(ej).replace("\\", "/")
        if artifact in seen:
            skipped += 1
            continue
        ev = classify_eval_json(ej, run_id=run_id)
        if ev is None:
            errors += 1
            continue
        append_event(ev)
        added += 1
    return {
        "scanned": added + skipped + errors,
        "added": added,
        "skipped": skipped,
        "errors": errors,
    }


def watch(eval_root: Path, run_id: str, interval: float, quiet_secs: float) -> dict:
    """Poll-and-classify loop. Exits when no new files have arrived for quiet_secs."""
    print(
        f"[classifier] watching {eval_root} every {interval}s; quiet exit after {quiet_secs}s",
        flush=True,
    )
    total = {"added": 0, "errors": 0}
    last_change = time.time()
    while True:
        r = scan_once(eval_root, run_id)
        if r["added"] > 0:
            print(
                f"[classifier] {datetime.now().strftime('%H:%M:%S')} — +{r['added']} new "
                f"(total added this session: {total['added'] + r['added']})",
                flush=True,
            )
            last_change = time.time()
        total["added"] += r["added"]
        total["errors"] += r["errors"]
        if time.time() - last_change > quiet_secs:
            print(
                f"[classifier] quiet for {quiet_secs}s — exiting. session added={total['added']}",
                flush=True,
            )
            return total
        time.sleep(interval)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli():
    ap = argparse.ArgumentParser(description="Determinex continuous failure-family classifier")
    ap.add_argument(
        "--eval-root", type=Path, default=Path("T:/determinex-programbench/mass_run_v2_base")
    )
    ap.add_argument("--run-id", default="mass_run_v2_base")
    g = ap.add_mutually_exclusive_group(required=False)
    g.add_argument("--once", action="store_true", help="scan once and exit (default)")
    g.add_argument("--watch", action="store_true", help="poll continuously")
    ap.add_argument("--interval", type=float, default=20.0, help="watch poll interval (s)")
    ap.add_argument(
        "--quiet-secs",
        type=float,
        default=600.0,
        help="exit after this many seconds with no new files (watch only)",
    )
    args = ap.parse_args()

    if args.watch:
        r = watch(args.eval_root, args.run_id, args.interval, args.quiet_secs)
    else:
        r = scan_once(args.eval_root, args.run_id)
    print(json.dumps({"mode": "watch" if args.watch else "once", **r}, indent=2))


if __name__ == "__main__":
    _cli()
