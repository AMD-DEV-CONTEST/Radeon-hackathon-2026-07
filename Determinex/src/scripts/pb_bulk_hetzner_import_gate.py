#!/usr/bin/env python3
"""Bulk import + gate all completed Hetzner pool factory eval dirs.

For each completed dir on Hetzner that has not been locally gated yet:
1. rsync the eval JSON from Hetzner
2. Find baseline from lock board
3. Gate with --skip-eval (uses Hetzner's eval result)
4. Apply accepted gates (Rule A/B/C)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "logs" / "programbench_lock_board.json"
HETZ_IMPORT_BASE = Path("T:/determinex-programbench")
SSH = Path(r"C:\Windows\System32\OpenSSH\ssh.exe")
SCP = Path(r"C:\Windows\System32\OpenSSH\scp.exe")
SSH_KEY = Path.home() / ".ssh" / "id_citadel"
SSH_HOST = "root@5.78.192.163"
REMOTE_BASE = "/root/citadel-programbench"
PYTHON = Path(sys.executable)


def _ssh(cmd: str, timeout: int = 60) -> str:
    r = subprocess.run(
        [str(SSH), "-o", "StrictHostKeyChecking=no", "-i", str(SSH_KEY), SSH_HOST, cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return r.stdout.strip()


def _scp_dir(remote_path: str, local_path: Path) -> bool:
    """Copy remote dir to local via scp -r."""
    local_path.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [
            str(SCP),
            "-o",
            "StrictHostKeyChecking=no",
            "-i",
            str(SSH_KEY),
            "-r",
            f"{SSH_HOST}:{remote_path}",
            str(local_path) + "/",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    return r.returncode == 0


def load_board() -> dict[str, dict]:
    board = json.loads(BOARD.read_text(encoding="utf-8"))
    return {t["base_slug"]: t for t in board if t.get("base_slug")}


def get_completed_dirs() -> list[tuple[str, str]]:
    """Returns list of (slug, remote_dir) for dirs that have an eval JSON."""
    script = (
        f"for d in {REMOTE_BASE}/determinex_pb_factory_*_v1; do "
        "slug=$(basename $d | sed 's/determinex_pb_factory_//' | sed 's/_v1$//'); "
        "if ls $d/$slug/*.eval.json 2>/dev/null | grep -q .; then echo $slug; fi; "
        "done"
    )
    out = _ssh(script, timeout=120)
    result = []
    for slug in out.strip().split("\n"):
        slug = slug.strip()
        if not slug:
            continue
        remote_dir = f"{REMOTE_BASE}/determinex_pb_factory_{slug}_v1"
        result.append((slug, remote_dir))
    return result


def _check_native(local_slug_dir: Path) -> bool:
    """Return True if compile.sh looks like a native build (not a python wrapper)."""
    compile_sh = local_slug_dir / "source" / "compile.sh"
    if not compile_sh.exists():
        # Also try directly inside the slug dir
        compile_sh = local_slug_dir / "compile.sh"
    if not compile_sh.exists():
        return True  # unknown, don't block
    text = compile_sh.read_text(encoding="utf-8", errors="replace").lower()
    # Red flags for python wrappers
    python_wrapper_patterns = [
        "import subprocess",
        "#!/usr/bin/env python",
        "#!/usr/bin/python",
        "python_wrapper",
        "wrapper.py",
        "shutil.copy",
        "shutil.copyfile",
    ]
    for pat in python_wrapper_patterns:
        if pat in text:
            return False
    return True


def find_baseline(slug: str, board: dict) -> tuple[Path | None, int]:
    base_slug = re.sub(r"\.[a-f0-9]+$", "", slug)
    entry = board.get(base_slug)
    if not entry:
        return None, 0
    best_eval = entry.get("best_eval_path")
    best_passed = entry.get("best_passed") or 0
    if best_eval and Path(best_eval).is_file():
        return Path(best_eval), max(0, int(best_passed) - 1)
    return None, 0


def gate_tool(
    slug: str,
    local_import_dir: Path,
    baseline_eval: Path | None,
    min_baseline: int,
    dry_run: bool,
) -> dict | None:
    gate_out = local_import_dir / "gate_result.json"
    if gate_out.exists():
        try:
            existing = json.loads(gate_out.read_text(encoding="utf-8", errors="replace"))
            # Return cached result (already gated)
            return existing
        except Exception:
            pass

    if baseline_eval is None or not baseline_eval.is_file():
        return None

    cmd = [
        str(PYTHON),
        str(ROOT / "scripts" / "pb_candidate_gate.py"),
        slug,
        str(local_import_dir),
        "--skip-eval",
        "--min-baseline-passed",
        str(min_baseline),
        "--baseline-eval",
        str(baseline_eval),
    ]
    if dry_run:
        print(f"  [DRY] gate cmd (last 6 args): {' '.join(cmd[-6:])}")
        return None

    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    if r.returncode not in (0, 1):
        print(f"  [GATE ERROR rc={r.returncode}] {r.stderr[:200]}")
        return None
    try:
        return json.loads(r.stdout)
    except Exception:
        print(f"  [GATE PARSE ERROR] {r.stdout[:200]}")
        return None


def apply_gate(slug: str, local_import_dir: Path, dry_run: bool) -> int:
    gate_path = local_import_dir / "gate_result.json"
    cmd = [
        str(PYTHON),
        str(ROOT / "scripts" / "pb_apply_gate_decision.py"),
        slug,
        str(gate_path),
        "--run-root",
        str(local_import_dir),
        "--python",
        str(PYTHON),
    ]
    if dry_run:
        print("  [DRY] apply (would write lesson/sidecar/board annotations)")
        return 0
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    return r.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="max tools to process (0=all)")
    ap.add_argument("--only-slug", default="", help="only process tools containing this substring")
    ap.add_argument("--no-skip-locked", action="store_true", help="gate even already-locked tools")
    ap.add_argument(
        "--re-gate", action="store_true", help="re-gate even tools with existing gate_result.json"
    )
    args = ap.parse_args()

    board = load_board()
    locked_bases = {slug for slug, t in board.items() if t.get("locked_archive")}

    print("Fetching completed Hetzner dirs ...", flush=True)
    completed = get_completed_dirs()
    print(f"Found {len(completed)} completed Hetzner eval dirs", flush=True)

    if args.only_slug:
        completed = [(s, d) for s, d in completed if args.only_slug in s]
        print(f"Filtered to {len(completed)} matching '{args.only_slug}'", flush=True)

    stats = {
        "processed": 0,
        "accepted": 0,
        "rule_c": 0,
        "potential_lock": 0,
        "rejected": 0,
        "skipped": 0,
        "no_baseline": 0,
        "not_native": 0,
    }

    for slug, remote_dir in completed:
        if args.limit and stats["processed"] >= args.limit:
            break

        base_slug = re.sub(r"\.[a-f0-9]+$", "", slug)

        if not args.no_skip_locked and base_slug in locked_bases:
            stats["skipped"] += 1
            continue

        local_import_dir = (
            HETZ_IMPORT_BASE / f"hetz_import_{slug.replace('__', '_').replace('/', '_')}"
        )
        local_slug_dir = local_import_dir / slug

        # Check if already gated (and not re-gating)
        existing_gate = local_import_dir / "gate_result.json"
        if existing_gate.exists() and not args.re_gate:
            try:
                eg = json.loads(existing_gate.read_text(encoding="utf-8", errors="replace"))
                decision = eg.get("decision", "?")
                rule = eg.get("decision_rule", "?")
                if decision == "accept":
                    stats["accepted"] += 1
                    if rule == "C":
                        stats["rule_c"] += 1
                    stats["processed"] += 1
                    continue
            except Exception:
                pass

        print(f"\n[{stats['processed'] + 1}] {slug}", flush=True)

        # Sync eval JSON from Hetzner (skip if already present)
        eval_already = local_slug_dir / f"{slug}.eval.json"
        if not eval_already.exists():
            if not _scp_dir(f"{remote_dir}/{slug}", local_import_dir):
                print("  scp FAILED, skipping")
                stats["skipped"] += 1
                continue
        else:
            print("  (eval JSON already local, skipping scp)")

        # Check native (not python wrapper)
        if not _check_native(local_slug_dir):
            print("  SKIP: looks like python wrapper (compile.sh contains subprocess/import)")
            stats["not_native"] += 1
            stats["skipped"] += 1
            continue

        # Find baseline
        baseline_eval, min_baseline = find_baseline(slug, board)
        if baseline_eval is None:
            print(f"  no baseline for {base_slug}, skipping")
            stats["no_baseline"] += 1
            stats["skipped"] += 1
            continue

        # Gate
        result = gate_tool(slug, local_import_dir, baseline_eval, min_baseline, args.dry_run)
        if result is None:
            stats["skipped"] += 1
            stats["processed"] += 1
            continue

        decision = result.get("decision", "?")
        # decision_rule comes from gate_result.json (stdout summary also has it after fix)
        gate_json_path = local_import_dir / "gate_result.json"
        if gate_json_path.exists():
            try:
                gate_full = json.loads(gate_json_path.read_text(encoding="utf-8", errors="replace"))
                rule = gate_full.get("decision_rule")
            except Exception:
                rule = result.get("decision_rule")
        else:
            rule = result.get("decision_rule")
        reason = (result.get("reason") or "")[:120]
        cand_passed = result.get("candidate_passed", "?")
        base_passed = result.get("baseline_passed", "?")
        print(f"  {decision.upper()} rule={rule} | {base_passed}->{cand_passed} | {reason}")

        if decision == "accept":
            stats["accepted"] += 1
            if rule == "C":
                stats["rule_c"] += 1
            cand = result.get("candidate") or {}
            cp = cand.get("passed", 0)
            cr = cand.get("runnable", 0)
            if cp > 0 and cr > 0 and cp >= cr:
                print(f"  *** POTENTIAL 100% LOCK: {cp}/{cr} ***")
                stats["potential_lock"] += 1

            rc = apply_gate(slug, local_import_dir, args.dry_run)
            if rc not in (0, 1):
                print(f"  apply returned rc={rc} (non-fatal)")

        elif decision == "reject":
            stats["rejected"] += 1

        stats["processed"] += 1

    print(f"\n{'=' * 60}")
    print(f"Processed:      {stats['processed']}")
    print(f"Accepted (A+B): {stats['accepted'] - stats['rule_c']}")
    print(f"Accepted (C):   {stats['rule_c']}  (progress-grade; fix regressions for ledger)")
    print(f"Rejected:       {stats['rejected']}")
    print(f"Potential 100%: {stats['potential_lock']}")
    print(
        f"Skipped:        {stats['skipped']}  (locked={len(locked_bases)}, no-baseline={stats['no_baseline']}, not-native={stats['not_native']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
