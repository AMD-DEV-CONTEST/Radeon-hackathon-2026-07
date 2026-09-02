#!/usr/bin/env python3
"""
determinex_pb_eval.py -- the trustworthy eval primitive (cache-disciplined + auto-archive)
=======================================================================================
Two fixes for the failures that wasted cycles this session:

  1. CACHE DISCIPLINE -- PB caches the COMPILED task image. If compile.sh changes but
     the stale compiled image is reused, the fix never runs and the score is identical
     (the gdu mystery). `clear_compiled_image()` does `docker rmi` on the tool's
     programbench-compiled image BEFORE eval, so a changed compile.sh always rebuilds.

  2. AUTO-RE-ARCHIVE -- a lock's recorded score must never drift from what its archive
     PROVES. `archive_if_clean()` re-archives eval_report + submission to locked/<tool>/
     and flips eval_index official_full_suite_resolved whenever an eval is a clean 100%
     (passed==total, 0 failed/not_run/skipped). Closes the 8 stale-lock gap permanently.

Local-first: runs the local PB CLI CPU-capped for light tools; pass host='hetzner' to
dispatch over SSH for heavy C/C++. eval remains the only oracle.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PBROOT = REPO / "corpus" / "programbench"
LOCKED = PBROOT / "locked"
EVAL_INDEX = PBROOT / "eval_index.json"
PB_LOCAL = Path("T:/Dev/ProgramBench/.venv/Scripts/programbench.exe")
PILOT_ROOT = Path("T:/determinex-programbench")
HET = "root@5.78.192.163"
HET_KEY = str(Path.home() / ".ssh" / "id_citadel")


def _reclaim_disk(host: str) -> None:
    """Prune dangling images + build cache + stopped containers so cache-cleared
    REBUILDS don't pile up layers and fill the disk (the root cause of the
    results_read_failed=0 storm: disk hit 100%, fresh builds couldn't write results).
    Does NOT touch tagged base :task images. Cache discipline = rmi + prune."""
    cmds = ["docker container prune -f", "docker image prune -f", "docker builder prune -af"]
    if host == "local":
        for c in cmds:
            try:
                subprocess.run(c.split(), capture_output=True, timeout=120)
            except Exception:
                pass
    else:
        try:
            subprocess.run(
                ["ssh", "-i", HET_KEY, HET, "; ".join(cmds)],
                capture_output=True,
                text=True,
                timeout=180,
            )
        except Exception:
            pass


def clear_compiled_image(slug: str, host: str = "local") -> list[str]:
    """docker rmi the cached compiled image(s) for a tool so a changed compile.sh
    forces a rebuild, THEN reclaim disk so rebuilds never fill it. Returns images removed."""
    base = slug.split(".")[0].lower()
    short = slug.split("__")[-1].split(".")[0].lower()
    _reclaim_disk(host)  # <-- prevent the disk-full -> results_read_failed storm
    if host == "local":
        try:
            out = subprocess.run(
                ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout
        except Exception:
            return []
        imgs = [
            ln
            for ln in out.splitlines()
            if "programbench-compiled" in ln and (base in ln.lower() or short in ln.lower())
        ]
        for im in imgs:
            subprocess.run(["docker", "rmi", "-f", im], capture_output=True, timeout=60)
        return imgs
    else:  # hetzner
        cmd = (
            f"docker images --format '{{{{.Repository}}}}:{{{{.Tag}}}}' | "
            f"grep -i programbench-compiled | grep -i {short} | "
            f"xargs -r docker rmi -f 2>/dev/null; echo done"
        )
        subprocess.run(
            ["ssh", "-i", HET_KEY, HET, cmd], capture_output=True, text=True, timeout=120
        )
        return [f"(hetzner) programbench-compiled *{short}*"]


def run_eval(slug: str, pilot_dir: Path, cpus: int = 2, host: str = "local") -> Path | None:
    """Cache-clear, then eval. Returns the report path (or None)."""
    clear_compiled_image(slug, host)
    author = slug.split("__")[0]
    env_cpus = str(cpus)
    if host == "local":
        import os

        env = dict(os.environ, PROGRAMBENCH_DOCKER_CPUS=env_cpus, PYTHONUTF8="1")
        subprocess.run(
            [str(PB_LOCAL), "eval", str(pilot_dir), "--filter", author, "--force"],
            env=env,
            capture_output=True,
            text=True,
            timeout=3600,
        )
    else:
        cmd = (
            f"PROGRAMBENCH_DOCKER_CPUS=8 /root/ProgramBench/.venv/bin/programbench eval "
            f"{pilot_dir} --filter {author} --force"
        )
        subprocess.run(
            ["ssh", "-i", HET_KEY, HET, cmd], capture_output=True, text=True, timeout=3600
        )
    reps = list(Path(pilot_dir).rglob("*.eval.json"))
    return max(reps, key=lambda p: p.stat().st_mtime) if reps else None


def report_counts(report: Path) -> dict:
    rr = json.loads(report.read_text(encoding="utf-8")).get("test_results", [])
    c = Counter(x.get("status", "?") for x in rr)
    p, tot = c.get("passed", 0), len(rr)
    return {
        "passed": p,
        "total": tot,
        "failed": c.get("failure", 0) + c.get("failed", 0),
        "not_run": c.get("not_run", 0),
        "skipped": c.get("skipped", 0),
        "clean_100": tot > 0
        and p == tot
        and c.get("failure", 0) + c.get("failed", 0) == 0
        and c.get("not_run", 0) == 0
        and c.get("skipped", 0) == 0,
        "pct": round(p / tot * 100, 2) if tot else 0,
    }


def archive_if_clean(slug: str, report: Path, submission: Path | None = None) -> dict:
    """If the eval is a clean 100%, re-archive (report + submission) to locked/<tool>/
    and set eval_index official_full_suite_resolved. Keeps claimed == proven."""
    cnt = report_counts(report)
    if not cnt["clean_100"]:
        return {
            "archived": False,
            "reason": f"not clean 100% ({cnt['passed']}/{cnt['total']} "
            f"f={cnt['failed']} nr={cnt['not_run']} sk={cnt['skipped']})",
            **cnt,
        }
    # find/make archive dir
    dest = None
    if LOCKED.exists():
        for d in LOCKED.iterdir():
            if d.is_dir() and (
                d.name == slug
                or d.name.split(".")[0] == slug.split(".")[0]
                or d.name.split("__")[-1].split(".")[0] == slug.split("__")[-1].split(".")[0]
            ):
                dest = d
                break
    if not dest:
        dest = LOCKED / slug
        dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(report, dest / "eval_report.json")
    if submission and submission.exists():
        shutil.copy2(submission, dest / "submission.tar.gz")
    # update eval_index
    idx = json.loads(EVAL_INDEX.read_text(encoding="utf-8"))
    for e in idx:
        s = (e.get("slug") or "").replace(".eval", "")
        if (
            s == slug
            or s.split(".")[0] == slug.split(".")[0]
            or s.split("__")[-1].split(".")[0] == slug.split("__")[-1].split(".")[0]
        ):
            e["status"] = "strict_lock"
            e["official_full_suite_resolved"] = True
            e["official_score_pct"] = 100.0
            e["official_passed"] = cnt["passed"]
            e["official_total"] = cnt["total"]
            e["official_failed"] = 0
            e["official_not_run"] = 0
            e["official_skipped"] = 0
            e["last_eval_date"] = "2026-06-15"
            e["last_eval_source"] = "cache_clean_reverify"
            break
    EVAL_INDEX.write_text(json.dumps(idx, indent=2), encoding="utf-8")
    return {"archived": True, "dest": str(dest), **cnt}


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="Determinex trustworthy PB eval (cache-clean + auto-archive)"
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("eval")
    r.add_argument("slug")
    r.add_argument("pilot_dir", type=Path)
    r.add_argument("--cpus", type=int, default=2)
    r.add_argument("--host", default="local")
    r.add_argument("--archive", action="store_true", help="auto-re-archive if clean 100%")
    rmi = sub.add_parser("clear-cache")
    rmi.add_argument("slug")
    rmi.add_argument("--host", default="local")
    ar = sub.add_parser("archive-if-clean")
    ar.add_argument("slug")
    ar.add_argument("report", type=Path)
    ar.add_argument("--submission", type=Path, default=None)
    args = ap.parse_args()
    if args.cmd == "clear-cache":
        print("removed:", clear_compiled_image(args.slug, args.host))
        return 0
    if args.cmd == "eval":
        rep = run_eval(args.slug, args.pilot_dir, args.cpus, args.host)
        if not rep:
            print("no report produced")
            return 1
        cnt = report_counts(rep)
        print(f"{args.slug}: {cnt['pct']}% {cnt}")
        if args.archive:
            sub_path = args.pilot_dir / args.slug / "submission.tar.gz"
            print(archive_if_clean(args.slug, rep, sub_path if sub_path.exists() else None))
        return 0
    if args.cmd == "archive-if-clean":
        print(archive_if_clean(args.slug, args.report, args.submission))
        return 0
    return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
