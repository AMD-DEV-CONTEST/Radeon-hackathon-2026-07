#!/usr/bin/env python3
"""sprint4_factory_validation.py — run the family factory on 10 untouched tools.

For each picked instance:
  1. Classify (via programbench_classify_family.py)
  2. Generate scaffold (via corpus/programbench/families/wave1/<family>/scaffold_generator.py)
  3. Pack submission.tar.gz
  4. Defer eval to the chain runner (serial under resource guard)

Success metric (from user):
  - 10 generated, 10 packed
  - 5 evaluated (defer to chain)
  - avg +3pp lift over base
  - < 3 minutes scaffold time per tool

Outputs:
  - logs/mass_run_v2/sprint4_factory_validation.json — per-tool timing + paths
  - T:/determinex-programbench/determinex_pb_factory_<tool>_v1/ per tool
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus" / "programbench" / "families" / "wave1"
PBROOT = Path("T:/determinex-programbench")

# The 10 picks (user-curated, avoid known tar pits)
TARGETS = [
    {"instance": "dalance__amber.69a0f52", "family": "search_grep", "rank": 1},
    {"instance": "pls-rs__pls.4e1ae50", "family": "shell_coreutils", "rank": 2},
    {"instance": "ksxgithub__parallel-disk-usage.96978ed", "family": "shell_coreutils", "rank": 3},
    {"instance": "pier-cli__pier.5e1bde9", "family": "rust_cli", "rank": 4},
    {"instance": "ecumene__rust-sloth.051c559", "family": "rust_cli", "rank": 5},
    {"instance": "miserlou__loop.209927c", "family": "shell_coreutils", "rank": 6},
    {"instance": "clog-tool__clog-cli.7066cba", "family": "git_wrappers", "rank": 7},
    {"instance": "bensadeh__tailspin.6278437", "family": "formatters", "rank": 8},
    {"instance": "canop__rhit.ae90bcb", "family": "shell_coreutils", "rank": 9},
    {"instance": "agourlay__zip-password-finder.704700d", "family": "rust_cli", "rank": 10},
]


def _eval_json_path(instance: str) -> Path:
    return PBROOT / "mass_run_v2_base" / instance / f"{instance}.eval.json"


def _factory_dir(instance: str) -> Path:
    return PBROOT / f"determinex_pb_factory_{instance}_v1"


def generate_one(target: dict) -> dict:
    """Run the family generator + pack. Returns timing/path record."""
    instance = target["instance"]
    family = target["family"]
    gen = CORPUS / family / "scaffold_generator.py"
    if not gen.is_file():
        return {
            "instance": instance,
            "family": family,
            "status": "FAMILY_GEN_MISSING",
            "gen_path": str(gen),
        }

    eval_json = _eval_json_path(instance)
    out_root = _factory_dir(instance)
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(gen),
        "--instance",
        instance,
        "--out",
        str(out_root),
        "--pack",
    ]
    if eval_json.is_file():
        cmd += ["--probe-from", str(eval_json)]

    t0 = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        return {"instance": instance, "family": family, "status": "GEN_TIMEOUT", "elapsed_s": 180.0}
    elapsed = time.time() - t0

    inst_dir = out_root / instance
    main_py = inst_dir / "source" / "main.py"
    submission = inst_dir / "submission.tar.gz"

    record = {
        "instance": instance,
        "family": family,
        "rank": target["rank"],
        "status": "OK" if (rc == 0 and main_py.is_file() and submission.is_file()) else "GEN_FAIL",
        "rc": rc,
        "elapsed_s": round(elapsed, 2),
        "main_py": str(main_py),
        "submission": str(submission),
        "submission_bytes": submission.stat().st_size if submission.is_file() else 0,
        "stdout_tail": (proc.stdout or "")[-300:] if rc != 0 else "",
        "stderr_tail": (proc.stderr or "")[-300:] if rc != 0 else "",
    }
    return record


def base_score(instance: str) -> float | None:
    """Return base eval percent or None if missing."""
    ej = _eval_json_path(instance)
    if not ej.is_file():
        return None
    try:
        d = json.loads(ej.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    tr = d.get("test_results", []) or []
    if not tr:
        return None
    p = sum(1 for t in tr if t.get("status") == "passed")
    return round(100.0 * p / len(tr), 2)


def main() -> int:
    print(f"Sprint 4 factory validation — generating {len(TARGETS)} scaffolds")
    print(f"Generators root: {CORPUS}")
    print(f"Output root:     {PBROOT}")
    print()

    records: list[dict] = []
    total_t0 = time.time()
    for t in TARGETS:
        bscore = base_score(t["instance"])
        rec = generate_one(t)
        rec["base_score"] = bscore
        records.append(rec)
        flag = "✓" if rec.get("status") == "OK" else "✗"
        print(
            f"  {flag} #{t['rank']:>2} {t['instance']:<50} family={t['family']:<16} "
            f"{rec.get('elapsed_s', '?'):>5}s  base={bscore if bscore is not None else '?'}%  status={rec.get('status')}"
        )

    total = time.time() - total_t0
    n_ok = sum(1 for r in records if r.get("status") == "OK")
    avg_gen_time = sum(r.get("elapsed_s", 0) for r in records if r.get("status") == "OK") / max(
        n_ok, 1
    )

    print()
    print("=== summary ===")
    print(f"  generated OK:    {n_ok}/{len(TARGETS)}")
    print(f"  total wall time: {round(total, 1)}s")
    print(f"  avg per-tool gen: {round(avg_gen_time, 2)}s")
    print("  factory dirs:    T:/determinex-programbench/determinex_pb_factory_*_v1")

    # Persist
    out_log = ROOT / "logs" / "mass_run_v2" / "sprint4_factory_validation.json"
    out_log.parent.mkdir(parents=True, exist_ok=True)
    out_log.write_text(
        json.dumps(
            {
                "targets": TARGETS,
                "records": records,
                "summary": {
                    "n_ok": n_ok,
                    "n_total": len(TARGETS),
                    "total_wall_s": round(total, 1),
                    "avg_gen_s_per_tool_ok": round(avg_gen_time, 2),
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"  log:             {out_log}")

    return 0 if n_ok == len(TARGETS) else 1


if __name__ == "__main__":
    sys.exit(main())
