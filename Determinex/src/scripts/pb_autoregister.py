#!/usr/bin/env python3
"""
pb_autoregister.py -- hands-off PB lock registration from a Hetzner eval-pool result set.
============================================================================================
The manual loop this replaces (per tool): scp submission + eval json back, run the registry
verify (anti-gaming + sha-pin gates), git add/commit. Doing that by hand per tool is the slow
part of every wake. This does the whole batch in one command, and ONLY registers a tool that
passes the SAME gates (passed==total, f=0, nr=0, sk=0, sha-pin, no test-gaming) -- it cannot
create a fake lock; a non-clean or gamed tool is reported and skipped, never registered.

It pulls from a Hetzner pool laid out by the eval driver:
  <remote_base>/results.jsonl                      # one json line per tool (+ {"DONE":true})
  <remote_base>/jsons/<slug>.eval.json             # the eval report
  <remote_base>/pilot/<slug>/submission.tar.gz     # the exact artifact that produced it

Usage:
  python scripts/pb_autoregister.py <remote_base> [--host root@5.78.192.163] [--key ~/.ssh/id_citadel]
                                    [--commit] [--dry-run]
  e.g. python scripts/pb_autoregister.py /root/capfix9 --commit
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCKED = ROOT / "corpus" / "programbench" / "locked"
REG = ROOT / "corpus" / "programbench" / "verified_locks.json"


def _ssh(host: str, key: str, cmd: str) -> str:
    r = subprocess.run(
        ["ssh", "-i", key, "-o", "ConnectTimeout=25", host, cmd], capture_output=True, text=True
    )
    return r.stdout


def _scp(host: str, key: str, remote: str, local: Path) -> bool:
    local.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["scp", "-i", key, "-o", "ConnectTimeout=25", f"{host}:{remote}", str(local)],
        capture_output=True,
        text=True,
    )
    return r.returncode == 0 and local.exists()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("remote_base", help="e.g. /root/capfix9")
    ap.add_argument("--host", default="root@5.78.192.163")
    ap.add_argument("--key", default=str(Path.home() / ".ssh" / "id_citadel"))
    ap.add_argument("--commit", action="store_true", help="git commit the batch")
    ap.add_argument("--dry-run", action="store_true", help="report only, no registration")
    args = ap.parse_args()

    verified = set(json.loads(REG.read_text(encoding="utf-8"))["locks"]) if REG.exists() else set()
    raw = _ssh(args.host, args.key, f"cat {args.remote_base}/results.jsonl 2>/dev/null")
    if not raw.strip():
        print(f"no results at {args.remote_base}/results.jsonl")
        return 1

    clean, notclean, already = [], [], []
    for line in raw.splitlines():
        line = line.strip()
        if not line or '"DONE"' in line[:10]:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        slug = d.get("slug")
        if not slug:
            continue
        is_clean = d.get("clean") or (
            d.get("error") is None
            and d.get("passed") == d.get("total")
            and d.get("failed", 1) == 0
            and d.get("not_run", 1) == 0
            and d.get("skipped", 1) == 0
        )
        if not is_clean:
            notclean.append(
                (
                    slug,
                    d.get("error")
                    or f"{d.get('passed')}/{d.get('total')} sk={d.get('skipped')} nr={d.get('not_run')} f={d.get('failed')}",
                )
            )
        elif slug in verified:
            already.append(slug)
        else:
            clean.append(slug)

    print(
        f"results: {len(clean)} new-clean | {len(already)} already-locked | {len(notclean)} not-clean"
    )
    for s, why in notclean:
        print(f"  skip {s}: {why}")
    if args.dry_run:
        for s in clean:
            print(f"  WOULD register {s}")
        return 0

    registered = []
    for slug in clean:
        d = LOCKED / slug
        ok_sub = _scp(
            args.host,
            args.key,
            f"{args.remote_base}/pilot/{slug}/submission.tar.gz",
            d / "submission.tar.gz",
        )
        ok_json = _scp(
            args.host,
            args.key,
            f"{args.remote_base}/jsons/{slug}.eval.json",
            d / "eval_report.json",
        )
        if not (ok_sub and ok_json):
            print(f"  FETCH-FAIL {slug} (sub={ok_sub} json={ok_json})")
            continue
        # the gates live in the registry verify -- this is the only thing that can mint a lock
        r = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "determinex_pb_lock_registry.py"),
                "verify",
                slug,
                str(d / "eval_report.json"),
            ],
            capture_output=True,
            text=True,
        )
        out = r.stdout + r.stderr
        if "'ok': True" in out:
            registered.append(slug)
            print(f"  REGISTERED {slug}")
        else:
            print(
                f"  GATE-REJECT {slug}: {out.strip().splitlines()[-1] if out.strip() else 'no output'}"
            )

    print(f"\nregistered {len(registered)} new locks")
    if registered and args.commit:
        subprocess.run(
            [
                "git",
                "add",
                "corpus/programbench/verified_locks.json",
                "corpus/programbench/locked",
                "corpus/programbench/CAPABILITY.md",
            ],
            cwd=ROOT,
        )
        msg = (
            f"PB: auto-register {len(registered)} locks via pb_autoregister "
            f"({', '.join(s.split('__')[-1].split('.')[0] for s in registered)})\n\n"
            "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
        )
        subprocess.run(["git", "commit", "-q", "-m", msg], cwd=ROOT)
        n = len(json.loads(REG.read_text(encoding="utf-8"))["locks"])
        print(f"committed. verified_locks now: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
