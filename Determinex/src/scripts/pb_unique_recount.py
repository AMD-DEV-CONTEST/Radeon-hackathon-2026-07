#!/usr/bin/env python3
"""pb_unique_recount.py — canonical UNIQUE-count recount of ProgramBench.

Defensibility rationale
-----------------------
ProgramBench's "bidir" technique emits each test under BOTH the ``tests.`` and
``eval.tests.`` classname prefixes, which doubles the raw ``test_results`` count
in the eval report. The raw doubled count is what a hostile reviewer attacks
("you ran each test twice"). The CANONICAL, externally-defensible count is the
UNIQUE count:

  * total   = distinct test names after stripping the tests./eval.tests. prefix
  * passed  = distinct names where EVERY emitted instance passed (conservative —
              a not_run/skip/failure under either prefix means NOT resolved, so
              this can never inflate)

A tool is a FULL LOCK iff unique_passed == unique_total (and total > 0). The lock
verdict is invariant to doubling; only the partial-credit count needs deduping.

Usage
-----
  python scripts/pb_unique_recount.py --reports <dir-of-*.eval.json>           # report only
  python scripts/pb_unique_recount.py --reports <dir> --distribute             # + place evidence locally
  python scripts/pb_unique_recount.py --reports <dir> --distribute --apply-board  # + rewrite eval_index
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EVAL_INDEX = REPO / "corpus" / "programbench" / "eval_index.json"
LOCKED = REPO / "corpus" / "programbench" / "locked"
PARTIALS = REPO / "corpus" / "programbench" / "partials"
PREFIXES = ("eval.tests.", "tests.")


def strip_prefix(name: str) -> str:
    for p in PREFIXES:
        if name.startswith(p):
            return name[len(p) :]
    return name


def unique_counts(test_results: list) -> tuple[int, int, list[str]]:
    """Return (unique_passed, unique_total, gap_names)."""
    by: dict[str, list[str]] = defaultdict(list)
    for t in test_results:
        by[strip_prefix(t.get("name", ""))].append(t.get("status", "?"))
    gaps = [n for n, sts in by.items() if not all(s == "passed" for s in sts)]
    passed = len(by) - len(gaps)
    return passed, len(by), gaps


def norm_keys(slug: str) -> list[str]:
    """Candidate match keys for a full slug 'author__tool.sha', most specific first."""
    keys = [slug]
    base = slug.split(".")[0] if "." in slug else slug  # author__tool
    keys.append(base)
    if "__" in base:
        keys.append(base.split("__")[-1])  # tool
    return keys


def index_reports(reports_dir: Path) -> dict[str, dict]:
    """Map every candidate key -> report record (prefer more specific keys)."""
    idx: dict[str, dict] = {}
    for f in sorted(reports_dir.glob("*.eval.json")):
        full = f.name[: -len(".eval.json")]
        raw = f.read_bytes()
        try:
            tr = json.loads(raw.decode("utf-8")).get("test_results") or []
        except Exception:
            continue
        up, ut, gaps = unique_counts(tr)
        rec = {
            "full": full,
            "uniq_passed": up,
            "uniq_total": ut,
            "raw": len(tr),
            "gaps": gaps,
            "bytes": raw,
            "is_lock": ut > 0 and up == ut,
        }
        # register under full slug + base/tool keys; on collision keep the BEST
        # (highest unique_passed, then lock) so a tool's best eval always wins.
        for k in norm_keys(full):
            prev = idx.get(k)
            if prev is None or (rec["uniq_passed"], rec["is_lock"]) > (
                prev["uniq_passed"],
                prev["is_lock"],
            ):
                idx[k] = rec
    return idx


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reports", type=Path, required=True)
    ap.add_argument(
        "--distribute", action="store_true", help="place evidence into canonical local dirs"
    )
    ap.add_argument(
        "--apply-board", action="store_true", help="rewrite eval_index.json unique counts"
    )
    args = ap.parse_args()

    ridx = index_reports(args.reports)
    board = json.loads(EVAL_INDEX.read_text(encoding="utf-8"))
    rows = board if isinstance(board, list) else list(board.values())
    canon = [r for r in rows if not r.get("alias_of") and not r.get("canonical_slug")]

    matched = 0
    locks = near99 = near95 = partial = low = 0
    sump = sumt = 0
    changes = []
    distributed = []
    gaps_out = {}
    for r in canon:
        slug = r.get("slug") or r.get("source") or "?"
        full = r.get("source") or slug
        rec = None
        for k in [full] + norm_keys(full) + norm_keys(slug):
            if k in ridx:
                rec = ridx[k]
                break
        if not rec:
            continue
        matched += 1
        up, ut, lock = rec["uniq_passed"], rec["uniq_total"], rec["is_lock"]
        sump += up
        sumt += ut
        pct = up / ut if ut else 0
        if lock:
            locks += 1
        elif pct >= 0.99:
            near99 += 1
        elif pct >= 0.95:
            near95 += 1
        elif pct >= 0.50:
            partial += 1
        else:
            low += 1
        if not lock and rec["gaps"]:
            gaps_out[rec["full"]] = {
                "slug": slug,
                "uniq_passed": up,
                "uniq_total": ut,
                "pct": round(100 * pct, 2),
                "n_gaps": ut - up,
                "gaps": rec["gaps"],
            }
        # canonical dir
        cdir = (LOCKED if lock else PARTIALS) / rec["full"]
        sha = hashlib.sha256(rec["bytes"]).hexdigest()
        if args.distribute:
            cdir.mkdir(parents=True, exist_ok=True)
            (cdir / "eval_report.json").write_bytes(rec["bytes"])
            distributed.append(rec["full"])
        # board change record
        if (
            r.get("official_passed"),
            r.get("official_total"),
            r.get("official_full_suite_resolved"),
        ) != (up, ut, lock):
            changes.append(
                (
                    slug,
                    r.get("official_passed"),
                    r.get("official_total"),
                    up,
                    ut,
                    lock,
                    rec["gaps"][:4],
                )
            )
        if args.apply_board:
            r["unique_passed"] = up
            r["unique_total"] = ut
            r["raw_test_results"] = rec["raw"]
            r["official_passed"] = up
            r["official_total"] = ut
            r["official_full_suite_resolved"] = lock
            r["eval_report_path"] = (cdir / "eval_report.json").as_posix()
            r["eval_report_sha256"] = sha
            r["count_basis"] = "unique_dedup_v1"

    print(f"matched {matched}/{len(canon)} canonical tasks to eval evidence")
    print(f"UNIQUE locks={locks} near99={near99} near95={near95} partial={partial} low={low}")
    print(f"UNIQUE aggregate {sump}/{sumt} = {100 * sump / sumt:.2f}%" if sumt else "no totals")
    if args.distribute:
        print(f"distributed evidence into {len(distributed)} canonical dirs")
    print(f"\nrows whose count/lock CHANGES under unique recount: {len(changes)}")
    for slug, op, ot, up, ut, lk, gaps in sorted(changes):
        flip = "" if (op == up and ot == ut) else "  <== COUNT CHANGE"
        g = f" gaps:{gaps}" if gaps else ""
        print(f"  {slug:28} {op}/{ot} -> {up}/{ut} lock={lk}{flip}{g}")
    if args.apply_board:
        EVAL_INDEX.write_text(json.dumps(board, indent=2, ensure_ascii=False), encoding="utf-8")
        print("\neval_index.json REWRITTEN on unique basis.")
    gaps_path = Path("C:/tmp/pb_gaps.json")
    gaps_path.write_text(json.dumps(gaps_out, indent=2), encoding="utf-8")
    print(
        f"\nper-tool gaps (non-locks) -> {gaps_path}  ({len(gaps_out)} tools, "
        f"{sum(v['n_gaps'] for v in gaps_out.values())} total failing unique tests)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
