"""Rebuild the final state from the event stream and check it against the run.

This is the P3 acceptance test. The claim the event stream makes is that it is
a lossless record of state *changes*, so replaying it must reproduce the state
machine exactly -- if it cannot, the 100x compression against full snapshots
is buying nothing.

What the stream carries is (step, agent, kind). That reconstructs which state
every agent is in at any t, and when they changed. It does not carry position,
which is why the run also keeps the trajectory ring buffer on device.

    python -m scripts.replay_events --run-dir /data/quakesense/runs/p2_full
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simulator.agent_swarm import (
    S_INDOORS, S_TRANSIT, S_SHELTERED, S_GAVEUP,
    E_DEPART, E_RETARGET, E_ARRIVE, E_REJECTED, E_GAVEUP,
)

#: Which terminal state each event kind puts an agent into. RETARGET and
#: REJECTED leave the agent walking, so they are state-preserving.
_TRANSITION = {
    E_DEPART: S_TRANSIT,
    E_ARRIVE: S_SHELTERED,
    E_GAVEUP: S_GAVEUP,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default="/data/quakesense/runs/p2_full")
    args = ap.parse_args()

    run = Path(args.run_dir)
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    n = summary["n_agents"]

    shards = sorted((run / "events").glob("*.npy"))
    print(f"{len(shards)} shards, replaying {n:,} agents")

    state = np.full(n, S_INDOORS, dtype=np.int8)
    counts = {k: 0 for k in (E_DEPART, E_RETARGET, E_ARRIVE, E_REJECTED, E_GAVEUP)}
    total_rows = 0
    t0 = time.perf_counter()

    for sh in shards:
        ev = np.load(sh)
        total_rows += len(ev)
        agent, kind = ev[:, 1].astype(np.int64), ev[:, 2]
        for k, target in _TRANSITION.items():
            m = kind == k
            if m.any():
                state[agent[m]] = target
        for k in counts:
            counts[k] += int((kind == k).sum())

    elapsed = time.perf_counter() - t0
    rebuilt = {
        "indoors": int((state == S_INDOORS).sum()),
        "in_transit": int((state == S_TRANSIT).sum()),
        "sheltered": int((state == S_SHELTERED).sum()),
        "gave_up": int((state == S_GAVEUP).sum()),
    }
    online = {k: summary["totals"][k] for k in rebuilt}

    print(f"replayed {total_rows:,} events in {elapsed:.1f} s "
          f"({total_rows/max(elapsed,1e-9)/1e6:.1f} M events/s)")
    print(f"\n{'state':<14}{'online':>14}{'replayed':>14}{'delta':>10}")
    ok = True
    for k in rebuilt:
        d = rebuilt[k] - online[k]
        ok &= (d == 0)
        print(f"{k:<14}{online[k]:>14,}{rebuilt[k]:>14,}{d:>10,}")

    print(f"\nevent mix:")
    names = {E_DEPART: "depart", E_RETARGET: "retarget", E_ARRIVE: "arrive",
             E_REJECTED: "rejected", E_GAVEUP: "gave_up"}
    for k, v in counts.items():
        print(f"  {names[k]:<12}{v:>14,}")

    disk = sum(f.stat().st_size for f in shards)
    snap = n * summary["state_bytes"]["total_bytes_per_agent"] * summary["steps"]
    print(f"\nevent stream on disk {disk/1024**3:>8.2f} GB")
    print(f"full snapshots would be{snap/1024**3:>8.1f} GB  "
          f"({snap/max(disk,1):.0f}x)")

    print("\nREPLAY EXACT" if ok else "\nREPLAY MISMATCH -- stream is not lossless")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
