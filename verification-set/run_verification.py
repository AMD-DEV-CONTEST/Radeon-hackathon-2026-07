#!/usr/bin/env python3
"""Run the V1 verification set (verification_seeds.json) through eval_policy.py.

Each episode is invoked as:
    eval_policy.py --episodes 1 --seed <seed> --picks <pick> --video-dir <out>/<pick>_s<seed>
Results are aggregated into <out>/verification_results.json and printed.

Reproducibility: every seed is fixed in verification_seeds.json and EnvRandomizer
seeds the whole domain randomization from it, so re-running reproduces the same
episode states (see README.md).

Usage:
    python run_verification.py --jobs 3
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run_one(ep: dict, eval_script: Path, checkpoint: str, out_root: Path) -> dict:
    tag = f"{ep['pick']}_s{ep['seed']}"
    vdir = out_root / tag
    cmd = [
        sys.executable, "-u", str(eval_script),
        "--checkpoint", checkpoint,
        "--episodes", "1",
        "--seed", str(ep["seed"]),
        "--picks", ep["pick"],
        "--video-dir", str(vdir),
    ]
    print(f"[verify] running {tag} -> {vdir}", flush=True)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    summ = vdir / "summary.json"
    if proc.returncode != 0 or not summ.exists():
        tail = ((proc.stdout or "") + (proc.stderr or ""))[-2000:]
        print(f"[verify] {tag} ERROR (see verification_results.json)", flush=True)
        return {**ep, "rerun_success": None, "error": tail}
    got = json.loads(summ.read_text())["results"][0]
    mark = "OK" if got["success"] else "FAIL"
    print(f"[verify] {tag} {mark} frames={got['frames']}", flush=True)
    return {**ep, "rerun_success": got["success"], "rerun_frames": got["frames"]}


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the V1 verification set (25 fixed-seed episodes).")
    ap.add_argument("--eval-script", default=str(HERE.parent / "eval_policy.py"))
    ap.add_argument(
        "--checkpoint",
        default="/persistent/track3-robot/models/smolvla_industrial_sort_v2_ckpt20k",
    )
    ap.add_argument("--out-dir", default=str(HERE / "verification_videos"))
    ap.add_argument(
        "--jobs",
        type=int,
        default=3,
        help="parallel episode workers (3 is safe on the W7900)",
    )
    args = ap.parse_args()

    doc = json.loads((HERE / "verification_seeds.json").read_text())
    episodes = doc["episodes"]
    out_root = Path(args.out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(
            pool.map(
                lambda e: run_one(e, Path(args.eval_script), args.checkpoint, out_root),
                episodes,
            )
        )

    (out_root / "verification_results.json").write_text(json.dumps(results, indent=2))

    ran = [r for r in results if r.get("rerun_success") is not None]
    n_ok = sum(1 for r in ran if r["rerun_success"])
    n_label = sum(1 for r in ran if r.get("expected_success") is not None)
    n_labelled_ok = sum(1 for r in ran if r.get("expected_success") is not None and r["rerun_success"])
    n_new_ok = sum(1 for r in ran if r.get("expected_success") is None and r["rerun_success"])
    n_new = len(ran) - n_label
    print(f"\n[verify] rerun score: {n_ok}/{len(ran)} overall "
          f"(labelled curated: {n_labelled_ok}/{n_label}; "
          f"new random seeds: {n_new_ok}/{n_new})")
    if len(ran) < len(results):
        print(f"[verify] WARNING: {len(results) - len(ran)} episode(s) errored, "
              f"see verification_results.json")

    flipped = [
        r for r in ran
        if r.get("expected_success") is not None and r["rerun_success"] != r["expected_success"]
    ]
    if flipped:
        print("[verify] episodes that flipped vs logged runs "
              "(normal closed-loop noise):")
        for r in flipped:
            print(f"  - {r['pick']} s{r['seed']}: "
                  f"expected {r['expected_success']}, got {r['rerun_success']}")


if __name__ == "__main__":
    main()
