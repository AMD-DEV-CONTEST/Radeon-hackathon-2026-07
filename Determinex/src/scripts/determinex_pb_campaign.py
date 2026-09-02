#!/usr/bin/env python3
"""
determinex_pb_campaign.py -- the autonomic fan-out driver
======================================================
Turns the assisted loop (a human dispatching adjudicator + autofix per tool) into a
self-driving one. It orchestrates the pieces built this session:

  adjudicator (diagnose) -> corpus-retrieve (what fixed this elsewhere) -> autofix
  (apply structural+behavioral, legitimacy-gated) -> eval (Oracle) -> keep_if_better
  (regression gate) -> capture (flywheel) -> back-propagate (new technique -> retry
  every older tool whose residual matches it) -> maybe_retrain.

Four capabilities the user asked for, wired here:
  1. FAN-OUT DRIVER       -- drive() / drive_all(): the unattended per-tool loop.
  2. CORPUS RETRIEVAL     -- corpus_retrieve(): at fix-time, query the behavioral/
     verdict corpus + locked lessons for how a SIMILAR failure was fixed elsewhere.
  3. BACK-PROPAGATION     -- back_propagate(): a newly-proven technique auto-queues a
     retry of every older tool whose residual matches that technique's signature.
  4. RETRAIN TRIGGER      -- maybe_retrain(): when enough NEW training-eligible pairs
     accumulate, fire the flywheel so the models internalize the patterns.

EVAL is pluggable (`eval_fn(slug, pilot_dir) -> report_path`) so the same driver runs
local-capped or on Hetzner. `plan-all` runs the whole diagnosis+retrieval pass CPU-free
to produce the ranked fix queue without spending a single eval.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
from determinex_adjudicator import adjudicate_eval_report  # noqa: E402
from determinex_pb_autofix import OVERRIDES, autofix  # noqa: E402
from determinex_pb_integrity import keep_if_better, legitimacy_class  # noqa: E402

REPO = _HERE.parent
PBROOT = REPO / "corpus" / "programbench"
EVAL_INDEX = PBROOT / "eval_index.json"
BEHAVIORAL_CORPUS = PBROOT / "training_corpus" / "pb_behavioral_corpus.jsonl"
LOCKED = PBROOT / "locked"


# ---------------------------------------------------------------------------
# Candidates: every non-locked tool with build material.
# ---------------------------------------------------------------------------
def candidates(min_pct: float = 0.0, max_pct: float = 100.0) -> list[dict]:
    idx = json.loads(EVAL_INDEX.read_text(encoding="utf-8"))
    out = []
    for e in idx:
        st = e.get("status", "")
        if st in ("strict_lock",):
            continue
        if e.get("official_full_suite_resolved"):
            continue
        pct = e.get("official_score_pct") or 0
        if not (min_pct <= pct <= max_pct):
            continue
        slug = (e.get("slug") or "").replace(".eval", "")
        out.append(
            {
                "slug": slug,
                "status": st,
                "pct": pct,
                "failed": e.get("official_failed"),
                "not_run": e.get("official_not_run"),
            }
        )
    # rank: closest-to-lock first (highest pct), then by fewest failures
    out.sort(key=lambda x: -(x["pct"] or 0))
    return out


def find_override(slug: str) -> Path | None:
    for d in OVERRIDES.iterdir():
        if d.is_dir() and (
            d.name == slug
            or d.name.split(".")[0] == slug.split(".")[0]
            or d.name.split("__")[-1].split(".")[0] == slug.split("__")[-1].split(".")[0]
        ):
            if (d / "compile.sh").exists():
                return d
    return None


def latest_report(slug: str) -> Path | None:
    """Newest eval report for a tool, searched across local pilot dirs + staging."""
    base = slug.split("__")[-1].split(".")[0]
    roots = [Path("T:/determinex-programbench"), REPO / ".determinex_staging", LOCKED / slug]
    best, best_mt = None, 0.0
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*.eval.json"):
            if base in str(p) or slug.split(".")[0] in str(p):
                mt = p.stat().st_mtime
                if mt > best_mt:
                    best, best_mt = p, mt
    return best


# ---------------------------------------------------------------------------
# 2. CORPUS RETRIEVAL -- how was a SIMILAR failure fixed elsewhere?
# ---------------------------------------------------------------------------
def _signature(text: str) -> str:
    """Collapse a failure text to a coarse signature for cross-tool matching."""
    t = re.sub(r"\d+", "#", text or "")
    t = re.sub(r"0x[0-9a-f]+|[0-9a-f]{7,}", "H", t)
    t = re.sub(r"/tmp/\S+|/workspace/\S+", "P", t)
    toks = re.findall(r"[A-Za-z_]{4,}", t)
    return " ".join(sorted(set(toks))[:20])


def corpus_retrieve(failure_text: str, k: int = 5) -> list[dict]:
    """Query the behavioral corpus for past fixes whose failure signature overlaps.
    Returns ranked {tool, diff_kind, technique, verdict, overlap}. This is the
    'pull from every other tool's history' capability."""
    if not BEHAVIORAL_CORPUS.exists():
        return []
    want = set(_signature(failure_text).split())
    if not want:
        return []
    scored = []
    for line in BEHAVIORAL_CORPUS.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        sig = set(
            _signature((rec.get("actual", "") + " " + rec.get("expected", "")).strip()).split()
        )
        ov = len(want & sig)
        if ov >= 2 and rec.get("verdict") in ("resolved", "improved"):
            scored.append(
                (
                    ov,
                    {
                        "tool": rec.get("tool"),
                        "diff_kind": rec.get("diff_kind"),
                        "technique": rec.get("technique"),
                        "verdict": rec.get("verdict"),
                        "overlap": ov,
                    },
                )
            )
    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored[:k]]


# ---------------------------------------------------------------------------
# 1. FAN-OUT DRIVER -- the per-tool loop (eval pluggable).
# ---------------------------------------------------------------------------
def plan_tool(slug: str) -> dict:
    """CPU-free: diagnose + autofix-plan + corpus-retrieve for one tool."""
    d = find_override(slug)
    if not d:
        return {"slug": slug, "error": "no override dir"}
    rep = latest_report(slug)
    adj_counts, retrieved = {}, []
    if rep:
        adjs = adjudicate_eval_report(rep)
        adj_counts = dict(Counter(a.strategy for a in adjs))
        # retrieve for the most common failure
        first_txt = next((a.failure.text for a in adjs if a.failure.text), "")
        retrieved = corpus_retrieve(first_txt)
    res = autofix(slug, rep, apply=False)
    return {
        "slug": slug,
        "report": str(rep) if rep else None,
        "adjudication": adj_counts,
        "autofix_would": res.applied + res.skipped,
        "corpus_suggestions": retrieved,
    }


def drive(slug: str, eval_fn, max_iters: int = 3) -> dict:
    """The unattended loop for ONE tool: fix -> eval -> keep-if-better -> iterate.
    eval_fn(slug, pilot_dir) -> report_path. Returns the trajectory."""
    d = find_override(slug)
    if not d:
        return {"slug": slug, "error": "no override dir"}
    traj = []
    before = latest_report(slug)
    for i in range(max_iters):
        res = autofix(slug, before, apply=True)
        if not res.changed:
            traj.append({"iter": i, "note": "no further auto-fix; stop"})
            break
        # legitimacy gate every applied fix
        for ap in res.applied:
            tech = ap.split(":")[0]
            lc = legitimacy_class(tech)
            if lc.legitimacy == "RED":
                traj.append({"iter": i, "ABORT": f"RED fix refused: {ap}"})
                return {"slug": slug, "trajectory": traj, "stopped": "RED"}
        pilot = Path("T:/determinex-programbench") / f"campaign_{slug}_{i}"
        after = eval_fn(slug, pilot)  # the Oracle (pluggable: local/Hetzner)
        gate = (
            keep_if_better(before, after)
            if before and after
            else {"keep": True, "verdict": "no-baseline"}
        )
        traj.append({"iter": i, "applied": res.applied, "gate": gate["verdict"]})
        if not gate.get("keep"):
            traj.append({"iter": i, "REVERTED": "regression; restoring prior submission"})
            # caller restores from .autofix.bak; we signal revert
            return {"slug": slug, "trajectory": traj, "result": "reverted"}
        before = after
    return {"slug": slug, "trajectory": traj, "result": "done"}


# ---------------------------------------------------------------------------
# 3. BACK-PROPAGATION -- a new technique -> retry every matching older tool.
# ---------------------------------------------------------------------------
_TECHNIQUE_SIG = {
    "fix-build-target": re.compile(r"!<arch>|exec format|no.*main|not a main package", re.I),
    "clock-route": re.compile(r"startswith\(['\"]20\d\d|Week \d+|20\d\d-\d\d-\d\d", re.I),
    "pty-allocate": re.compile(r"tty|render|screen|interactive", re.I),
    "source-completion": re.compile(r"no matching versions|cannot find package|missing", re.I),
}


def back_propagate(technique: str, limit: int = 50) -> list[str]:
    """Given a newly-proven technique, return every non-locked tool whose latest report
    matches that technique's signature -- the 'new locks teach older tests' queue."""
    sig = _TECHNIQUE_SIG.get(technique)
    if not sig:
        return []
    hits = []
    for c in candidates():
        rep = latest_report(c["slug"])
        if not rep:
            continue
        try:
            blob = rep.read_text(encoding="utf-8", errors="replace")[:200000]
        except Exception:
            continue
        if sig.search(blob):
            hits.append(c["slug"])
        if len(hits) >= limit:
            break
    return hits


# ---------------------------------------------------------------------------
# 4. RETRAIN TRIGGER
# ---------------------------------------------------------------------------
def maybe_retrain(threshold: int = 200) -> dict:
    """Fire the flywheel retrain when enough NEW training-eligible pairs accumulate."""
    n = 0
    if BEHAVIORAL_CORPUS.exists():
        n = sum(1 for _ in BEHAVIORAL_CORPUS.open(encoding="utf-8", errors="replace"))
    ready = n >= threshold
    return {
        "behavioral_pairs": n,
        "threshold": threshold,
        "retrain_ready": ready,
        "command": "python scripts/determinex_flywheel.py"
        if ready
        else f"accumulate {threshold - n} more pairs first",
    }


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Determinex PB autonomic fan-out driver")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser(
        "plan-all", help="CPU-free diagnosis+retrieval queue over all unlocked tools"
    )
    pa.add_argument("--limit", type=int, default=30)
    pa.add_argument("--min-pct", type=float, default=0.0)
    pt = sub.add_parser("plan")
    pt.add_argument("slug")
    bp = sub.add_parser("backprop")
    bp.add_argument("technique")
    sub.add_parser("retrain-status")
    args = ap.parse_args()

    if args.cmd == "plan-all":
        cands = candidates(min_pct=args.min_pct)[: args.limit]
        print(f"=== FAN-OUT QUEUE: {len(cands)} unlocked tools (closest-to-lock first) ===")
        for c in cands:
            p = plan_tool(c["slug"])
            adj = p.get("adjudication", {})
            sugg = p.get("corpus_suggestions", [])
            fixes = [a for a in p.get("autofix_would", []) if a and not a.startswith("no ")]
            tag = (
                ("AUTOFIX:" + ";".join(f.split(":")[0] for f in fixes))
                if fixes
                else "behavioral/manual"
            )
            print(
                f"  {c['pct']:5.1f}%  {c['slug']:34s} {tag}"
                + (f"  corpus<-{[s['technique'] for s in sugg][:2]}" if sugg else "")
            )
        return 0
    if args.cmd == "plan":
        print(json.dumps(plan_tool(args.slug), indent=2))
        return 0
    if args.cmd == "backprop":
        hits = back_propagate(args.technique)
        print(f"{args.technique} back-prop -> {len(hits)} matching tools:")
        for h in hits:
            print("  ", h)
        return 0
    if args.cmd == "retrain-status":
        print(json.dumps(maybe_retrain(), indent=2))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
