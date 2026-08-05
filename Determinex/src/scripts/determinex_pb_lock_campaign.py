#!/usr/bin/env python3
"""
determinex_pb_lock_campaign.py -- the production line: drive every PB tool to a CLEAN LOCK
========================================================================================
RULE (operator, 2026-06-15): the line does NOT advance until everything is a clean lock.
Each tool is driven to passed==total (0 not_run / 0 skipped / 0 failed) and registered in
verified_locks.json (sha-pinned), or proven a genuine ceiling via the adjudicator.

Strategy (fastest/easiest first -- learned from cmatrix & fzf):
  TIER 1  eval-as-is (cache-cleared). Many "degraded" tools are only STALE RECORDS, not
          degraded artifacts (cmatrix: 769/769 as-is). Register the clean ones immediately.
          NEVER pre-modify -- fzf showed blind bidir over-mirrors a tool that already routes
          prefixes via nodeid (4144/4239 + skips). As-is is the safe, high-yield first pass.
  TIER 2  diagnose the not-clean set per failure shape:
            - prefix-dupe not_run AND no nodeid-route/bidir present  -> restore bidir
            - build/setup/behavioral failure                          -> autofix patterns
          re-eval; register if clean.
  TIER 3  UNLOCKED_WORKING (no archive): pack best working copy -> eval -> autofix loop.

This module builds the WORK LIST + authoritative slug map. The eval loop runs on the heavy
box (Hetzner) via `emit-driver`; results are registered locally via determinex_pb_lock_registry.

Usage:
  python scripts/determinex_pb_lock_campaign.py worklist            # manifest of non-PROVEN tools
  python scripts/determinex_pb_lock_campaign.py emit-driver <out.sh>  # Hetzner triage loop script
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCKED = ROOT / "corpus" / "programbench" / "locked"
OVERRIDES = ROOT / "corpus" / "programbench" / "per_tool_overrides"
EVAL_INDEX = ROOT / "corpus" / "programbench" / "eval_index.json"
MANIFEST = ROOT / "logs" / "programbench_factory" / "lock_campaign_worklist.json"
sys.path.insert(0, str(ROOT / "scripts"))


def _base(slug: str) -> str:
    s = (slug or "").replace(".eval", "")
    return s.split("__")[-1].split(".")[0] if "__" in s else s


def _authoritative_slugs() -> dict[str, str]:
    """base tool -> full task slug (author__tool.hash). per_tool_overrides dir names are
    the authoritative task identifiers PB expects in the pilot dir."""
    out: dict[str, str] = {}
    if OVERRIDES.exists():
        for d in sorted(OVERRIDES.iterdir()):
            if d.is_dir() and "__" in d.name:
                out.setdefault(_base(d.name), d.name)
    # fall back to eval_index full slugs
    idx = json.loads(EVAL_INDEX.read_text(encoding="utf-8"))
    for e in idx:
        s = (e.get("slug") or "").replace(".eval", "")
        if "__" in s and not s.endswith("_native"):
            out.setdefault(_base(s), s)
    return out


def _locked_archive(base: str, slug: str) -> Path | None:
    for cand in (base, slug):
        p = LOCKED / cand / "submission.tar.gz"
        if p.exists():
            return p
    # by base-name scan
    for d in LOCKED.iterdir():
        if d.is_dir() and _base(d.name) == base and (d / "submission.tar.gz").exists():
            return d / "submission.tar.gz"
    return None


def build_worklist() -> list[dict]:
    import determinex_pb_lock_registry as R

    reg = R.load_registry()
    verified = set(reg.get("locks", {}).keys())
    slugs = _authoritative_slugs()

    idx = json.loads(EVAL_INDEX.read_text(encoding="utf-8"))
    bases = {}
    for e in idx:
        s = (e.get("slug") or "").replace(".eval", "")
        if not s or s.endswith("_native"):
            continue
        bases.setdefault(_base(s), True)

    work = []
    for base in sorted(bases):
        if base in verified:
            continue
        slug = slugs.get(base, base)
        arch = _locked_archive(base, slug)
        ov = None
        for cand in (slug, base):
            d = OVERRIDES / cand
            if (d / "compile.sh").exists():
                ov = d
                break
        if ov is None:
            for d in OVERRIDES.iterdir():
                if d.is_dir() and _base(d.name) == base and (d / "compile.sh").exists():
                    ov = d
                    break
        work.append(
            {
                "base": base,
                "slug": slug,
                "tier": "1-as-is" if arch else ("3-pack" if ov else "blocked-no-artifact"),
                "archive": str(arch.relative_to(ROOT)) if arch else None,
                "override": str(ov.relative_to(ROOT)) if ov else None,
                "author": slug.split("__")[0] if "__" in slug else base,
            }
        )
    return work


def register_results(results_jsonl: Path, clean_jsons_dir: Path) -> dict:
    """Register every CLEAN tool from a batch results.jsonl, copying its eval_report into the
    archive dir, then refresh the live capability doc ONCE. Drives tier promotion."""
    import shutil

    import determinex_pb_lock_registry as R

    registered, skipped = [], []
    for line in results_jsonl.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or '"DONE"' in line:
            continue
        d = json.loads(line)
        if not d.get("clean"):
            skipped.append(d.get("slug"))
            continue
        slug = d["slug"]
        base = _base(slug)
        # find the archive dir (by base or slug)
        arch_dir = next((LOCKED / c for c in (base, slug) if (LOCKED / c).is_dir()), None)
        if arch_dir is None:
            for dd in LOCKED.iterdir():
                if dd.is_dir() and _base(dd.name) == base:
                    arch_dir = dd
                    break
        ej = clean_jsons_dir / f"{slug}.eval.json"
        if arch_dir is None or not ej.exists():
            skipped.append(slug)
            continue
        shutil.copy(ej, arch_dir / "eval_report.json")  # refresh degraded report to clean
        res = R.verify_and_register(arch_dir.name, arch_dir / "eval_report.json", refresh_doc=False)
        (registered if res.get("ok") else skipped).append(arch_dir.name)
    # refresh the live capability map + doc ONCE after the whole batch
    try:
        import determinex_pb_capability_map as C

        C.refresh()
    except Exception as e:
        print(f"[campaign] registered; capability refresh deferred: {e}")
    return {"registered": registered, "skipped": skipped}


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "register-batch":
        out = register_results(Path(sys.argv[2]), Path(sys.argv[3]))
        print(
            f"registered {len(out['registered'])} new locks: {', '.join(sorted(out['registered']))}"
        )
        print(f"not-clean / skipped: {len(out['skipped'])}")
        return 0
    if len(sys.argv) >= 2 and sys.argv[1] == "worklist":
        work = build_worklist()
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps(work, indent=2), encoding="utf-8")
        from collections import Counter

        tiers = Counter(w["tier"] for w in work)
        print(f"worklist -> {MANIFEST}")
        print(f"  non-verified tools: {len(work)}")
        for t, n in sorted(tiers.items()):
            print(f"    {t:22s} {n}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
