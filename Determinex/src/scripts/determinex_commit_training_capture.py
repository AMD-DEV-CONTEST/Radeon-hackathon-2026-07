#!/usr/bin/env python3
"""scripts/determinex_commit_training_capture.py — capture every commit as a
potential training example, not just Hive DAG build sessions.

Gap found 2026-07-20: scripts/hive/budget.py's queue_for_training() is real
and wired into the general compile-gate loop (not just SWE-bench), but it
only fires for steps executed through determinex_hive.py's DAG pipeline
(StepRecord.compiler_error_hashes, .escalations, etc. -- Hive-specific
fields). logs/retrain_queue.jsonl had been dormant since 2026-04-25 --
almost 3 months -- and structurally could never capture work done outside
that one pipeline (the OSS-integration fixes, the frontend hydration fix,
the hackathon kernel work, the corpus fixes all this session included --
all real, all compiler/test-verified, none of it Hive-DAG-shaped, none of
it captured anywhere).

This captures at COMMIT granularity instead of Hive-step granularity: every
commit's diff + message + a quality tag inferred from the verification
evidence the commit message itself states. This project's own commit
convention already documents test results in the body ("4540/4540 passing",
"0 violations", "N tests ... all pass") -- classify_quality() below reads
that instead of re-running the full suite synchronously in a hook (which
would make every commit slow and block on Docker/Ollama availability).

Usage:
    python scripts/determinex_commit_training_capture.py capture [--sha SHA]
    python scripts/determinex_commit_training_capture.py stats

Writes to logs/commit_training_corpus.jsonl -- deliberately a SEPARATE file
from logs/retrain_queue.jsonl (different schema/granularity; the Hive
step-level queue's consumers expect its exact shape, this must not corrupt
that contract).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "logs" / "commit_training_corpus.jsonl"

# Heuristics over the commit message body -- matches this project's own
# established convention of stating verification evidence in commit
# messages (test counts, governance-gate results), not a general-purpose
# NLP classifier.
_PASS_EVIDENCE_RE = re.compile(
    # "4540/4540 passing", "85/85 vitest unit tests still pass" -- real
    # prose puts descriptive words between the count and the verb, not
    # just whitespace, so allow up to ~6 words in between.
    r"\b(\d+)\s*/\s*\1\b(?:\s+\w+){0,6}?\s+(?:passing|passed|pass)\b"
    r"|\ball\s+\d+\s+tests?\s+pass"  # "all 20 tests pass"
    # "1165 passed, 0 failed" / "0 failed, 1165 passed" -- comma-separated
    # pass/fail counts where the fail side is exactly 0.
    r"|\b\d+\s+passed,\s*0\s+failed\b"
    r"|\b0\s+failed,\s*\d+\s+passed\b"
    r"|\b0\s+violations?\b"  # "0 violations"
    r"|\bguard\s+passed\b"  # "GUARD PASSED"
    r"|\ball\s+invariants\s+satisfied\b",  # "All invariants satisfied"
    re.IGNORECASE,
)
_FAIL_EVIDENCE_RE = re.compile(
    r"\bwip\b|\bbroken\b|\bdo\s+not\s+merge\b|\bfixup!|\bsquash!",
    re.IGNORECASE,
)


@retry(
    retry=retry_if_exception_type(subprocess.CalledProcessError),
    stop=stop_after_attempt(3),
    wait=wait_fixed(0.5),
    reraise=True,
)
def _run(cmd: list[str]) -> str:
    # A real 2394-commit backfill hit a git invocation that failed with exit
    # 128 mid-run on a machine that had been running many concurrent
    # processes all session (WSL compiles, uv syncs, embeddings rebuilds);
    # the exact same command re-run standalone afterward succeeded
    # immediately -- transient resource contention, not a malformed
    # argument (that theory was chased and ruled out: the "malformed" sha
    # was a miscount on my own part, a valid 40-char sha the whole time).
    # Retry past a transient failure rather than let one abort a
    # multi-thousand-commit run this far in.
    return subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout


def _safe_diff(sha: str) -> tuple[str, bool]:
    """git show can hit a genuine, non-transient, non-retryable failure on
    a specific historical commit's content -- found live: a commit touching
    a .doc file whose textconv/diff filter fails with "unsupported
    filetype" partway through an otherwise-successful 17MB diff (git
    processes most of it, then errors fatally near the end -- a shell
    pipeline truncating output with `| head` can hide this entirely by
    killing git before it reaches the bad file, which is exactly how this
    first looked like a transient/flaky failure and wasn't). Returns
    (diff_text, diff_capture_failed) -- the commit still gets captured
    (message + file stat are still real, useful signal) rather than being
    dropped outright over one unreadable file's diff."""
    try:
        return _run(["git", "show", "--format=", sha]), False
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        print(
            f"  {sha[:12]}: diff capture failed ({stderr[:200]}) -- "
            f"keeping message+stat, diff omitted",
            file=sys.stderr,
        )
        return "", True


def classify_quality(message: str) -> str:
    """training_ready: message states real pass/verification evidence.
    unverified: no such evidence found -- captured anyway (still real code,
    just not self-documented as tested) but a fine-tune curation pass
    should weight/filter these differently, not silently treat them the
    same as training_ready.
    excluded: message signals the commit itself is known-incomplete/WIP."""
    if _FAIL_EVIDENCE_RE.search(message):
        return "excluded"
    if _PASS_EVIDENCE_RE.search(message):
        return "training_ready"
    return "unverified"


def capture_commit(sha: str = "HEAD") -> dict:
    full_sha = _run(["git", "rev-parse", sha]).strip()
    message = _run(["git", "log", "-1", "--format=%B", full_sha])
    author_date = _run(["git", "log", "-1", "--format=%aI", full_sha]).strip()
    files = _run(["git", "show", "--stat", "--format=", full_sha]).strip()
    diff, diff_failed = _safe_diff(full_sha)

    quality = classify_quality(message)
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "sha": full_sha,
        "author_date": author_date,
        "message": message.strip(),
        "files_changed_summary": files,
        "diff": diff[:200_000],  # cap a single pathological commit, not the norm
        "diff_truncated": len(diff) > 200_000,
        "diff_capture_failed": diff_failed,
        "quality": quality,
        "source": "commit_capture",
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return {"sha": full_sha[:12], "quality": quality, "diff_bytes": len(diff)}


def _already_captured_shas() -> set[str]:
    """Read existing entries once (not per-commit) so a resumed/re-run
    backfill never re-captures the same sha -- same resumability discipline
    as determinex_pb_absorb's absorbed_sources tracking."""
    if not OUT_PATH.is_file():
        return set()
    seen: set[str] = set()
    with OUT_PATH.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            sha = row.get("sha")
            if sha:
                seen.add(sha)
    return seen


_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def backfill_all(ref: str = "HEAD", progress_every: int = 100) -> dict:
    """Capture every commit reachable from `ref` that isn't already in
    OUT_PATH. Runs in ONE process (unlike calling capture_commit() via the
    CLI in a shell loop, which pays Python-interpreter-startup cost per
    commit on top of git's own subprocess cost).

    The sha LIST comes from one unambiguous call (git log --format=%H, one
    40-hex-char line per commit -- no delimiter parsing needed at all).
    Per-commit date/message/stat/diff are then fetched with one call each.
    An earlier version tried to fetch sha+date+message for the WHOLE
    history in a single NUL-delimited git log call to save subprocess
    calls; that broke live on a real 2394-commit backfill (a stray
    character from one record's boundary leaked onto the next record's
    sha -- '2c47e4acd290a88b03069ccb192d105413242de2', 41 hex chars, one
    too many) after ~1200 commits had already processed cleanly, meaning
    the corruption was a rare boundary case, not a systematic one -- exactly
    the kind of bug that's dangerous precisely because it mostly works.
    Slower but provably correct beats fast but silently-sometimes-wrong for
    a backfill that's supposed to be the trustworthy historical record."""
    already = _already_captured_shas()

    sha_list_raw = _run(["git", "log", ref, "--format=%H"])
    all_shas = [s.strip() for s in sha_list_raw.splitlines() if s.strip()]

    added = skipped = malformed = errored = 0
    quality_counts: dict[str, int] = {}
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with OUT_PATH.open("a", encoding="utf-8") as out_f:
        for i, sha in enumerate(all_shas, start=1):
            if not _SHA_RE.match(sha):
                malformed += 1
                print(
                    f"  backfill: skipping malformed sha at position {i}: {sha!r}", file=sys.stderr
                )
                continue
            if sha in already:
                skipped += 1
                continue

            try:
                author_date = _run(["git", "log", "-1", "--format=%aI", sha]).strip()
                message = _run(["git", "log", "-1", "--format=%B", sha])
                files = _run(["git", "show", "--stat", "--format=", sha]).strip()
            except subprocess.CalledProcessError as e:
                # metadata/stat calls failing after 3 retries is a genuine
                # anomaly worth skipping over -- unlike the diff itself
                # (see _safe_diff), there's no known legitimate reason for
                # these specific lightweight calls to fail deterministically.
                errored += 1
                print(
                    f"  backfill: {sha[:12]} failed after retries, skipping: {e}", file=sys.stderr
                )
                continue
            diff, diff_failed = _safe_diff(sha)

            quality = classify_quality(message)
            quality_counts[quality] = quality_counts.get(quality, 0) + 1

            entry = {
                "timestamp": datetime.now(UTC).isoformat(),
                "sha": sha,
                "author_date": author_date,
                "message": message.strip(),
                "files_changed_summary": files,
                "diff": diff[:200_000],
                "diff_truncated": len(diff) > 200_000,
                "diff_capture_failed": diff_failed,
                "quality": quality,
                "source": "commit_capture_backfill",
            }
            out_f.write(json.dumps(entry) + "\n")
            out_f.flush()
            already.add(sha)
            added += 1

            if progress_every and added % progress_every == 0:
                print(
                    f"  backfill: {added} added, {skipped} already-captured "
                    f"({i}/{len(all_shas)} scanned)",
                    file=sys.stderr,
                )

    return {
        "total_in_history": len(all_shas),
        "added": added,
        "already_captured_skipped": skipped,
        "malformed_sha_skipped": malformed,
        "errored_after_retries": errored,
        "by_quality": quality_counts,
    }


def stats() -> dict:
    if not OUT_PATH.is_file():
        return {"exists": False}
    counts: dict[str, int] = {}
    total = 0
    with OUT_PATH.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            q = row.get("quality", "?")
            counts[q] = counts.get(q, 0) + 1
    return {"exists": True, "total": total, "by_quality": counts}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    cap = sub.add_parser("capture")
    cap.add_argument("--sha", default="HEAD")
    back = sub.add_parser("backfill")
    back.add_argument("--ref", default="HEAD")
    sub.add_parser("stats")
    args = ap.parse_args()

    if args.cmd == "capture":
        result = capture_commit(args.sha)
        print(json.dumps(result, indent=1))
    elif args.cmd == "backfill":
        result = backfill_all(args.ref)
        print(json.dumps(result, indent=1))
    elif args.cmd == "stats":
        print(json.dumps(stats(), indent=1))
    else:
        ap.print_help()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
