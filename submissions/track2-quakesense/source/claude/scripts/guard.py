"""Invariant checks that fail loudly, so today's bugs cannot happen twice.

Every defect this project hit on 2026-08-01 was detectable by a rule that
nobody was running. The expensive ones were not crashes -- they were runs that
finished cleanly and reported plausible numbers while a whole mechanism sat
disconnected:

* two configurations produced bit-identical results (the LLM tier was inert);
* 4,539 of 4,555 leader decisions were counted as hallucinations because a
  legal action was not in the validation list;
* bridging reported success while the graph still had 235 components;
* a sweep point silently equalled its neighbour because another parameter
  clamped it.

    python -m scripts.guard --run  /data/quakesense/runs/ab_llm_c05
    python -m scripts.guard --compare runA runB      # must NOT be identical
    python -m scripts.guard --sweep  runs/ab_base_*  # points must differ

Exit code is non-zero when any check fails, so this drops straight into a
queue script without anyone having to read the output.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

#: Fields whose exact equality across two differently-configured runs means the
#: configuration never reached the simulation. Floats, deliberately: two real
#: runs agreeing to the last bit of a float64 is not a coincidence.
FINGERPRINT = ("sheltered", "median_dist_walked_m", "mean_dist_walked_m",
               "gave_up_exhausted", "mean_switches")


def _load(p):
    p = Path(p)
    f = p / "summary.json" if p.is_dir() else p
    return json.loads(Path(f).read_text(encoding="utf-8"))


def check_run(d, name="run"):
    """Physical and plumbing invariants for a single run."""
    t, llm = d.get("totals", {}), d.get("llm") or {}
    fails, warns = [], []

    def bad(c, msg):
        (fails if c else warns).append(msg) if c else None

    # -- conservation and capacity: these are physics, not preferences -------
    if t.get("conservation_error", 0) != 0:
        fails.append(f"conservation violated by {t['conservation_error']}")
    if t.get("overfilled_shelters", 0) != 0:
        fails.append(f"{t['overfilled_shelters']} shelters over capacity")
    n = t.get("n_agents", 0)
    acc = t.get("accounted", 0)
    if n and acc != n:
        fails.append(f"accounted {acc:,} != n_agents {n:,}")
    sh, cap = t.get("sheltered", 0), t.get("shelter_capacity", 0)
    if cap and sh > cap:
        fails.append(f"sheltered {sh:,} exceeds capacity {cap:,}")

    # -- the LLM tier is either off, or it did something ---------------------
    if d.get("llm_enabled") and llm:
        calls = llm.get("calls", 0)
        if calls == 0:
            fails.append("LLM enabled but zero calls were made")
        applied = llm.get("applied_decisions", 0)
        if calls and applied / calls < 0.05:
            fails.append(f"only {applied}/{calls} LLM decisions applied "
                         f"({applied/calls:.1%}) -- the tier is effectively off")
        hall = llm.get("hallucinated_shelter", 0)
        if calls and hall / calls > 0.5:
            fails.append(f"{hall}/{calls} replies rejected as hallucinated -- "
                         f"check whether a legal action is missing from the "
                         f"validation list")
        unp = llm.get("unparseable_replies", 0)
        if calls and unp / calls > 0.3:
            warns.append(f"{unp}/{calls} replies unparseable ({unp/calls:.1%})")
        hold = llm.get("hold_share")
        if hold is not None and hold > 0.98:
            warns.append(f"hold_share {hold:.1%} -- the tier is abstaining, "
                         f"which is indistinguishable from being switched off")
        if llm.get("grammar_share", 1.0) < 0.9:
            warns.append(f"grammar applied to only "
                         f"{llm['grammar_share']:.0%} of calls")

    # -- knowledge model wired up -------------------------------------------
    if "mean_shelters_known" in t and t["mean_shelters_known"] == 0 \
            and t.get("sheltered", 0) > 1000:
        warns.append("nobody knows any shelter yet thousands are sheltered")

    # -- survivorship bias in the headline number ---------------------------
    p90 = t.get("t_p90_min_of_sheltered")
    sh_share = t.get("sheltered", 0) / max(t.get("n_agents", 1), 1)
    ref = t.get("share_safe_by_120min")
    if p90 is not None and ref is not None and sh_share and ref < sh_share * 0.95:
        warns.append("share_safe_by_120min is well below the final sheltered "
                     "share -- check the time quantiles are not being read as "
                     "a benefit when the slow tail simply gave up")

    # -- something actually moved -------------------------------------------
    if t.get("in_transit", 0) == 0 and t.get("sheltered", 0) == 0:
        fails.append("no agent ever moved")
    return fails, warns


def check_identical(a, b, na="A", nb="B"):
    """Two differently-configured runs must not agree bit for bit."""
    ta, tb = a.get("totals", {}), b.get("totals", {})
    # Exact equality means the config never arrived. Agreement to within a
    # few parts in ten thousand means the mechanism arrived but does nothing,
    # which is the same finding at a different volume -- the bellwether sweep
    # produced 1,700,473 / 1,700,193 / 1,700,739 and slipped through an
    # equality-only test.
    same, near = [], []
    for k in FINGERPRINT:
        if k not in ta or k not in tb:
            continue
        va, vb = ta[k], tb[k]
        if va == vb:
            same.append(k)
        elif va and abs(va - vb) / abs(va) < 5e-4:
            near.append(k)
    cfg_differs = any(a.get(k) != b.get(k) for k in
                      ("tag", "llm_enabled", "frac_knows_one", "word_of_mouth",
                       "knowledge_spread", "broadcast_reach", "leader_comm",
                       "bellwether_weight", "road_damage"))
    msgs = []
    if same and cfg_differs:
        msgs.append(f"{na} and {nb} are configured differently but agree "
                    f"exactly on {', '.join(same)} -- the configuration did "
                    f"not reach the simulation")
    if not same and len(near) >= 3 and cfg_differs:
        msgs.append(f"{na} and {nb} agree to within 0.05 % on "
                    f"{', '.join(near)} -- the mechanism is wired up but has "
                    f"no measurable effect; say so rather than reporting it "
                    f"as a result")
    return msgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", nargs="*", default=[])
    ap.add_argument("--compare", nargs=2, default=None)
    ap.add_argument("--sweep", nargs="*", default=[],
                    help="Glob of runs that vary one parameter; every pair must "
                         "differ.")
    a = ap.parse_args()

    n_fail = 0
    for r in a.run:
        for path in sorted(glob.glob(r)) or [r]:
            try:
                d = _load(path)
            except Exception as exc:                       # noqa: BLE001
                print(f"[GUARD] {path}: cannot read ({exc})")
                n_fail += 1
                continue
            f, w = check_run(d, path)
            tag = d.get("tag") or Path(path).name
            for m in w:
                print(f"[warn] {tag}: {m}")
            for m in f:
                print(f"[FAIL] {tag}: {m}")
            n_fail += len(f)
            if not f:
                print(f"[ok]   {tag}")

    if a.compare:
        A, B = (_load(x) for x in a.compare)
        msgs = check_identical(A, B, *a.compare)
        for m in msgs:
            print(f"[FAIL] {m}")
        n_fail += len(msgs)
        if not msgs:
            print(f"[ok]   {a.compare[0]} and {a.compare[1]} differ")

    paths = [p for g in a.sweep for p in sorted(glob.glob(g))]
    if len(paths) > 1:
        loaded = [(p, _load(p)) for p in paths]
        for i in range(len(loaded) - 1):
            (pa, A), (pb, B) = loaded[i], loaded[i + 1]
            msgs = check_identical(A, B, Path(pa).name, Path(pb).name)
            for m in msgs:
                print(f"[FAIL] {m}")
            n_fail += len(msgs)
        if n_fail == 0:
            print(f"[ok]   {len(paths)} sweep points all differ")

    print(f"\n{'PASS' if n_fail == 0 else str(n_fail) + ' FAILURE(S)'}")
    raise SystemExit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
