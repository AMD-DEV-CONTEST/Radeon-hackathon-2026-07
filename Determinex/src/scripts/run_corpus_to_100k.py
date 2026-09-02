#!/usr/bin/env python3
"""
DETERMINEX CORPUS RUNNER - drives gen_real_scale_v4.py in multiple passes
and tracks cumulative unique example count across all real_scale files.

Usage: python run_corpus_to_100k.py [start_pass] [end_pass]
  Defaults: start=0, end=120
"""

import glob
import hashlib
import json
import os
import os as _os
import subprocess
import sys
import time
from pathlib import Path as _P

SCRIPT = str(
    _P(_os.environ.get("DETERMINEX_ROOT", str(_P(__file__).parent.parent)))
    / "scripts"
    / "gen_real_scale_v4.py"
)
REAL_DIR = str(
    _P(_os.environ.get("DETERMINEX_MODELS_DIR", str(_P.home() / "determinex-models")))
    / "corpus"
    / "real_scale"
)
TARGET = 100_000

start_pass = int(sys.argv[1]) if len(sys.argv) > 1 else 0
end_pass = int(sys.argv[2]) if len(sys.argv) > 2 else 120


def count_unique_across_all():
    seen = set()
    total = 0
    for fpath in glob.glob(os.path.join(REAL_DIR, "*.jsonl")):
        with open(fpath, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    key = hashlib.md5(
                        (obj.get("instruction", "") + obj.get("output", ""))[:600].encode()
                    ).hexdigest()
                    if key not in seen:
                        seen.add(key)
                        total += 1
                except Exception:
                    pass
    return total


print("=" * 60)
print("DETERMINEX CORPUS RUNNER")
print("Script : " + SCRIPT)
print("Target : " + str(TARGET))
print("Passes : " + str(start_pass) + " -> " + str(end_pass))
print("=" * 60)

initial = count_unique_across_all()
print("\nStarting unique count: " + str(initial) + "\n")

for pass_num in range(start_pass, end_pass + 1):
    t0 = time.time()
    result = subprocess.run(["python", SCRIPT, str(pass_num)], capture_output=True)
    elapsed = time.time() - t0
    stdout = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
    stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""

    if result.returncode != 0:
        print("[PASS " + str(pass_num) + "] FAILED (" + str(round(elapsed, 1)) + "s)")
        print(stderr[-500:])
        continue

    lines = [l for l in stdout.splitlines() if l.strip()]
    summary = next((l for l in lines if "unique examples" in l), "")
    current = count_unique_across_all()
    pct = round(current / TARGET * 100, 1)

    pad_pass = str(pass_num).zfill(3)
    pad_sum = summary.strip()[:40].ljust(40)
    print(
        f"[PASS {pad_pass}] {pad_sum} | Total: {current:>7,} / {TARGET:,} ({pct}%) [{elapsed:.1f}s]"
    )

    if current >= TARGET:
        print("\n>>> TARGET REACHED: " + str(current) + " unique examples!")
        break

final = count_unique_across_all()
print("\n" + "=" * 60)
print("FINAL COUNT : " + str(final) + " unique examples")
print("Generated   : " + str(final - initial) + " new this run")
print("Gap to 100k : " + str(max(0, TARGET - final)))
