#!/usr/bin/env python3
"""sprint4_state_audit.py - comprehensive state across ALL ProgramBench tools.

Produces:
  logs/mass_run_v2/state_audit.tsv  - one row per tool
  logs/mass_run_v2/state_audit.md   - human-readable grouped report

Columns:
  instance, family, subtype, base_pct, factory_pct, delta_pp, gap_to_100,
  bucket (LOCKED|RECOVERABLE|FAR|NOT_EVALED), test_count
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PB_ROOT = Path("T:/determinex-programbench")
BASE_DIR = PB_ROOT / "mass_run_v2_base"
OUT_TSV = ROOT / "logs" / "mass_run_v2" / "state_audit.tsv"
OUT_MD = ROOT / "logs" / "mass_run_v2" / "state_audit.md"


def score_from(eval_json: Path) -> tuple[float | None, int]:
    if not eval_json.is_file():
        return None, 0
    try:
        j = json.loads(eval_json.read_text(encoding="utf-8"))
    except Exception:
        return None, 0
    r = j.get("test_results", []) or []
    if not r:
        return None, 0
    passed = sum(1 for t in r if t.get("status") == "passed")
    return round(100.0 * passed / len(r), 2), len(r)


def classify(instance: str) -> tuple[str, str]:
    """Best-effort family + subtype lookup from eval_queue.json."""
    cache_path = ROOT / "logs" / "mass_run_v2" / "sprint4_eval_queue.json"
    if not hasattr(classify, "_cache"):
        if cache_path.is_file():
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            classify._cache = {
                r["instance"]: (r.get("family", "?"), r.get("subtype", ""))  # type: ignore[attr-defined]
                for r in data.get("ranked", [])
            }
        else:
            classify._cache = {}  # type: ignore[attr-defined]
    return classify._cache.get(instance, ("?", ""))  # type: ignore[attr-defined]


def bucket_for(base: float | None, factory: float | None) -> str:
    """Decision bucket."""
    if factory is None and base is None:
        return "NOT_EVALED"
    if factory is None:
        # Have base but no scaffold yet
        if (base or 0) >= 90:
            return "NEAR_LOCKED"
        if (base or 0) >= 50:
            return "RECOVERABLE"
        if (base or 0) >= 20:
            return "MID"
        return "FAR_NO_SCAFFOLD"
    # Have scaffold
    if factory >= 95:
        return "NEAR_LOCKED"
    if factory >= 50:
        return "RECOVERABLE"
    if factory >= 20:
        return "MID"
    return "FAR"


def main() -> int:
    if not BASE_DIR.is_dir():
        print(f"ERROR: {BASE_DIR} not found")
        return 1
    rows = []
    instances = sorted(p.name for p in BASE_DIR.iterdir() if p.is_dir())
    for inst in instances:
        base_ej = BASE_DIR / inst / f"{inst}.eval.json"
        fac_dir = PB_ROOT / f"determinex_pb_factory_{inst}_v1"
        fac_ej = fac_dir / inst / f"{inst}.eval.json"
        base, n_base = score_from(base_ej)
        fac, n_fac = score_from(fac_ej)
        family, subtype = classify(inst)
        delta = (
            round((fac or 0.0) - (base or 0.0), 2)
            if (fac is not None and base is not None)
            else None
        )
        gap = round(100.0 - (fac or base or 0.0), 2)
        rows.append(
            {
                "instance": inst,
                "family": family,
                "subtype": subtype,
                "base": base if base is not None else "-",
                "factory": fac if fac is not None else "-",
                "delta": delta if delta is not None else "-",
                "gap": gap,
                "bucket": bucket_for(base, fac),
                "n_tests": n_fac or n_base,
            }
        )

    # TSV
    OUT_TSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_TSV.open("w", encoding="utf-8", newline="\n") as f:
        f.write(
            "instance\tfamily\tsubtype\tbase_pct\tfactory_pct\tdelta_pp\tgap_to_100\tbucket\ttest_count\n"
        )
        for r in rows:
            f.write(
                f"{r['instance']}\t{r['family']}\t{r['subtype']}\t{r['base']}\t{r['factory']}\t{r['delta']}\t{r['gap']}\t{r['bucket']}\t{r['n_tests']}\n"
            )

    # Markdown grouped by family
    by_family: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_family[r["family"]].append(r)
    lines = [
        f"# ProgramBench State Audit — {len(rows)} tools",
        "",
        "## Summary by bucket",
        "",
        "| Bucket | Count | What it means |",
        "|---|---:|---|",
    ]
    bucket_counts = Counter(r["bucket"] for r in rows)
    bucket_meanings = {
        "NEAR_LOCKED": "factory >= 95% OR base >= 90% — push to 100",
        "RECOVERABLE": "factory >= 50% OR base >= 50% — close enough that targeted work hits 100",
        "MID": "20-50% — needs family-v2 generator improvements + per-tool tuning",
        "FAR": "factory ran but <20% — wrong-family or specialized scaffold needed",
        "FAR_NO_SCAFFOLD": "no factory eval yet, base <20% — sprint-5 candidate",
        "NOT_EVALED": "no base, no factory — investigate",
    }
    for b in ["NEAR_LOCKED", "RECOVERABLE", "MID", "FAR", "FAR_NO_SCAFFOLD", "NOT_EVALED"]:
        lines.append(f"| {b} | {bucket_counts.get(b, 0)} | {bucket_meanings.get(b, '')} |")
    lines.append("")

    # Family rollup
    lines.append("## Per-family rollup")
    lines.append("")
    lines.append("| Family | Tools | Avg base % | Avg factory % | Avg lift | Best | Worst |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for fam in sorted(by_family.keys()):
        items = by_family[fam]
        bs = [x["base"] for x in items if isinstance(x["base"], (int, float))]
        fs = [x["factory"] for x in items if isinstance(x["factory"], (int, float))]
        ds = [x["delta"] for x in items if isinstance(x["delta"], (int, float))]
        avg_b = round(sum(bs) / len(bs), 1) if bs else 0.0
        avg_f = round(sum(fs) / len(fs), 1) if fs else 0.0
        avg_d = round(sum(ds) / len(ds), 2) if ds else 0.0
        best = max(fs) if fs else max(bs) if bs else 0.0
        worst = min(fs) if fs else min(bs) if bs else 0.0
        lines.append(
            f"| {fam} | {len(items)} | {avg_b} | {avg_f} | {avg_d:+.2f} | {best} | {worst} |"
        )
    lines.append("")

    # Full per-tool table, sorted by factory score descending then base descending
    def sort_key(r: dict) -> tuple:
        fac = r["factory"] if isinstance(r["factory"], (int, float)) else -1
        base = r["base"] if isinstance(r["base"], (int, float)) else -1
        return (-fac, -base)

    rows_sorted = sorted(rows, key=sort_key)
    lines.append("## Full tool list (sorted by current best score)")
    lines.append("")
    lines.append("| Instance | Family | Base % | Factory % | Δ | Gap to 100 | Bucket |")
    lines.append("|---|---|---:|---:|---:|---:|---|")
    for r in rows_sorted:
        lines.append(
            f"| `{r['instance']}` | {r['family']} | {r['base']} | {r['factory']} | {r['delta']} | {r['gap']} | {r['bucket']} |"
        )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print("AUDIT written:")
    print(f"  TSV: {OUT_TSV}")
    print(f"  MD:  {OUT_MD}")
    print()
    print("=== bucket counts ===")
    for b in ["NEAR_LOCKED", "RECOVERABLE", "MID", "FAR", "FAR_NO_SCAFFOLD", "NOT_EVALED"]:
        print(f"  {b:<20} {bucket_counts.get(b, 0):>4}")
    print()
    print("=== top 10 by best score ===")
    for r in rows_sorted[:10]:
        best = r["factory"] if isinstance(r["factory"], (int, float)) else r["base"]
        print(f"  {r['instance']:<48} fam={r['family']:<18} score={best}% gap={r['gap']}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
