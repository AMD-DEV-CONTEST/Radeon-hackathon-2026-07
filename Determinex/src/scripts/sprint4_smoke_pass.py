#!/usr/bin/env python3
"""sprint4_smoke_pass.py — verify every factory-generated scaffold:
  1. main.py compiles (py_compile)
  2. --help rc=0 and prints something
  3. unknown flag rc=2 (clap convention)

No Docker, just process invocation. Catches broken generators before eval queue.
"""

from __future__ import annotations

import json
import py_compile
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PBROOT = Path("T:/determinex-programbench")


def smoke(instance: str) -> dict:
    root = PBROOT / f"determinex_pb_factory_{instance}_v1" / instance
    main_py = root / "source" / "main.py"
    rec: dict = {"instance": instance, "main_py_exists": main_py.is_file()}
    if not main_py.is_file():
        rec["status"] = "MISSING_MAIN"
        return rec

    # 1. py_compile
    try:
        py_compile.compile(str(main_py), doraise=True)
        rec["compiles"] = True
    except py_compile.PyCompileError as ex:
        rec["compiles"] = False
        rec["compile_error"] = str(ex)[:200]
        rec["status"] = "COMPILE_FAIL"
        return rec

    # 2. --help rc=0 and prints something
    try:
        proc = subprocess.run(
            [sys.executable, str(main_py), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        rec["help_rc"] = proc.returncode
        rec["help_stdout_len"] = len(proc.stdout)
        rec["help_ok"] = proc.returncode == 0 and len(proc.stdout) > 0
    except subprocess.TimeoutExpired:
        rec["help_ok"] = False
        rec["help_rc"] = "TIMEOUT"
        rec["status"] = "HELP_TIMEOUT"
        return rec

    if not rec["help_ok"]:
        rec["status"] = "HELP_FAIL"
        return rec

    # 3. unknown flag rc=2
    try:
        proc = subprocess.run(
            [sys.executable, str(main_py), "--this-flag-definitely-does-not-exist"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        rec["unknown_rc"] = proc.returncode
        rec["unknown_stderr_contains_error"] = (
            "error" in proc.stderr.lower() or "unexpected" in proc.stderr.lower()
        )
        rec["unknown_flag_ok"] = proc.returncode == 2 and rec["unknown_stderr_contains_error"]
    except subprocess.TimeoutExpired:
        rec["unknown_flag_ok"] = False
        rec["unknown_rc"] = "TIMEOUT"

    if not rec["unknown_flag_ok"]:
        rec["status"] = "UNKNOWN_FLAG_FAIL"
        return rec

    rec["status"] = "OK"
    return rec


def main() -> int:
    log_in = ROOT / "logs" / "mass_run_v2" / "sprint4_bulk_generation.json"
    if not log_in.is_file():
        print(f"ERROR: bulk generation log not found at {log_in}")
        print("Run scripts/sprint4_bulk_generate.py first.")
        return 1
    bulk = json.loads(log_in.read_text(encoding="utf-8"))
    generated = [r for r in bulk["records"] if r.get("status") == "OK"]
    print(f"Sprint 4 smoke pass — checking {len(generated)} generated scaffolds")
    print()

    t0 = time.time()
    smokes: list[dict] = []
    counts = {
        "OK": 0,
        "COMPILE_FAIL": 0,
        "HELP_FAIL": 0,
        "HELP_TIMEOUT": 0,
        "UNKNOWN_FLAG_FAIL": 0,
        "MISSING_MAIN": 0,
    }
    for r in generated:
        s = smoke(r["instance"])
        s["family"] = r.get("family")
        s["base_score"] = r.get("base_score")
        smokes.append(s)
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    elapsed = time.time() - t0

    print("=== summary ===")
    print(f"  total smoked:         {len(smokes)}")
    print(f"  total wall time:      {round(elapsed, 1)}s")
    print(f"  avg per-tool:         {round(elapsed / max(len(smokes), 1), 3)}s")
    print()
    for status, n in sorted(counts.items(), key=lambda x: -x[1]):
        if n:
            tag = "✓" if status == "OK" else "✗"
            print(f"  {tag} {status:<22}  {n}")
    print()

    # List failures by class
    for status in (
        "COMPILE_FAIL",
        "HELP_FAIL",
        "HELP_TIMEOUT",
        "UNKNOWN_FLAG_FAIL",
        "MISSING_MAIN",
    ):
        bad = [s for s in smokes if s["status"] == status]
        if not bad:
            continue
        print(f"  --- {status} ({len(bad)}) ---")
        for s in bad[:10]:
            extra = ""
            if status == "HELP_FAIL":
                extra = f"  rc={s.get('help_rc')} stdout_len={s.get('help_stdout_len')}"
            elif status == "UNKNOWN_FLAG_FAIL":
                extra = (
                    f"  rc={s.get('unknown_rc')} has_err={s.get('unknown_stderr_contains_error')}"
                )
            elif status == "COMPILE_FAIL":
                extra = f"  {s.get('compile_error', '')[:80]}"
            print(f"    {s['instance']:<55} {s.get('family', '?'):<16}{extra}")

    out_log = ROOT / "logs" / "mass_run_v2" / "sprint4_smoke_pass.json"
    out_log.write_text(
        json.dumps(
            {
                "records": smokes,
                "counts": counts,
                "total_wall_s": round(elapsed, 1),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n  log: {out_log}")
    return 0 if counts.get("OK", 0) == len(smokes) else 1


if __name__ == "__main__":
    sys.exit(main())
