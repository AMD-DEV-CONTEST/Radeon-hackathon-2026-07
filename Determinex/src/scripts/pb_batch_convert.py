#!/usr/bin/env python3
"""Batch-convert every rewrite-native ProgramBench tool whose upstream
source is available, then pack each as a candidate.

Reads:
  logs/programbench_factory/LANGUAGE_AUDIT.json
  T:/determinex-programbench/_extracted_tests/<slug>/<branch>/

For each tool with action in (rewrite-native, scaffold-stub) AND
upstream source present:
  1. Run pb_convert_to_native.py
  2. Run pb_pack_candidate.py
  3. Record outcome

Outputs:
  logs/programbench_factory/BATCH_CONVERT_REPORT.json
  console summary
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = Path("T:/determinex-programbench/_extracted_tests")
STAGING = ROOT / ".determinex_staging"
AUDIT = ROOT / "logs" / "programbench_factory" / "LANGUAGE_AUDIT.json"
REPORT = ROOT / "logs" / "programbench_factory" / "BATCH_CONVERT_REPORT.json"


def has_upstream_source(slug: str) -> bool:
    d = UPSTREAM / slug
    if not d.is_dir():
        return False
    for branch in d.iterdir():
        if not branch.is_dir():
            continue
        if (branch / "go.mod").is_file() or (branch / "Cargo.toml").is_file():
            return True
        if list(branch.glob("*.c")) or list(branch.glob("*.cpp")):
            return True
    return False


def run(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300
        )
        return p.returncode, (p.stdout + p.stderr)[-500:]
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"
    except Exception as e:
        return 1, str(e)


def main() -> int:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    targets = []
    for r in audit:
        if r["action"] in ("rewrite-native", "scaffold-stub"):
            if has_upstream_source(r["slug"]):
                targets.append(r)
    targets.sort(key=lambda r: -r["score"])

    py = sys.executable
    results = []
    for r in tqdm(targets, desc="Converting + packing", unit="tool"):
        slug = r["slug"]
        # Already-converted tools have no main.py and have compile.sh referencing
        # build commands. Skip them if conversion would be a no-op (we already did it).
        # Use convert script - it's idempotent.
        rc1, out1 = run([py, str(ROOT / "scripts" / "pb_convert_to_native.py"), slug])
        if rc1 != 0:
            results.append({"slug": slug, "stage": "convert", "rc": rc1, "tail": out1})
            tqdm.write(f"  {slug}: CONVERT FAIL ({rc1})")
            continue
        tool_short = slug.replace("__", "_").split(".")[0]
        rundir = STAGING / f"pb_{tool_short}_native_v1"
        # Wipe stale
        if rundir.exists():
            import shutil

            shutil.rmtree(rundir, ignore_errors=True)
        rc2, out2 = run(
            [py, str(ROOT / "scripts" / "pb_pack_candidate.py"), slug, "--run-root", str(rundir)]
        )
        if rc2 != 0:
            results.append({"slug": slug, "stage": "pack", "rc": rc2, "tail": out2})
            tqdm.write(f"  {slug}: PACK FAIL ({rc2})")
            continue
        # Verify tar has reasonable count
        tar = rundir / slug / "submission.tar.gz"
        if tar.is_file():
            try:
                import tarfile as tf

                with tf.open(tar) as tarobj:
                    n_files = sum(1 for _ in tarobj)
                results.append(
                    {"slug": slug, "stage": "ok", "files": n_files, "rundir": str(rundir)}
                )
            except Exception as e:
                results.append({"slug": slug, "stage": "tar_inspect_fail", "rc": 1, "tail": str(e)})
        else:
            results.append({"slug": slug, "stage": "tar_missing", "rc": 1})

    REPORT.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    by_stage: dict[str, int] = {}
    for r in results:
        by_stage[r["stage"]] = by_stage.get(r["stage"], 0) + 1
    print()
    print("== batch convert results ==")
    for k, v in sorted(by_stage.items(), key=lambda x: -x[1]):
        print(f"  {k:20s} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
