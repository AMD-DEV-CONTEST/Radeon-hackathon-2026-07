#!/usr/bin/env python3
"""pb_drive — the autonomous self-eval + self-remediate loop.

The corpus drives ITSELF toward a target score: per tool it loops
    eval (on Hetzner) -> read score -> ask the corpus what it needs
    (determinex_pb_autofix) -> apply the fix -> repack complete -> re-eval
until score >= target, a lock (passed==total), no auto-fix remains, or max-iters.

This is NOT a new fixer — it COMPOSES the existing modules (AUDIT-BEFORE-BUILD):
  - determinex_pb_autofix.autofix()      (self-diagnose + apply build/cgo/fts5/etc.)
  - determinex_pb_autofix.pack_submission (complete repack — beats the freshen-drift trap)
  - programbench eval on Hetzner       (the system evals itself; the real oracle)

When no auto-fix applies and the tool is still <target, it prints exactly WHAT THE
CORPUS STILL NEEDS (the top failure clusters) so a human/behavioral pass can take it
the last mile. Build-broken tools it lifts fully autonomously.

Usage:
  python scripts/pb_drive.py <slug> [<slug>...] [--target 90] [--max-iters 4]
  python scripts/pb_drive.py --from-triage [--bucket AUTOFIX] [--target 90]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import determinex_pb_autofix as A  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

HOST = "root@5.78.192.163"
KEY = str(Path.home() / ".ssh" / "id_citadel")
SSH = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=40", "-i", KEY, HOST]
SCP = ["scp", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=40", "-i", KEY]
ROOT = "/root/citadel-programbench"
PB = "/root/ProgramBench/.venv/bin/programbench"


def ssh(cmd: str, timeout: int = 120) -> str:
    try:
        r = subprocess.run(SSH + [cmd], capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception as e:
        return f"__SSH_ERR__ {e}"


def find_factory_dir(slug: str) -> str | None:
    out = ssh(f"ls -d {ROOT}/*{slug}* 2>/dev/null | head -1")
    line = out.strip().splitlines()[0] if out.strip() else ""
    return line.split("/")[-1] if line else None


def read_eval(fdir: str, slug: str) -> tuple[int, int, Counter, Counter]:
    """Return (passed, total, status_counter, top_failure_signatures)."""
    pycode = (
        "import json,glob;from collections import Counter;"
        f"c=glob.glob('{ROOT}/{fdir}/**/*.eval.json',recursive=True);"
        "d=json.load(open(c[0])) if c else {};"
        "tr=d.get('test_results') or d.get('results',{}).get('test_results') or [];"
        "st=Counter(x.get('status') for x in tr);"
        "sig=Counter();"
        "[sig.update([next((l.strip()[:80] for l in ((x.get('extra') or {}).get('text','')).splitlines() "
        "if l.strip().startswith('E ') or 'assert' in l or 'Error' in l),'?')]) "
        "for x in tr if x.get('status') in ('failed','error','failure')];"
        "print(json.dumps({'p':st.get('passed',0),'t':len(tr),'st':dict(st),'sig':dict(sig.most_common(8))}))"
    )
    out = ssh(f'{PB.replace("programbench", "python")} -c "{pycode}"')
    for ln in out.splitlines():
        if ln.startswith("{"):
            d = json.loads(ln)
            return d["p"], d["t"], Counter(d["st"]), Counter(d["sig"])
    return 0, 0, Counter(), Counter()


def run_eval(fdir: str, author: str, slug: str, timeout: int = 3600) -> None:
    log = f"/tmp/grind/{slug}.drive.log"
    ssh(
        f"mkdir -p /tmp/grind; PYTHONUTF8=1 PROGRAMBENCH_DOCKER_CPUS=4 {PB} eval "
        f"{ROOT}/{fdir} --filter {author} --force > {log} 2>&1",
        timeout=timeout,
    )


def upload(slug: str, fdir: str) -> bool:
    sub = A.OVERRIDES / slug / "submission.tar.gz"
    A.pack_submission(slug)
    r = subprocess.run(
        SCP + [str(sub), f"{HOST}:{ROOT}/{fdir}/{slug}/submission.tar.gz"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return r.returncode == 0


def drive(slug: str, target: float, max_iters: int) -> dict:
    full = A._resolve_full_slug(slug) or slug
    fdir = find_factory_dir(full)
    if not fdir:
        return {"slug": full, "verdict": "NO_REMOTE_DIR"}
    author = full.split("__")[0]
    history = []
    for it in range(1, max_iters + 1):
        print(f"\n[drive {full}] iter {it}: evaling...", flush=True)
        run_eval(fdir, author, full)
        p, t, st, sig = read_eval(fdir, full)
        score = (100.0 * p / t) if t else 0.0
        history.append(score)
        print(f"[drive {full}] {p}/{t} = {score:.1f}%  status={dict(st)}", flush=True)
        if t and p == t:
            return {"slug": full, "verdict": "LOCK", "score": 100.0, "history": history}
        if score >= target:
            return {"slug": full, "verdict": "TARGET_MET", "score": score, "history": history}
        # ask the corpus what it needs + apply
        report = A._find_eval_report(full, None)
        # prefer the just-run remote eval.json: pull it local for autofix
        res = A.autofix(full, report, apply=True)
        if res.changed:
            print(f"[drive {full}] corpus self-fixed: {res.applied or res.notes[:1]}", flush=True)
            if not upload(full, fdir):
                return {
                    "slug": full,
                    "verdict": "UPLOAD_FAILED",
                    "score": score,
                    "history": history,
                }
            continue
        # no auto-fix -> report exactly what the corpus still needs
        needs = "; ".join(f"[{n}] {s}" for s, n in sig.most_common(5))
        print(f"[drive {full}] CORPUS NEEDS NEXT (no auto-fix): {needs}", flush=True)
        return {
            "slug": full,
            "verdict": "NEEDS_BEHAVIORAL",
            "score": score,
            "needs": dict(sig.most_common(8)),
            "history": history,
        }
    return {
        "slug": full,
        "verdict": "MAX_ITERS",
        "score": history[-1] if history else 0,
        "history": history,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="pb_drive — autonomous self-eval+remediate loop")
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--target", type=float, default=90.0)
    ap.add_argument("--max-iters", type=int, default=4)
    ap.add_argument(
        "--wait-for-queues",
        action="store_true",
        help="wait until grinder/phase* + any programbench eval finish before starting",
    )
    args = ap.parse_args()
    if args.wait_for_queues:
        print("[drive] waiting for existing queues to clear...", flush=True)
        while True:
            # [p] bracket trick so the pgrep command does not match ITSELF (the self-match
            # bug that hung the first run: 'programbench eval' matched the pgrep argv).
            busy = ssh(
                "pgrep -f '[p]rogrambench eval' >/dev/null && echo busy || "
                "(pgrep -f '[p]b_grind.sh|[p]b_phase' >/dev/null && echo busy || echo free)"
            )
            if "free" in busy:
                break
            time.sleep(60)
        print("[drive] queues clear, starting.", flush=True)
    results = []
    for slug in args.slugs:
        try:
            results.append(drive(slug, args.target, args.max_iters))
        except Exception as e:
            results.append({"slug": slug, "verdict": "ERROR", "error": str(e)[:120]})
        print(f"[drive] RESULT: {results[-1]}", flush=True)
    out = Path("logs/programbench_factory/pb_drive_results.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n=== pb_drive done -> {out} ===")
    for r in results:
        print(f"  {r.get('verdict'):18} {r['slug']:42} {r.get('score', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
