#!/usr/bin/env python3
"""ProgramBench WAL — write-ahead log of every (attempt → outcome) for future LoRA retrains.

Each WAL record captures the closed-loop training pair:
  - input: prompt sent to model (system + user_msg)
  - output: model's response (compile_sh + files)
  - outcome: compile result + eval score + per-test status
  - delta: vs prior attempt (what changed)

Records are appended as JSONL to logs/wal/<run_name>/<instance_id>.jsonl. Per-record fsync
ensures crash-safety. Format compatible with `determinex_trainer/dsl_finetune.py` for flywheel retrain.

Usage:
    from pb_wal import wal_record
    wal_record(run_name, instance_id, attempt, system_prompt, user_msg, response, outcome)
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

DETERMINEX_ROOT = Path(os.environ.get("DETERMINEX_ROOT", Path(__file__).resolve().parents[1]))
WAL_ROOT = DETERMINEX_ROOT / "logs" / "wal"


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()[:16]


def wal_record(
    run_name: str,
    instance_id: str,
    attempt: int,
    system_prompt: str,
    user_msg: str,
    response: str,
    outcome: dict,
) -> Path:
    """Append one WAL record. `outcome` should contain at minimum:
    backend, model, compile_ok, eval_score, eval_passed, eval_total,
    wins (test names), regressions (test names), failure_categories.
    """
    rec = {
        "ts": time.time(),
        "run_name": run_name,
        "instance_id": instance_id,
        "attempt": attempt,
        "prompt_sha": _sha(system_prompt + "\n---\n" + user_msg),
        "response_sha": _sha(response),
        # Truncate inputs/outputs at sensible sizes — full payload too big for daily WAL
        "system_prompt": system_prompt[:8000],
        "user_msg": user_msg[:30000],
        "response": response[:20000],
        "outcome": outcome,
    }
    out_dir = WAL_ROOT / run_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{instance_id}.jsonl"
    line = json.dumps(rec, default=str) + "\n"
    # Atomic append + fsync
    fd = os.open(str(out_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line.encode("utf-8", errors="replace"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return out_path


def wal_summary(run_name: str) -> str:
    """Quick stats over a run's WAL."""
    d = WAL_ROOT / run_name
    if not d.is_dir():
        return f"(no WAL at {d})"
    files = list(d.glob("*.jsonl"))
    n_records = 0
    n_locks = 0
    n_compile = 0
    by_score: dict[int, int] = {}
    for f in files:
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            n_records += 1
            o = r.get("outcome", {})
            if o.get("compile_ok"):
                n_compile += 1
            score = o.get("eval_score", -1)
            if score >= 100:
                n_locks += 1
            by_score[score // 10 * 10] = by_score.get(score // 10 * 10, 0) + 1
    return (
        f"WAL {run_name}: {len(files)} tasks, {n_records} attempts, "
        f"{n_compile} compiled, {n_locks} locked. Score histogram: "
        + ", ".join(f"{k}+={v}" for k, v in sorted(by_score.items()))
    )


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", help="Show WAL summary for a run")
    args = ap.parse_args()
    if args.summary:
        print(wal_summary(args.summary))
    else:
        ap.print_help()
