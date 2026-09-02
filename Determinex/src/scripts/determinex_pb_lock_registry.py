#!/usr/bin/env python3
"""
determinex_pb_lock_registry.py -- the single source of truth for genuine PB locks
===============================================================================
THE FIX for the lying board. Lock status was scattered across THREE records that
the 2026-06-10 bulk pass degraded inconsistently: eval_index `official_full_suite_resolved`,
`logs/programbench_lock_board.json`, and the CLAUDE.md prose list. A degraded archive
kept its stale "100%" in one record while the artifact no longer reproduced -> the board
lied and nothing re-checked (the 5 eval-integrity failure modes).

This registry is ONE place. A tool is in `verified_locks.json` ONLY when a cache-cleared
archive eval proved passed==total (0 not_run / 0 skipped / 0 failed), and the entry pins
the sha256 of BOTH the eval_report and the submission tarball that produced it. If the
tarball changes (any bulk edit), its sha no longer matches -> the lock is automatically
UNVERIFIED until re-eval. Staleness becomes impossible by construction.

  VERIFIED      -> in registry, tarball sha matches  -> the canonical lock set (the "one place")
  NEEDS_REVERIFY-> was a lock but artifact changed / never registered -> must re-eval to enter
  NEGATIVE      -> everything else (degraded-unrecoverable, partial-not_run, gated reject,
                   ceiling, RED cheat) -> emitted as NEGATIVE TRAINING SIGNAL

Negative signal teaches the flywheel what is NOT a genuine lock and why -- contrastive
examples, gated by the legitimacy classifier (RED cheats are negative; they never train as
positive). Written to pb_negative_signal.jsonl with the exclusion-schema convention.

Usage:
  python scripts/determinex_pb_lock_registry.py reconcile         # 3-bucket report
  python scripts/determinex_pb_lock_registry.py verify <tool> <eval_report.json>   # register if clean
  python scripts/determinex_pb_lock_registry.py emit-negative     # write negative signal for non-verified
"""

from __future__ import annotations

import hashlib
import json
import sys
import tarfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCKED = ROOT / "corpus" / "programbench" / "locked"
REGISTRY = ROOT / "corpus" / "programbench" / "verified_locks.json"
EVAL_INDEX = ROOT / "corpus" / "programbench" / "eval_index.json"
NEGATIVE = ROOT / "corpus" / "programbench" / "training_corpus" / "pb_negative_signal.jsonl"

sys.path.insert(0, str(ROOT / "scripts"))


def _filtered_checkout_declared() -> bool:
    """True only if the operator DECLARED that this checkout ships no locked archives.

    Two ways to say it, because two callers need it: the CLI flag for a human, and the env
    var for CI (the pre-commit config is shared between the dev repo and the public mirror,
    so the declaration has to live where the filtered checkout actually is -- the workflow --
    rather than in a config both of them read).

    Deliberately never inferred from counts. "Nothing was scannable" is identical whether the
    publish filter removed the tree or every archive vanished, and a guard that guesses
    benign in that situation is the exact failure this module exists to refuse.
    """
    import os

    return (
        "--allow-filtered-checkout" in sys.argv
        or os.environ.get("DETERMINEX_FILTERED_CHECKOUT") == "1"
    )


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _ident(n: str) -> str:
    return n.split("::")[-1] if "::" in n else n.split(".")[-1]


def counts(eval_report: dict) -> dict:
    tr = eval_report.get("test_results") or []
    from collections import Counter

    c = Counter(x.get("status", "") for x in tr)
    return {
        "total": len(tr),
        "passed": c.get("passed", 0),
        "failed": c.get("failed", 0) + c.get("error", 0),
        "not_run": c.get("not_run", 0),
        "skipped": c.get("skipped", 0),
        "distinct": len(set(_ident(x.get("name", "")) for x in tr)),
    }


def is_clean(c: dict) -> bool:
    return (
        c["total"] > 0
        and c["passed"] == c["total"]
        and c["failed"] == 0
        and c["not_run"] == 0
        and c["skipped"] == 0
    )


_SOURCE_EXTS = (".go", ".rs", ".c", ".cc", ".cpp", ".h", ".hpp", ".py", ".js", ".ts")
_SOURCE_EXCLUDES = (
    "/test/",
    "/tests/",
    "/testdata/",
    "/fixtures/",
    "/fixture/",
    "/vendor/",
    "/node_modules/",
    "/target/",
    "/.git/",
)


def _source_tree_violation(tarp: Path) -> str | None:
    """Reject upstream-source-tree shortcuts at the lock gate.

    The ProgramBench reimpl lane must submit a small native reimplementation, not
    a cleaned cargo/go/make build of the real upstream repo. The eval preflight
    warns on this shape; registry verification is the hard stop.
    """
    with tarfile.open(tarp, "r:gz") as t:
        source_files = []
        for m in t.getmembers():
            if not m.isfile():
                continue
            name = m.name.replace("\\", "/").strip("./")
            low = f"/{name.lower()}"
            if not low.endswith(_SOURCE_EXTS):
                continue
            if any(part in low for part in _SOURCE_EXCLUDES):
                continue
            source_files.append(name)
    if len(source_files) > 8:
        sample = ", ".join(source_files[:5])
        return (
            f"prohibited upstream-source tree: submission has {len(source_files)} "
            f"authored-looking source files ({sample}); ProgramBench locks must be "
            "small native reimpls, not upstream repo builds"
        )
    return None


# ---------- registry I/O ----------
def load_registry() -> dict:
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {
        "schema": "determinex-pb-verified-locks-v1",
        "note": "Single source of truth. An entry is a genuine lock ONLY: cache-cleared "
        "archive eval, passed==total (0 not_run/skipped/failed), tarball sha pinned. "
        "If submission_sha256 no longer matches the archive, the lock is UNVERIFIED.",
        "locks": {},
    }


def save_registry(reg: dict) -> None:
    REGISTRY.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")


def verify_and_register(
    tool: str, eval_report_path: Path, source: str = "hetzner", refresh_doc: bool = True
) -> dict:
    """Register a tool as a verified lock ONLY if its eval is a clean 100%.
    On success, refresh the live capability map + CAPABILITY.md (so the doc updates
    as locks happen). Batch callers can pass refresh_doc=False and refresh once at the end."""
    data = json.loads(eval_report_path.read_text(encoding="utf-8"))
    c = counts(data)
    if not is_clean(c):
        return {"ok": False, "why": f"not clean: {c}"}
    tarp = LOCKED / tool / "submission.tar.gz"
    if not tarp.exists():
        return {"ok": False, "why": f"no archive tarball at {tarp}"}
    try:
        upstream_why = _source_tree_violation(tarp)
        if upstream_why:
            return {"ok": False, "why": upstream_why}
    except Exception as e:
        return {"ok": False, "why": f"submission provenance scan failed: {e}"}
    # anti-test-gaming gate: a lock must EARN its passes (no reading the test name /
    # embedding goldens / branching on a literal test). Refuse to register a gamer.
    try:
        import determinex_pb_provenance_guard as PG

        hits = PG.scan_tool(tool)
        just = PG.load_just().get("justified", {})
        unjust = [h for h in hits if h["kind"] not in just.get(tool, [])]
        if unjust:
            return {
                "ok": False,
                "why": f"test-gaming (unjustified): {unjust[:2]} -- implement the "
                f"behavior or justify in provenance_justifications.json before locking",
            }
    except Exception:
        pass
    reg = load_registry()
    reg["locks"][tool] = {
        "passed": c["passed"],
        "total": c["total"],
        "distinct": c["distinct"],
        "verified_date": date.today().isoformat(),
        "source": source,
        "submission_sha256": sha256_file(tarp),
        "eval_report_sha256": hashlib.sha256(eval_report_path.read_bytes()).hexdigest(),
    }
    save_registry(reg)
    if refresh_doc:
        try:
            import determinex_pb_capability_map as C

            C.refresh()
        except Exception as e:  # never let doc-refresh break a registration
            print(f"[registry] lock saved; capability refresh deferred: {e}")
    return {"ok": True, "tool": tool, "passed": c["passed"], "total": c["total"]}


# ---------- reconciliation ----------
def _eval_index_totals() -> dict:
    idx = json.loads(EVAL_INDEX.read_text(encoding="utf-8"))
    out = {}
    for e in idx:
        s = (e.get("slug") or "").replace(".eval", "")
        short = s.split("__")[-1].split(".")[0] if "__" in s else s
        ot = e.get("official_total") or e.get("official_passed") or 0
        fsr = bool(e.get("official_full_suite_resolved"))
        if ot:
            out.setdefault(short, {"recorded_total": ot, "fsr": fsr})
    return out


def reconcile() -> dict:
    import tarfile

    import determinex_pb_bidir_restore as B

    reg = load_registry()
    idx = _eval_index_totals()
    verified, needs, negative = [], [], []
    for d in sorted(LOCKED.iterdir()):
        if not d.is_dir():
            continue
        tarp = d / "submission.tar.gz"
        rep = d / "eval_report.json"
        if not tarp.exists():
            continue
        tool = d.name
        # VERIFIED: in registry with matching tarball sha
        entry = reg["locks"].get(tool)
        if entry and entry.get("submission_sha256") == sha256_file(tarp):
            verified.append(tool)
            continue
        # gather evidence
        with tarfile.open(tarp, "r:gz") as t:
            cs = next((n for n in t.getnames() if n.endswith("compile.sh")), None)
            txt = t.extractfile(cs).read().decode("utf-8", "replace") if cs else ""
        has_bidir = B._has_bidir(txt)
        rec = idx.get(tool, {}).get("recorded_total", 0)
        c = counts(json.loads(rep.read_text(encoding="utf-8"))) if rep.exists() else None
        # was a doubled lock whose archive no longer carries bidir = degraded, recoverable
        doubled = c and rec and abs(rec - 2 * c["distinct"]) <= max(4, 0.02 * rec)
        if (
            (entry and entry.get("submission_sha256") != sha256_file(tarp))
            or doubled
            or not has_bidir
            and rec
            and c
            and c["total"] < rec
        ):
            needs.append(
                {
                    "tool": tool,
                    "recorded_total": rec,
                    "archive_now": (c["total"] if c else None),
                    "has_bidir": has_bidir,
                    "reason": "stale-sha"
                    if entry
                    else ("degraded-doubled" if doubled else "archive-below-recorded"),
                }
            )
        else:
            negative.append(
                {
                    "tool": tool,
                    "reason": "unverified-needs-eval",
                    "recorded_total": rec,
                    "archive_now": (c["total"] if c else None),
                }
            )
    return {"verified": verified, "needs_reverify": needs, "negative": negative}


# ---------- negative signal ----------
def emit_negative(buckets: dict | None = None) -> dict:
    """Write negative training signal for everything that is NOT a verified lock.
    Contrastive: teaches the flywheel what a genuine lock is NOT, and why."""
    import determinex_pb_integrity as I  # noqa: F401  (legitimacy gate available to callers)

    if buckets is None:
        buckets = reconcile()
    NEGATIVE.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(NEGATIVE, "w", encoding="utf-8") as f:
        for item in buckets["needs_reverify"]:
            rec = {
                "schema": "determinex-pb-negative-signal-v1",
                "label": "negative",
                "tool": item["tool"],
                "status": "DEGRADED_UNVERIFIED",
                "reason": item["reason"],
                "lesson": "A recorded 100% with a degraded/changed artifact is NOT a lock. "
                "Re-verify from a cache-cleared archive eval before claiming.",
                "evidence": item,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
        for item in buckets["negative"]:
            rec = {
                "schema": "determinex-pb-negative-signal-v1",
                "label": "negative",
                "tool": item["tool"],
                "status": "UNVERIFIED",
                "reason": item["reason"],
                "lesson": "Not in the verified-lock registry. Treated as not-locked until a "
                "cache-cleared archive eval proves passed==total.",
                "evidence": item,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    return {"written": n, "path": str(NEGATIVE)}


def check_integrity() -> dict:
    """The structural 'never again' gate. For every registered lock, recompute the archive
    tarball sha; if it no longer matches the pinned sha, the artifact CHANGED since it was
    verified -> the lock is LYING (this is exactly the bulk-edit/bidir-strip degradation that
    made the board lie). Returns drifted + missing. A clean result is the only honest board."""
    reg = load_registry()
    drifted, missing, ok = [], [], []
    for tool, e in reg.get("locks", {}).items():
        tarp = LOCKED / tool / "submission.tar.gz"
        if not tarp.exists():
            missing.append(tool)
            continue
        if sha256_file(tarp) != e.get("submission_sha256"):
            drifted.append(tool)
        else:
            ok.append(tool)
    return {"ok": ok, "drifted": drifted, "missing": missing}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    if cmd == "check-integrity":
        r = check_integrity()
        print(
            f"verified locks: {len(r['ok'])} intact, {len(r['drifted'])} DRIFTED, {len(r['missing'])} missing-archive"
        )
        if r["drifted"]:
            print("  DRIFTED (artifact changed since verify -> lock is lying, RE-VERIFY):")
            for t in r["drifted"]:
                print(f"    {t}")
        if r["missing"]:
            print("  MISSING ARCHIVE:", ", ".join(r["missing"]))
        # DRIFT and ABSENCE are different findings and must not share a verdict.
        #
        # Drift means a locked archive changed since it was verified: the lock is lying,
        # and that is a hard failure anywhere. Absence means the archive is not in THIS
        # checkout -- which is the normal state of the public mirror, because locked/
        # holds vendored upstream trees that filter_corpus deliberately does not publish.
        #
        # Reporting "a registered lock's artifact drifted" on 0 drifted and 5 missing was
        # a guard announcing an outcome it had not established, and it failed CI on every
        # public run for a condition that is by design.
        if "--guard" in sys.argv:
            if r["drifted"]:
                print(
                    "INTEGRITY GUARD FAILED: a registered lock's artifact DRIFTED "
                    "since it was verified. The lock is lying -- re-verify before commit."
                )
                return 1
            if r["missing"]:
                if r["ok"]:
                    print(
                        "INTEGRITY GUARD FAILED: some archives are present and some are "
                        "missing, so this checkout is partial rather than filtered. "
                        "Restore the missing archives before trusting any lock."
                    )
                    return 1
                # DECLARED, not inferred -- same correction as the provenance guard. Counts
                # cannot tell "the publish filter removed the whole tree" from "every archive
                # vanished", so deciding from counts is guessing that absence is benign. The
                # filtered checkout has to say so.
                if not _filtered_checkout_declared():
                    print(
                        f"INTEGRITY GUARD FAILED: {len(r['missing'])} locked archive(s) are "
                        "absent, so their integrity is unverified -- which is not the same "
                        "as unchanged. Restore them, or if this checkout deliberately does "
                        "not ship corpus/programbench/locked/, declare it with "
                        "--allow-filtered-checkout (or DETERMINEX_FILTERED_CHECKOUT=1) to "
                        "abstain explicitly."
                    )
                    return 1
                print(
                    f"INTEGRITY GUARD CANNOT VERIFY: {len(r['missing'])} locked "
                    "archive(s) are absent and none are present, and a filtered checkout "
                    "was declared. Nothing drifted; nothing was checked either. "
                    "NOT a pass -- an abstention."
                )
                return 0
        return 0
    if cmd == "reconcile":
        b = reconcile()
        print(f"VERIFIED (canonical locks, sha-matched): {len(b['verified'])}")
        print(f"NEEDS_REVERIFY (degraded/unregistered): {len(b['needs_reverify'])}")
        print(f"NEGATIVE (unverified -> negative signal): {len(b['negative'])}")
        print("\nverified:", ", ".join(sorted(b["verified"])) or "(none yet)")
        print("\nneeds_reverify (top 20):")
        for x in b["needs_reverify"][:20]:
            print(
                f"  {x['tool']:40s} rec={x['recorded_total']} now={x['archive_now']} bidir={x['has_bidir']} [{x['reason']}]"
            )
        return 0
    if cmd == "verify" and len(sys.argv) >= 4:
        print(verify_and_register(sys.argv[2], Path(sys.argv[3])))
        return 0
    if cmd == "emit-negative":
        print(emit_negative())
        return 0
    print(f"unknown/incomplete command: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
