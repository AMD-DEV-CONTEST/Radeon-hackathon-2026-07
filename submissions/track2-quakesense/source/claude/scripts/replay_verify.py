"""Prove -- or disprove -- that the event stream reconstructs the run.

The compression claim rests entirely on this: if a 32 GB event stream really
carries what an 8.2 TB sequence of full snapshots carries, then replaying the
events must land on exactly the state the simulation was in. Until that is
checked field by field, "lossless" is an assertion, not a result.

So the run dumps its live ``state`` vector at chosen steps, and this script
rebuilds the same vector from events alone and compares all 22,381,605 entries.
Any disagreement is reported per transition, because *which* transition is lost
tells you whether the cause is a dropped event, an ordering mistake, or a state
change nobody recorded.

    python -m scripts.replay_verify --run /data/quakesense/runs/verify

What this can and cannot establish: the stream records state transitions, so it
determines every agent's state-machine trajectory. It carries no coordinates,
so position, target and distance walked are NOT reconstructible from it and are
reported as such rather than quietly omitted.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

S_INDOORS, S_DEPARTING, S_QUEUED, S_TRANSIT, S_SHELTERED, S_GAVEUP = range(6)
E_DEPART, E_RETARGET, E_ARRIVE, E_REJECTED, E_GAVEUP = range(5)

#: Which event drives which transition. Events that carry information but do
#: not move the state machine map to None and must be no-ops on replay.
TRANSITION = {
    E_DEPART: S_TRANSIT,
    E_ARRIVE: S_SHELTERED,
    E_GAVEUP: S_GAVEUP,
    E_RETARGET: None,
    E_REJECTED: None,
}
NAMES = {E_DEPART: "depart", E_RETARGET: "retarget", E_ARRIVE: "arrive",
         E_REJECTED: "rejected", E_GAVEUP: "gave_up"}
STATE_NAMES = {S_INDOORS: "indoors", S_TRANSIT: "in_transit",
               S_SHELTERED: "sheltered", S_GAVEUP: "gave_up"}


def replay(event_dir: Path, n_agents: int, upto_step: int, log=print):
    """Rebuild the state vector from events with ``step <= upto_step``."""
    state = np.full(n_agents, S_INDOORS, dtype=np.int8)
    shards = sorted(event_dir.glob("events_*.npy"))
    if not shards:
        raise FileNotFoundError(f"no event shards under {event_dir}")

    counts = {k: 0 for k in TRANSITION}
    total = 0
    for sh in shards:
        ev = np.load(sh, mmap_mode="r")
        step, agent, kind = ev[:, 0], ev[:, 1], ev[:, 2]
        keep = step <= upto_step
        if not keep.any():
            continue
        agent = np.asarray(agent[keep], dtype=np.int64)
        kind = np.asarray(kind[keep], dtype=np.int64)
        total += len(agent)
        # Shards are written in emission order and each shard is internally
        # ordered by step, so applying them in filename order applies the
        # transitions in the order the simulation made them.
        for ek, target in TRANSITION.items():
            m = kind == ek
            if not m.any():
                continue
            counts[ek] += int(m.sum())
            if target is not None:
                state[agent[m]] = target
    log(f"  replayed {total:,} events from {len(shards)} shards "
        f"(step <= {upto_step})")
    for ek, c in counts.items():
        log(f"    {NAMES[ek]:<10}{c:>14,}")
    return state


def compare(rebuilt: np.ndarray, truth: np.ndarray, log=print):
    same = rebuilt == truth
    n = len(truth)
    n_bad = int((~same).sum())
    log(f"  agents compared      {n:,}")
    log(f"  exact matches        {int(same.sum()):,}")
    log(f"  mismatches           {n_bad:,}  ({n_bad/n*100:.6f} %)")
    detail = []
    if n_bad:
        pairs, cnt = np.unique(
            np.stack([truth[~same], rebuilt[~same]]).T, axis=0, return_counts=True)
        for (t_, r_), c in sorted(zip(pairs.tolist(), cnt.tolist()),
                                  key=lambda x: -x[1])[:8]:
            log(f"    live={STATE_NAMES.get(t_, t_):<11} "
                f"replay={STATE_NAMES.get(r_, r_):<11} {c:>12,}")
            detail.append({"live": STATE_NAMES.get(t_, t_),
                           "replay": STATE_NAMES.get(r_, r_), "count": int(c)})
    return {"n": n, "matches": int(same.sum()), "mismatches": n_bad,
            "mismatch_share": round(n_bad / n, 9), "detail": detail}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="/data/quakesense/runs/verify")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    run = Path(a.run)

    snaps = sorted(run.glob("state_*.npy"))
    if not snaps:
        raise SystemExit(f"no state_*.npy checkpoints in {run}; "
                         f"rerun bench_swarm with --verify-at")

    ev_dir = run / "events"
    ev_bytes = sum(f.stat().st_size for f in ev_dir.glob("*.npy"))
    results, all_ok = [], True
    for snap in snaps:
        step = int(snap.stem.split("_")[1])
        truth = np.load(snap)
        print(f"\n=== checkpoint at step {step} ===")
        rebuilt = replay(ev_dir, len(truth), step)
        r = compare(rebuilt, truth)
        r["step"] = step
        results.append(r)
        all_ok &= (r["mismatches"] == 0)

    n = results[0]["n"]
    snapshot_bytes = n * 338 * (max(r["step"] for r in results) + 1)
    print("\n" + "=" * 70)
    print(f"state-machine reconstruction: {'EXACT' if all_ok else 'NOT EXACT'}")
    print(f"event stream        {ev_bytes/1024**3:>8.2f} GB")
    print(f"full snapshots      {snapshot_bytes/1024**3:>8.2f} GB "
          f"(338 B x {n:,} x every step)")
    print(f"compression         {snapshot_bytes/max(ev_bytes,1):>8.1f} x")
    print("NOT reconstructible from events: block, target, dist_walked, "
          "fatigue, belief")
    print("=" * 70)

    out = Path(a.out) if a.out else run / "replay_verification.json"
    out.write_text(json.dumps({
        "checkpoints": results,
        "state_machine_exact": bool(all_ok),
        "event_bytes": int(ev_bytes),
        "snapshot_bytes": int(snapshot_bytes),
        "compression_x": round(snapshot_bytes / max(ev_bytes, 1), 1),
        "reconstructible": ["state"],
        "not_reconstructible": ["block", "target", "dist_walked", "fatigue",
                                "n_hops", "belief"],
    }, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    raise SystemExit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
