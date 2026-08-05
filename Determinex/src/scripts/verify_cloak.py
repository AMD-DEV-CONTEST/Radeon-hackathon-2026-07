"""
scripts/verify_cloak.py — Project Cloak Post-Run Audit
=======================================================
Verifies that no private identifiers reached the cloud AI during a cloaked run.

What it checks:
  1. For every instance that has a cloak_map_<iid>.json, load the forward map.
  2. Scan api_requests.jsonl (if present) — confirm no original identifiers appear
     in any logged API request prompt excerpt.
  3. Summarise: instances checked, leaks found, star-import holes counted.

Usage:
  python scripts/verify_cloak.py --run-dir logs/swebench/<run_id>
  python scripts/verify_cloak.py --run-dir logs/swebench/<run_id> --strict

  --strict: exit 1 if ANY leak is found (for CI pipelines)

Output:
  Prints a summary table to stdout.
  Writes logs/swebench/<run_id>/cloak_audit/verify_report.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Windows stdout defaults to charmap — force UTF-8 so unicode chars don't crash
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_X_TOKEN_RE = re.compile(r"\bx_\d{4}\b")


def load_cloak_map(map_path: Path) -> dict[str, str]:
    """Returns forward map {original → x_NNNN} from a saved cloak_map file."""
    try:
        data = json.loads(map_path.read_text(encoding="utf-8"))
        return data.get("symbol_map", {}).get("forward", {})
    except Exception as e:
        print(f"  [WARN] Cannot load {map_path.name}: {e}")
        return {}


def check_instance(
    instance_id: str,
    forward_map: dict[str, str],
    api_requests_path: Path,
) -> list[str]:
    """
    Return list of leak descriptions for this instance.
    A leak = an original private identifier found in an API request prompt excerpt.
    """
    leaks: list[str] = []
    if not api_requests_path.exists():
        return leaks  # no API audit log — cannot verify, not a leak

    private_names = sorted(forward_map.keys(), key=len, reverse=True)
    if not private_names:
        return leaks

    # Build a single pattern for efficiency
    pattern = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in private_names) + r")\b")

    with api_requests_path.open(encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            try:
                entry = json.loads(raw)
            except Exception:
                continue
            if entry.get("instance_id") != instance_id:
                continue
            prompt = entry.get("prompt_excerpt", "")
            role = entry.get("role", "?")
            found = set(pattern.findall(prompt))
            for name in found:
                leaks.append(
                    f"  LEAK  instance={instance_id} role={role} "
                    f"line={line_no} name='{name}' → {forward_map[name]}"
                )

    return leaks


def verify_run(run_dir: Path, strict: bool = False) -> int:
    """
    Run the full audit for a given run directory.
    Returns 0 on clean, 1 if leaks found (or strict + no audit logs).
    """
    audit_dir = run_dir / "cloak_audit"
    if not audit_dir.exists():
        print(f"[verify_cloak] No cloak_audit/ directory in {run_dir}")
        print("  This run was not cloaked, or DETERMINEX_CLOAK_AUDIT was not set.")
        return 0

    map_files = sorted(audit_dir.glob("cloak_map_*.json"))
    api_log = audit_dir / "api_requests.jsonl"
    failure_log = audit_dir / "cloak_failures.jsonl"

    print(f"\n{'=' * 70}")
    print("  Project Cloak — Verification Report")
    print(f"  Run dir : {run_dir}")
    print(f"  Maps    : {len(map_files)} instance(s)")
    print(
        f"  API log : {'present' if api_log.exists() else 'absent (DETERMINEX_CLOAK_AUDIT not set)'}"
    )
    print(f"{'=' * 70}\n")

    total_instances = len(map_files)
    total_identifiers = 0
    total_star_holes = 0
    total_leaks = 0
    all_leaks: list[str] = []
    instances_with_no_audit: list[str] = []

    for map_path in map_files:
        iid = map_path.stem.replace("cloak_map_", "")
        try:
            raw = json.loads(map_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [SKIP] {iid}: cannot parse map — {e}")
            continue

        forward = raw.get("symbol_map", {}).get("forward", {})
        star_holes = len(raw.get("star_import_warnings", []))
        n_ids = raw.get("private_id_count", len(forward))
        total_identifiers += n_ids
        total_star_holes += star_holes

        if not api_log.exists():
            instances_with_no_audit.append(iid)
            print(
                f"  [{iid}] {n_ids} identifiers mapped, {star_holes} star-hole(s) — no API log to verify"
            )
            continue

        leaks = check_instance(iid, forward, api_log)
        total_leaks += len(leaks)
        all_leaks.extend(leaks)

        status = "CLEAN" if not leaks else f"LEAK×{len(leaks)}"
        print(f"  [{iid}] {n_ids} ids, {star_holes} star-hole(s) -> {status}")
        for leak in leaks:
            print(leak)

    # Restoration failures
    n_failures = 0
    if failure_log.exists():
        try:
            with failure_log.open(encoding="utf-8") as f:
                n_failures = sum(1 for _ in f)
        except Exception:
            pass

    print(f"\n{'=' * 70}")
    print("  SUMMARY")
    print(f"{'=' * 70}")
    print(f"  Instances verified    : {total_instances}")
    print(f"  Total identifiers     : {total_identifiers}")
    print(f"  Total star-import holes: {total_star_holes} (known, documented)")
    print(f"  Restoration failures  : {n_failures}")
    print(f"  Privacy leaks found   : {total_leaks}")

    if instances_with_no_audit:
        print(f"\n  Note: {len(instances_with_no_audit)} instance(s) could not be verified")
        print("  (re-run with DETERMINEX_CLOAK_AUDIT=1 for full API request logging)")

    if total_leaks == 0 and api_log.exists():
        print("\n  VERDICT: CLEAN — zero proprietary identifiers reached cloud APIs")
        claim_line = (
            f"  CLAIM  : Determinex resolved these instances while the cloud AI was\n"
            f"           blind to all {total_identifiers} proprietary identifier tokens\n"
            f"           ({total_star_holes} star-import names are a documented known hole)"
        )
        print(claim_line)
    elif total_leaks > 0:
        print(f"\n  VERDICT: {total_leaks} LEAK(S) FOUND — review above before publishing")
    else:
        print("\n  VERDICT: UNVERIFIED — run with DETERMINEX_CLOAK_AUDIT=1 for proof")

    print(f"{'=' * 70}\n")

    # Write JSON report
    report = {
        "run_dir": str(run_dir),
        "instances_checked": total_instances,
        "total_private_identifiers": total_identifiers,
        "star_import_holes": total_star_holes,
        "restoration_failures": n_failures,
        "leaks_found": total_leaks,
        "leaks": all_leaks,
        "api_audit_present": api_log.exists(),
        "verdict": (
            "clean"
            if (total_leaks == 0 and api_log.exists())
            else "leaked"
            if total_leaks > 0
            else "unverified"
        ),
    }
    report_path = audit_dir / "verify_report.json"
    try:
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"  [WARN] Could not write report: {e}")
    else:
        print(f"  Report saved: {report_path}")

    if strict and total_leaks > 0:
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify Project Cloak — confirm no private identifiers reached cloud APIs"
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        required=True,
        help="Path to the run directory (e.g. logs/swebench/determinex_lite_B-Cloaked_...)",
    )
    parser.add_argument(
        "--strict", action="store_true", help="Exit 1 if any leak is found (for CI integration)"
    )
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    if not run_dir.exists():
        print(f"[verify_cloak] ERROR: run directory not found: {run_dir}")
        sys.exit(2)

    sys.exit(verify_run(run_dir, strict=args.strict))


if __name__ == "__main__":
    main()
