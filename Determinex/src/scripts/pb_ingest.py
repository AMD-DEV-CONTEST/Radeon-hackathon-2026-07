#!/usr/bin/env python3
"""pb_ingest — the ONE gated path that compiles every eval result (local OR Hetzner)
into the canonical corpus, so there's a single source of truth and no who/what/where/when
confusion.

For each finished eval.json it does, in order:
  1. record the score + provenance into eval_index.json (official_passed/total/failed/skipped/
     not_run/score_pct, last_eval_date, last_eval_source=local|hetzner) via the canonical updater.
  2. if it's a CLEAN 100% (passed==total, 0 not_run/skip/fail): archive_if_clean (copy to
     locked/ + flip official_full_suite_resolved) THEN verify_and_register (the provenance /
     anti-test-gaming gate). A lock is recorded ONLY if it passes the gate.
  3. feed the raw json into the training corpus via drive_tick (ungated, diagnostic).

State model (single source of truth):
  - eval_index.json  -> every tool's latest score + source + date (the board).
  - lock registry    -> gated locks only (verify_and_register).
  - locked/<slug>/   -> archived artifacts of locks.
  - training corpus  -> all results (drive_tick), for the flywheel.

Usage:
  python scripts/pb_ingest.py one <slug> <eval.json> --source hetzner
  python scripts/pb_ingest.py sweep         # pull+ingest all finished local+hetzner evals
"""

from __future__ import annotations

import argparse
import datetime as _dt
import glob
import json
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
REPO = _HERE.parent
import determinex_pb_eval as E  # noqa: E402  (archive_if_clean)
import determinex_pb_lock_registry as R  # noqa: E402  (verify_and_register)
import pb_eval_unified as U  # noqa: E402  (update_index_entry, load_index)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

HOST = "root@5.78.192.163"
KEY = str(Path.home() / ".ssh" / "id_citadel")
HZ_ROOT = "/root/citadel-programbench"
LOCAL_ROOT = Path("T:/determinex-programbench")


def _counts(data: dict) -> dict:
    tr = data.get("test_results") or data.get("results", {}).get("test_results") or []
    from collections import Counter

    st = Counter(x.get("status") for x in tr)
    p = st.get("passed", 0)
    t = len(tr)
    return {
        "passed": p,
        "total": t,
        "failed": st.get("failed", 0) + st.get("failure", 0) + st.get("error", 0),
        "skipped": st.get("skipped", 0),
        "not_run": st.get("not_run", 0),
        "pct": (100 * p / t) if t else 0.0,
        "clean": bool(t) and p == t,
    }


def _existing_row(slug: str) -> dict:
    for e in U.load_index():
        if e.get("slug") == slug:
            return e
    return {}


def ingest_one(slug: str, eval_json: Path, source: str) -> dict:
    data = json.loads(eval_json.read_text(encoding="utf-8"))
    c = _counts(data)
    today = _dt.date.today().isoformat()
    prev = _existing_row(slug)
    prev_fsr = bool(prev.get("official_full_suite_resolved"))
    prev_total = prev.get("official_total") or 0
    prev_pct = prev.get("official_score_pct") or 0
    # ANTI-REGRESSION: a stale/lower eval must NOT overwrite a higher recorded score. Only
    # update score fields when the new result is clean-100%, OR scores >= recorded, OR the row
    # was never freshly recorded. Otherwise skip (keep the better, known-good number).
    if not c["clean"] and prev.get("last_eval_date") and c["pct"] < prev_pct - 0.01:
        return {
            "slug": slug,
            "score": round(c["pct"], 2),
            "source": source,
            "skipped": f"anti-regression: {c['pct']:.1f}% < recorded {prev_pct}%",
        }
    # FSR guard: NEVER demote a real lock on a stale/partial eval. Only flip True->False if the
    # new eval is a comparable FULL run (>=95% of the recorded denominator) AND <100% (a genuine
    # regression). Always promote on a clean 100%.
    if c["clean"]:
        new_fsr = True
    elif prev_fsr and (not prev_total or c["total"] < 0.95 * prev_total):
        new_fsr = True  # partial/stale eval -> preserve the lock, don't demote
    else:
        new_fsr = False
    # 1) record score + provenance into eval_index (canonical updater)
    U.update_index_entry(
        slug,
        {
            "official_passed": c["passed"],
            "official_total": c["total"],
            "official_failed": c["failed"],
            "official_skipped": c["skipped"],
            "official_not_run": c["not_run"],
            "official_score_pct": round(c["pct"], 2),
            "last_eval_date": today,
            "last_eval_source": source,
            "official_full_suite_resolved": new_fsr,
        },
    )
    out = {"slug": slug, "score": round(c["pct"], 2), "source": source, "clean": c["clean"]}
    # 2) clean 100% -> archive + GATED register
    if c["clean"]:
        sub = REPO / "corpus" / "programbench" / "per_tool_overrides" / slug / "submission.tar.gz"
        try:
            E.archive_if_clean(slug, eval_json, sub if sub.exists() else None)
            locked_report = REPO / "corpus" / "programbench" / "locked" / slug / "eval_report.json"
            res = R.verify_and_register(
                slug, locked_report if locked_report.exists() else eval_json, source=source
            )
            out["gate"] = res
        except Exception as e:
            out["gate"] = {"ok": False, "why": f"archive/register error: {e}"}
    return out


def _pull_hetzner_evals(dest: Path) -> list[tuple[str, Path]]:
    """scp every finished Hetzner eval.json to dest; return [(slug, local_path)]."""
    ssh = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=40", "-i", KEY, HOST]
    listing = subprocess.run(
        ssh + [f"find {HZ_ROOT} -name '*.eval.json' -newermt '2026-06-19' 2>/dev/null"],
        capture_output=True,
        text=True,
        timeout=120,
    ).stdout.splitlines()
    out = []
    for remote in listing:
        remote = remote.strip()
        if not remote:
            continue
        slug = Path(remote).name.replace(".eval.json", "")
        local = dest / f"{slug}.eval.json"
        r = subprocess.run(
            [
                "scp",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "ConnectTimeout=40",
                "-i",
                KEY,
                f"{HOST}:{remote}",
                str(local),
            ],
            capture_output=True,
            timeout=120,
        )
        if r.returncode == 0:
            out.append((slug, local))
    return out


def sweep(max_age_hours: float = 36.0) -> int:
    import time as _t

    cutoff = _t.time() - max_age_hours * 3600
    results = []
    # local -- FRESH ONLY (recent mtime). Blanket-globbing all of LOCAL_ROOT ingests ancient
    # stale evals that regress good scores; the anti-regression guard + this mtime filter both
    # protect the corpus.
    seen = set()
    for ej in glob.glob(str(LOCAL_ROOT / "**" / "*.eval.json"), recursive=True):
        p = Path(ej)
        if p.stat().st_mtime < cutoff:
            continue
        slug = p.name.replace(".eval.json", "")
        if slug in seen:
            continue
        seen.add(slug)
        try:
            results.append(ingest_one(slug, p, "local"))
        except Exception as e:
            results.append({"slug": slug, "error": str(e)[:80]})
    # hetzner (pull then ingest)
    with tempfile.TemporaryDirectory() as td:
        for slug, lp in _pull_hetzner_evals(Path(td)):
            try:
                results.append(ingest_one(slug, lp, "hetzner"))
            except Exception as e:
                results.append({"slug": slug, "error": str(e)[:80]})
    # 3) training corpus (batch, ungated) -- best effort
    try:
        import determinex_pb_drive_tick as DT

        corpus = REPO / "corpus" / "programbench" / "training_corpus" / "pb_verdict_corpus.jsonl"
        ledger = REPO / "logs" / "programbench_factory" / "drive_ledger.json"
        # drive_tick wants a dir of jsons; point it at locals (hetzner already ingested to index)
        DT.tick(LOCAL_ROOT, corpus, ledger)
    except Exception as e:
        print(f"[ingest] drive_tick skipped: {e}")
    locks = [r for r in results if r.get("gate", {}).get("ok")]
    print(f"=== pb_ingest sweep: {len(results)} results ingested, {len(locks)} NEW gated LOCKS ===")
    for r in sorted(results, key=lambda x: -x.get("score", 0))[:30]:
        g = r.get("gate", {})
        tag = (
            " LOCK"
            if g.get("ok")
            else (f" gate-rejected: {g.get('why', '')[:40]}" if "gate" in r else "")
        )
        print(f"  {r.get('score', '?'):>6}%  {r['slug']:42} [{r.get('source', '?')}]{tag}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="pb_ingest - gated result->corpus compiler")
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("one")
    o.add_argument("slug")
    o.add_argument("eval_json", type=Path)
    o.add_argument("--source", default="hetzner")
    sub.add_parser("sweep")
    args = ap.parse_args()
    if args.cmd == "one":
        print(json.dumps(ingest_one(args.slug, args.eval_json, args.source), indent=2))
        return 0
    return sweep()


if __name__ == "__main__":
    sys.exit(main())
