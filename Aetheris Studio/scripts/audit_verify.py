#!/usr/bin/env python3
"""Standalone Flight Recorder chain verifier.

Deliberately dependency-free (stdlib only: json/hashlib/argparse/sys) and
does NOT import anything under core/ -- a client who received a
session's .jsonl log (see UC-01: "auditing a session for an NDA client")
can verify it with nothing installed except Python itself, no Aetheris
checkout required.

This duplicates the ~30-line chain-walk in
core/audit/flight_recorder.py::verify_chain() on purpose, for that same
standalone-portability reason. If the entry shape in flight_recorder.py
ever changes, update both by hand -- they're intentionally not sharing
code.

Usage:
    python audit_verify.py <path-to-session.jsonl>
"""

import argparse
import hashlib
import json
import sys

GENESIS_HASH = hashlib.sha256(b"aetheris-flight-recorder-genesis-v1").hexdigest()


def _canonical_json(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def verify(path: str):
    """Returns (ok: bool, entry_count: int, first_bad_seq: int | None, errors: list[str])."""
    head = GENESIS_HASH
    entry_count = 0
    errors = []

    try:
        f = open(path, "r", encoding="utf-8")
    except OSError as e:
        return False, 0, None, [f"cannot open {path}: {e}"]

    with f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as e:
                return False, entry_count, None, [f"line {line_num}: invalid JSON ({e})"]

            seq = entry.get("seq")

            if entry.get("prev_hash") != head:
                errors.append(f"seq {seq}: prev_hash does not match the previous entry's hash -- chain broken")
                return False, entry_count, seq, errors

            claimed_hash = entry.get("hash")
            recomputed = dict(entry)
            recomputed.pop("hash", None)
            real_hash = hashlib.sha256(_canonical_json(recomputed).encode("utf-8")).hexdigest()
            if real_hash != claimed_hash:
                errors.append(f"seq {seq}: stored hash does not match recomputed hash -- entry was tampered with")
                return False, entry_count, seq, errors

            head = claimed_hash
            entry_count += 1

    return True, entry_count, None, []


def main():
    parser = argparse.ArgumentParser(description="Verify a Flight Recorder session log's hash chain.")
    parser.add_argument("log_path", help="Path to a <session_id>.jsonl file")
    args = parser.parse_args()

    ok, count, first_bad_seq, errors = verify(args.log_path)

    if ok:
        print(f"OK -- {count} entries verified, chain intact.")
        sys.exit(0)
    else:
        print(f"FAILED at entry seq={first_bad_seq} ({count} entries verified before the failure).")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
