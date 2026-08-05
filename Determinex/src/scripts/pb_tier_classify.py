"""
pb_tier_classify.py — Assigns tier and sub_bucket to every eval_index row,
and enforces the archive-authoritative provenance law (the brotli-prevention).

Tier schema (COMPLETION ARCHITECTURE directive, 2026-06-12):
  T1  strict_lock:       status==strict_lock
  T2  ceiling_certified: fail==0 AND nr==0 AND sk>0 AND CEILING_CERT.md exists in locked dir
  T3  open:              everything else
      sub_buckets:
        near_miss          — score >= 98% OR T2 candidate (no cert yet)
        impossible_ceiling — ceiling_confirmed (proven structural ceiling < 100%)
        tui_wall           — TUI/tmux is the primary remaining blocker
        rebaseline_needed  — stale/low-data (board_cache_only) or 50-98% w/o TUI
        behavioral_deep    — score < 50% or complex behavioral failures

The reconcile law (added 2026-06-21 after brotli was re-worked while already
locked): a row's lock status is driven by GROUND TRUTH ON DISK, never by a stale
per-row field. Two directions, both provenance-gated by verified_locks.json:

  PROMOTE  — a verified task (in verified_locks.json) that has a PERFECT locked
             archive (passed==total, 0 fail/nr/sk) but whose row is not yet
             strict_lock is promoted from that archive. (fixes brotli: archive
             1212/1212 since Jun 15, row stuck at board_cache_only 42/955.)
  DEMOTE   — a row claiming strict_lock whose task is NOT in verified_locks.json
             is demoted to status 'unverified_lock'. (fixes yj/svd2rust: the
             2026-06-19 CANON AUDIT proved they pass via answer-key binaries.)

verified_locks.json is the sha-pinned provenance registry maintained by
determinex_pb_lock_registry.py — "archive is 100%" alone never promotes, or the
demoted fakes would silently return.

Usage:
    python scripts/pb_tier_classify.py [--dry-run] [--report]
    python scripts/pb_tier_classify.py --guard   # CI: exit 1 if any row drifts
                                                  # from archive/provenance truth
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).parent.parent
INDEX = REPO_ROOT / "corpus" / "programbench" / "eval_index.json"
LOCKED = REPO_ROOT / "corpus" / "programbench" / "locked"
VERIFIED = REPO_ROOT / "corpus" / "programbench" / "verified_locks.json"

# Subdirs under locked/ that are tier buckets (their children are per-tool dirs)
# or quarantine — handled specially / skipped by the flat archive scan.
_LOCKED_TIER_SUBDIRS = {"tier_1_perfect", "tier_2_upstream_skips"}
_LOCKED_SKIP_SUBDIRS = {"_superseded"}

TUI_KEYWORDS = {
    "tmux",
    "tui_wall",
    "libtmux",
    "tui test",
    "tui_cap",
    "factory_accepted_tui_cap",
    "tui-ceiling",
    "tmux_session",
    "test_tui",
    "test_tmux",
}


# ── Canonical join + ground-truth sources for the reconcile law ────────────


def short_name(slug: str) -> str:
    """Canonical join key: 'multiprocessio__dsq.c3ae0ba' -> 'dsq', 'jq_native' -> 'jq'.

    This is the same short-name join pb_build_index.py uses to unify a tool's
    short slug, owner__repo.hash slug, and _native/_model variants.
    """
    s = slug
    if "__" in s:
        s = s.split("__", 1)[1]
    s = s.split(".")[0]
    s = re.sub(r"_(native|model)$", "", s)
    return s.lower()


def load_verified_short() -> set[str]:
    """Short names of every provenance-verified lock in verified_locks.json."""
    try:
        d = json.loads(VERIFIED.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    return {short_name(k) for k in d.get("locks", {})}


def _counts_from_report(path: pathlib.Path) -> tuple[int, int, int, int, int] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None
    tr = data.get("test_results")
    if not isinstance(tr, list):
        return None
    c = collections.Counter(r.get("status") for r in tr)
    total = len(tr)
    passed = c.get("passed", 0)
    failed = c.get("failure", 0) + c.get("failed", 0) + c.get("error", 0)
    not_run = c.get("not_run", 0)
    skipped = c.get("skipped", 0)
    return (passed, total, failed, not_run, skipped)


def scan_archive_best() -> dict[str, tuple[tuple[int, int, int, int, int], pathlib.Path]]:
    """short_name -> (best_counts, report_path) under locked/.

    best_counts = (passed,total,fail,nr,sk). 'Best' = the perfect archive if any
    exists, else the one with most passes. Walks flat locked/<tool>/ dirs plus the
    tier_1_perfect/ and tier_2_upstream_skips/ bucket children. Skips _superseded/.
    """
    best: dict[str, tuple[tuple[int, int, int, int, int], pathlib.Path]] = {}

    def consider(dir_name: str, report: pathlib.Path) -> None:
        counts = _counts_from_report(report)
        if not counts or counts[1] == 0:
            return
        sn = short_name(dir_name)
        cur = best.get(sn)
        p = counts[0]
        perfect = counts[0] == counts[1] and counts[2] == 0 and counts[3] == 0 and counts[4] == 0
        if cur is None:
            best[sn] = (counts, report)
            return
        cur_counts = cur[0]
        cur_perfect = (
            cur_counts[0] == cur_counts[1]
            and cur_counts[2] == 0
            and cur_counts[3] == 0
            and cur_counts[4] == 0
        )
        # Tiebreaker when both are equally-perfect with equal passes: prefer the
        # canonical owner__repo.hash dir name (matches the verified_locks key form)
        # over a bare short alias, so backfills point at the provenance-pinned copy.
        canonical = bool(re.search(r"__.+\.[0-9a-f]{7,8}$", report.parent.name))
        cur_canonical = bool(re.search(r"__.+\.[0-9a-f]{7,8}$", best[sn][1].parent.name))
        if (
            (perfect and not cur_perfect)
            or (perfect == cur_perfect and p > cur_counts[0])
            or (perfect == cur_perfect and p == cur_counts[0] and canonical and not cur_canonical)
        ):
            best[sn] = (counts, report)

    if not LOCKED.exists():
        return best
    for d in LOCKED.iterdir():
        if not d.is_dir() or d.name in _LOCKED_SKIP_SUBDIRS:
            continue
        if d.name in _LOCKED_TIER_SUBDIRS:
            for child in d.iterdir():
                if child.is_dir() and (child / "eval_report.json").exists():
                    consider(child.name, child / "eval_report.json")
            continue
        rep = d / "eval_report.json"
        if rep.exists():
            consider(d.name, rep)
    return best


def reconcile_from_archive(
    entries: list[dict], verified_short: set[str], archive_best: dict[str, tuple]
) -> list[tuple[str, str]]:
    """Apply the archive-authoritative provenance law in-place.

    Returns a list of (slug, human_description) for every change made.
    """
    changes: list[tuple[str, str]] = []
    for e in entries:
        if e.get("alias_of") or e.get("canonical_slug"):
            continue
        sn = short_name(e.get("slug", ""))
        verified = sn in verified_short
        arch = archive_best.get(sn)
        status = e.get("status", "")

        # PROMOTE: verified task with a perfect archive that isn't marked locked.
        #
        # 2026-07-02 fix (found during a corpus-center audit): "verified" in
        # verified_locks.json means SCORE-verified only -- its own note says
        # "cache-cleared archive eval, passed==total, tarball sha pinned." It
        # says nothing about provenance (real reimplementation vs. upstream
        # copy). status == "needs_reverify" is a DELIBERATE hold, distinct
        # from the stale board_cache_only case this rule was built for
        # (brotli: archive 1212/1212 since Jun 15, row stuck at a stale
        # cached score). Three rows (chmln__handlr, isona__dirble, ngrrram)
        # are score-perfect AND in verified_locks.json AND explicitly held at
        # needs_reverify because the 2026-06-30 provenance audit could not
        # confirm they're genuine reimplementations ("not positively
        # confirmed as upstream, but also not verified as a genuine native
        # reimplementation... needs manual reverify"). Auto-promoting them to
        # strict_lock here would silently re-introduce exactly the
        # overclaiming that audit corrected. needs_reverify must never be an
        # auto-promote target -- only a human clearing the provenance
        # question should move a row out of it.
        if verified and arch and status != "needs_reverify":
            (p, t, f, nr, sk), report_path = arch
            archive_perfect = t > 0 and p == t and f == 0 and nr == 0 and sk == 0
            if archive_perfect and status != "strict_lock":
                changes.append(
                    (
                        e["slug"],
                        f"PROMOTE {status or '∅'} -> strict_lock (verified archive {p}/{t})",
                    )
                )
                e["official_passed"] = p
                e["official_total"] = t
                e["official_failed"] = 0
                e["official_not_run"] = 0
                e["official_skipped"] = 0
                e["official_score_pct"] = 100.0
                e["status"] = "strict_lock"
                e["eval_report_path"] = str(report_path)
                e["reconciled_from_archive"] = sn
                e["reconcile_note"] = (
                    "archive-authoritative promote: verified_locks + perfect "
                    "locked archive (pb_tier_classify reconcile law)"
                )
                status = "strict_lock"

        # DEMOTE: claims strict_lock but is NOT provenance-verified.
        if status == "strict_lock" and not verified:
            changes.append(
                (
                    e["slug"],
                    "DEMOTE strict_lock -> unverified_lock (absent from verified_locks.json)",
                )
            )
            e["status"] = "unverified_lock"
            e["unverified_lock"] = True
            e["reconcile_note"] = (
                "demoted: not in verified_locks.json — provenance unproven "
                "(CANON AUDIT / pb_tier_classify reconcile law)"
            )

        # BACKFILL: a verified perfect lock must always link to its archive so the
        # README/eval trace is never orphaned (e.g. a freshly promoted brotli).
        if e.get("status") == "strict_lock" and verified and arch:
            (p, t, f, nr, sk), report_path = arch
            rp = e.get("eval_report_path") or ""
            archive_perfect = t > 0 and p == t and f == 0 and nr == 0 and sk == 0
            if archive_perfect and (not rp or not pathlib.Path(rp).exists()):
                e["eval_report_path"] = str(report_path)
                changes.append((e["slug"], "BACKFILL eval_report_path -> archive"))
    return changes


def _has_cert(entry: dict) -> bool:
    """True if a CEILING_CERT.md exists in the locked archive for this tool."""
    source = entry.get("source", "") or ""
    # source can be a full slug like chmln__handlr.90e78ba or a path alias
    slug = entry.get("slug", "") or ""
    for candidate in [source, slug]:
        if candidate:
            cert = LOCKED / candidate / "CEILING_CERT.md"
            if cert.exists():
                return True
    # also check the archive dir that eval_report_path actually points at
    # (e.g. locked/tier_2_upstream_skips/<slug>/), so a cert lives WITH its archive
    rp = entry.get("eval_report_path") or ""
    if rp:
        cert = pathlib.Path(rp).parent / "CEILING_CERT.md"
        if cert.exists():
            return True
    return False


def _tui_signal(entry: dict) -> bool:
    corpus = " ".join(
        str(entry.get(k) or "")
        for k in (
            "notes",
            "failure_class",
            "factory_note",
            "ceiling_note",
            "hetzner_eval_note",
            "next_action",
        )
    ).lower()
    return any(kw in corpus for kw in TUI_KEYWORDS)


def classify(entry: dict) -> tuple[str, str | None]:
    """Return (tier_value, sub_bucket_or_None)."""
    status = entry.get("status", "")

    # T1
    if status == "strict_lock":
        return "strict_lock", None

    fail = int(entry.get("official_failed", 0) or 0)
    nr = int(entry.get("official_not_run", 0) or 0)
    sk = int(entry.get("official_skipped", 0) or 0)
    passed = int(entry.get("official_passed", 0) or 0)
    total = int(entry.get("official_total", 0) or 0)

    # T2 check
    if fail == 0 and nr == 0 and sk > 0 and _has_cert(entry):
        return "ceiling_certified", None

    # T3 — assign sub_bucket

    # TUI signal takes priority over ceiling_confirmed: a tool blocked only by tmux/TUI
    # is not truly "impossible" — it's fixable if the eval environment gains tmux support.
    if _tui_signal(entry):
        return "open", "tui_wall"

    # Impossible ceiling: proven structural failures that can never reach 100%
    if status in ("ceiling_confirmed", "impossible_ceiling"):
        return "open", "impossible_ceiling"

    # T2 candidate without cert yet → near_miss (first in line for T2 sweep)
    if fail == 0 and nr == 0 and sk > 0:
        return "open", "near_miss"

    # Score-based classification
    ratio = passed / total if total > 0 else 0.0
    score_pct = entry.get("official_score_pct", None)
    if score_pct is not None:
        ratio = score_pct / 100.0

    # board_cache_only always needs a fresh mechanical pass regardless of stale score
    if status == "board_cache_only":
        return "open", "rebaseline_needed"

    if ratio >= 0.98:
        return "open", "near_miss"
    elif ratio >= 0.50:
        return "open", "rebaseline_needed"
    elif ratio > 0:
        return "open", "behavioral_deep"

    # No eval data: submetric_claim, reference_parity, unknown
    if status in ("submetric_claim", "reference_parity"):
        return "open", "rebaseline_needed"

    return "open", "behavioral_deep"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing")
    parser.add_argument("--report", action="store_true", help="Print tier distribution summary")
    parser.add_argument(
        "--guard",
        action="store_true",
        help="CI mode: detect (never write) any row that drifts "
        "from archive/provenance truth; exit 1 if drift found",
    )
    args = parser.parse_args()

    raw = INDEX.read_text(encoding="utf-8")
    data = json.loads(raw)
    entries = data if isinstance(data, list) else list(data.values())

    # ── Reconcile law: archive + provenance are authoritative over stale fields.
    verified_short = load_verified_short()
    archive_best = scan_archive_best()
    reconcile_changes = reconcile_from_archive(entries, verified_short, archive_best)

    if args.guard:
        if reconcile_changes:
            print(
                "DRIFT DETECTED — eval_index.json disagrees with the locked "
                "archives / verified_locks.json:"
            )
            for slug, desc in reconcile_changes:
                print(f"  {slug}: {desc}")
            print(
                f"\n{len(reconcile_changes)} drifting row(s). "
                "Run `python scripts/pb_tier_classify.py` to reconcile."
            )
            sys.exit(1)
        print(
            "Guard OK: every lock row matches its locked archive + verified_locks.json (0 drift)."
        )
        sys.exit(0)

    if reconcile_changes and (args.dry_run or args.report):
        print(
            f"\nReconcile law — {len(reconcile_changes)} row(s) corrected from archive/provenance:"
        )
        for slug, desc in reconcile_changes:
            print(f"  {slug}: {desc}")

    from collections import Counter

    tier_counts: Counter[str] = Counter()
    bucket_counts: Counter[str] = Counter()
    changed = 0

    for entry in entries:
        if entry.get("alias_of") or entry.get("canonical_slug"):
            # Alias rows: propagate T1 if they alias a strict_lock
            continue

        tier, bucket = classify(entry)
        old_tier = entry.get("tier")
        old_bucket = entry.get("sub_bucket")

        if old_tier != tier or old_bucket != bucket:
            changed += 1
            if args.dry_run:
                slug = entry.get("slug", "?")
                print(
                    f"  {slug}: tier {old_tier!r} -> {tier!r}, bucket {old_bucket!r} -> {bucket!r}"
                )

        entry["tier"] = tier
        if bucket is not None:
            entry["sub_bucket"] = bucket
        elif "sub_bucket" in entry:
            del entry["sub_bucket"]

        tier_counts[tier] += 1
        bucket_counts[bucket or tier] += 1

    if args.report or args.dry_run:
        canonical = [e for e in entries if not e.get("alias_of") and not e.get("canonical_slug")]
        print(f"\nTier distribution ({len(canonical)} canonical rows):")
        print(f"  T1 strict_lock:       {tier_counts['strict_lock']}")
        print(f"  T2 ceiling_certified: {tier_counts['ceiling_certified']}")
        t3 = tier_counts["open"]
        print(f"  T3 open:              {t3}")
        print(f"    near_miss:          {bucket_counts['near_miss']}")
        print(f"    impossible_ceiling: {bucket_counts['impossible_ceiling']}")
        print(f"    tui_wall:           {bucket_counts['tui_wall']}")
        print(f"    rebaseline_needed:  {bucket_counts['rebaseline_needed']}")
        print(f"    behavioral_deep:    {bucket_counts['behavioral_deep']}")
        total = sum(tier_counts.values())
        print(f"  TOTAL:                {total} (must be 200)")
        print(f"\nRows changed: {changed}")

    if not args.dry_run:
        INDEX.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote eval_index.json ({changed} rows updated).")


if __name__ == "__main__":
    main()
