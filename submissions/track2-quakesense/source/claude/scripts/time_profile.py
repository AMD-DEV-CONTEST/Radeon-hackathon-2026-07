"""Cumulative share safe over time, per run.

A single "sheltered" total hides the shape of the evacuation. Guidance can
front-load it -- more people safe in the first fifteen minutes, fewer by the
third hour -- and reporting only the endpoint turns that trade-off into a flat
"leadership made things worse", which is not what happened.

    python -m scripts.time_profile base_k005 llm_c00 llm_c05 llm_c10
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RUNS = Path("/data/quakesense/runs")
MARKS = (15, 30, 60, 120)


def main(names):
    head = f"{'scenario':>13}" + "".join(f"{'safe@' + str(m) + 'm':>11}"
                                         for m in MARKS)
    head += f"{'final':>11}{'p50':>8}{'p90':>8}"
    print(head)
    print("-" * len(head))
    rows = []
    for n in names:
        f = RUNS / f"ab_{n}" / "summary.json"
        if not f.exists():
            print(f"{n:>13}   (missing)")
            continue
        t = json.loads(f.read_text(encoding="utf-8"))["totals"]
        n_ag = t["n_agents"]
        cells = [f"{n:>13}"]
        vals = []
        for m in MARKS:
            v = t.get(f"share_safe_by_{m}min", 0.0)
            vals.append(v)
            cells.append(f"{v * 100:>10.3f}%")
        fin = t["sheltered"] / n_ag
        cells.append(f"{fin * 100:>10.3f}%")
        cells.append(f"{t.get('t_p50_min_of_sheltered', 0):>8.1f}")
        cells.append(f"{t.get('t_p90_min_of_sheltered', 0):>8.1f}")
        print("".join(cells))
        rows.append((n, vals, fin))

    if len(rows) > 1:
        base, bvals, bfin = rows[0]
        print(f"\nrelative to {base}:")
        for n, vals, fin in rows[1:]:
            deltas = "  ".join(
                f"@{m}m {(v - b) / b * 100:+6.1f}%" if b else f"@{m}m    n/a"
                for m, v, b in zip(MARKS, vals, bvals))
            print(f"  {n:<12} {deltas}   final {(fin - bfin) / bfin * 100:+6.1f}%")
        print("\nA positive early delta with a negative final one means guidance "
              "front-loaded the evacuation\nrather than improving or harming it "
              "outright -- report both, not the endpoint alone.")


if __name__ == "__main__":
    main(sys.argv[1:])
