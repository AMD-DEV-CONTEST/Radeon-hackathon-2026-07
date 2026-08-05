"""Driver: run the teacher and report success rate and throughput.

Renders nothing, so it measures the physics alone. Collection renders three
streams per tick and is bound by host RAM instead, which is why `collect` has
its own scaling probe rather than trusting this one.

    uv run rollout
    uv run rollout --envs 32 --batches 4
    uv run rollout --scaling 1,4,16,64
"""
from __future__ import annotations

import argparse
import time
from dataclasses import replace

import numpy as np
import genesis as gs

from . import teacher
from .config import EnvConfig
from .randomize import sample_episode
from .scene import build_scene
from .task_state import EpisodeResult


def merge(results: list[EpisodeResult]) -> EpisodeResult:
    """Concatenate per-batch results into one, so N and batch count drop out."""
    return EpisodeResult(**{
        f: np.concatenate([getattr(r, f) for r in results])
        for f in EpisodeResult.__dataclass_fields__
    })


def run(cfg: EnvConfig, batches: int, *, quiet: bool = False) -> tuple[EpisodeResult, float]:
    """`batches` episodes of `cfg.n_envs` envs each. Returns results and wall time."""
    b = build_scene(cfg)
    rng = np.random.default_rng(cfg.seed)

    results = []
    t0 = time.perf_counter()
    for i in range(batches):
        setup = sample_episode(cfg, rng)
        b.reset(setup)
        r = teacher.run_episode(b, setup, rng)
        results.append(r)
        if not quiet:
            print(f"  batch {i + 1}/{batches}: {r.success.sum()}/{r.n}")
    return merge(results), time.perf_counter() - t0


def report(r: EpisodeResult, wall: float, n_envs: int) -> None:
    ok = r.success
    print(f"\n  success        {ok.sum()}/{r.n} = {100 * ok.mean():.1f}%")
    print(f"  opened         {r.opened.sum()}/{r.n}")
    print(f"  released       {r.released.sum()}/{r.n}")
    print(f"  wrong drawer   {r.wrong_drawer.sum()}")
    print(f"  dragged        {r.dragged.sum()}")
    print(f"  travel         mean {r.travel.mean() * 1e3:.1f} mm")
    print(f"  shortfall      mean {r.shortfall.mean() * 1e3:.2f} mm, "
          f"max {r.shortfall.max() * 1e3:.2f}")
    print(f"  cabinet shift  mean {r.shift.mean() * 1e3:.2f} mm, "
          f"max {r.shift.max() * 1e3:.2f}")

    # The number the tactile channel is judged on. Averaged over episodes that
    # actually both stopped and released; -1 marks the ones that did not.
    lat = r.latency[r.latency >= 0]
    if len(lat):
        print(f"  release latency mean {lat.mean():.0f} steps, "
              f"median {np.median(lat):.0f}, max {lat.max()}")
    print(f"\n  wall {wall:.1f}s for {r.n} episodes at N={n_envs}"
          f"  ->  {60 * r.n / wall:.1f} episodes/min")


def main() -> None:
    ap = argparse.ArgumentParser(description="teacher success rate and throughput")
    ap.add_argument("--envs", type=int, default=8)
    ap.add_argument("--batches", type=int, default=2)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--scaling", default=None,
                    help="comma-separated env counts to sweep instead of one run")
    args = ap.parse_args()

    gs.init(backend=gs.gpu, logging_level="warning")
    base = EnvConfig(n_envs=args.envs, seed=args.seed)

    if not args.scaling:
        r, wall = run(base, args.batches)
        report(r, wall, base.n_envs)
        return

    # One scene per N: n_envs is baked in at build time.
    print(f"{'N':>6} {'wall':>8} {'eps/min':>9} {'success':>10} {'speedup':>8}")
    first = None
    for n in (int(x) for x in args.scaling.split(",")):
        r, wall = run(replace(base, n_envs=n), args.batches, quiet=True)
        rate = 60 * r.n / wall
        first = first or rate
        print(f"{n:>6} {wall:>7.1f}s {rate:>9.1f} "
              f"{r.success.sum():>4}/{r.n:<5} {rate / first:>7.1f}x")


if __name__ == "__main__":
    main()
