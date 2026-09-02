"""Print the ablation matrix as one table, and guard every row.

Reading fourteen summary.json files by hand is how a disconnected mechanism
slips through, so this pairs each row with scripts.guard rather than trusting
the numbers to look wrong.

    python -m scripts.ablation_table base_k005 bell5 bell50
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RUNS = Path("/data/quakesense/runs")

#: (header, width, format, extractor). Width is explicit because deriving it
#: from the format spec mis-parsed "{:>9.2%}" as width 92 and ran the columns
#: together.
COLS = [
    ("scenario", 13, "{:>13}", None),
    ("sheltered", 12, "{:>12,}", lambda t: t["sheltered"]),
    ("util", 8, "{:>8.3f}", lambda t: t["shelter_utilisation"]),
    ("p50", 7, "{:>7.1f}", lambda t: t.get("t_p50_min_of_sheltered", 0.0)),
    ("p90", 7, "{:>7.1f}", lambda t: t.get("t_p90_min_of_sheltered", 0.0)),
    ("safe15m", 9, "{:>8.2f}%", lambda t: t.get("share_safe_by_15min", 0.0) * 100),
    ("walk_m", 8, "{:>8.0f}", lambda t: t["median_dist_walked_m"]),
    ("no_path", 11, "{:>11,}", lambda t: t["gave_up_no_path"]),
    ("gini", 7, "{:>7.3f}", lambda t: t.get("shelter_occupancy_gini", 0.0)),
    ("known", 7, "{:>7.2f}", lambda t: t.get("mean_shelters_known", 0.0)),
]


def main(names):
    print("".join(f"{c[0]:>{c[1]}}" for c in COLS))
    print("-" * sum(c[1] for c in COLS))
    seen = []
    for n in names:
        f = RUNS / f"ab_{n}" / "summary.json"
        if not f.exists():
            print(f"{n:>13}   (not finished)")
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        t = d["totals"]
        seen.append((n, d))
        cells = [f"{n:>13}"]
        for _name, _w_, fmt, get in COLS[1:]:
            cells.append(fmt.format(get(t)))
        print("".join(cells))
    return seen


if __name__ == "__main__":
    seen = main(sys.argv[1:])
    # Same rule as guard: two differently-configured runs must not coincide.
    from scripts.guard import check_identical, check_run
    bad = 0
    for i in range(len(seen) - 1):
        (na, a), (nb, b) = seen[i], seen[i + 1]
        for m in check_identical(a, b, na, nb):
            print(f"\n[FAIL] {m}")
            bad += 1
    for n, d in seen:
        f, w = check_run(d, n)
        for m in f:
            print(f"[FAIL] {n}: {m}")
            bad += 1
    if not bad:
        print("\n[guard] all rows pass")
