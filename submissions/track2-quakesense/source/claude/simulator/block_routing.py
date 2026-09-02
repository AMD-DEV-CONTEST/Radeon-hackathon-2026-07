"""Exact shortest-path routing over the block adjacency graph, on the GPU.

Greedy geographic routing can walk into local minima: a block whose every
neighbour is farther from the goal. Street networks cut by rivers, rail and
ring roads contain many such cases, so the simulator uses exact shortest paths.

So compute the real thing. For every (shelter, block) pair we want

    dist[s, b]  ->  network distance from block b to shelter s, metres
    pred[s, b]  ->  the next block to step to from b heading for s

Running one Dijkstra search per shelter on the CPU is the textbook answer.
Because the searches are independent and share one graph, they can instead be
processed as batched dense relaxations on the GPU. Bellman-Ford converges in as
many rounds as the graph's hop diameter, with each round performing neighbour
gathers over matrices that remain in device memory.

This turns next-hop selection from a neighbourhood search into one gather and
makes the routing workload an explicit Radeon acceleration target.
"""

from __future__ import annotations

import time

import numpy as np
import torch

#: Marks an unreachable predecessor, matching scipy's convention.
NO_PATH = -9999

_INF = 3.0e38


def locate_shelter_blocks(s_lon, s_lat, b_lon, b_lat, chunk: int = 128):
    """Nearest block centroid per shelter, chunked so the full cross product is
    never materialised."""
    s_lon = np.asarray(s_lon, dtype=np.float64)
    s_lat = np.asarray(s_lat, dtype=np.float64)
    out = np.empty(len(s_lon), dtype=np.int32)
    for i in range(0, len(s_lon), chunk):
        dx = b_lon[None, :] - s_lon[i:i + chunk, None]
        dy = b_lat[None, :] - s_lat[i:i + chunk, None]
        out[i:i + chunk] = np.argmin(dx * dx + dy * dy, axis=1)
    return out


def build_routing(neigh: np.ndarray, bx: np.ndarray, by: np.ndarray,
                  shelter_blocks: np.ndarray, device: str = "cuda",
                  max_rounds: int = 4000, check_every: int = 20,
                  budget_gib: float = 4.0, log=print):
    """Return ``(dist, pred)`` as ``(n_shelters, n_blocks)`` float32/int32.

    Sources are relaxed in batches sized to a memory budget. Large cities can
    exceed the device-memory cap when the full distance matrix and gather
    temporary are materialised together. Batching the source dimension leaves
    the result identical because each source's shortest paths are independent,
    while bounding the working set.
    """
    ns_total = len(shelter_blocks)
    nb_total = neigh.shape[0]
    per_source = nb_total * 4 * 3          # dist + one gather temp + slack
    batch = max(1, int(budget_gib * 1024 ** 3 / per_source))
    if batch < ns_total:
        log(f"routing: {ns_total:,} sources x {nb_total:,} blocks needs "
            f"{ns_total * nb_total * 4 / 1024 ** 3:.1f} GiB per matrix; "
            f"batching {batch:,} sources at a time")
        d_parts, p_parts = [], []
        for s in range(0, ns_total, batch):
            d, p = _build_batch(neigh, bx, by, shelter_blocks[s:s + batch],
                                device, max_rounds, check_every, log=None)
            d_parts.append(d)
            p_parts.append(p)
        dist = np.concatenate(d_parts, axis=0)
        pred = np.concatenate(p_parts, axis=0)
        reach = float((pred != NO_PATH).mean())
        log(f"routing: done in {len(d_parts)} batches; reachable {reach*100:.1f}%")
        return dist, pred
    return _build_batch(neigh, bx, by, shelter_blocks, device, max_rounds,
                        check_every, log)


def _build_batch(neigh, bx, by, shelter_blocks, device, max_rounds,
                 check_every, log=print):
    d = torch.device(device)
    nb, D = neigh.shape
    ns = len(shelter_blocks)

    nbr = torch.as_tensor(neigh.astype(np.int64)).to(d)              # (nb, D)
    valid = nbr >= 0
    nbr_safe = nbr.clamp_min(0)
    bxt = torch.as_tensor(np.asarray(bx, dtype=np.float32)).to(d)
    byt = torch.as_tensor(np.asarray(by, dtype=np.float32)).to(d)
    w = torch.sqrt((bxt[nbr_safe] - bxt.unsqueeze(1)) ** 2
                   + (byt[nbr_safe] - byt.unsqueeze(1)) ** 2).clamp_min(1.0)
    # A padded slot must never win a relaxation.
    w = torch.where(valid, w, torch.full_like(w, _INF))

    dist = torch.full((ns, nb), _INF, dtype=torch.float32, device=d)
    src = torch.as_tensor(np.asarray(shelter_blocks, dtype=np.int64)).to(d)
    dist[torch.arange(ns, device=d), src] = 0.0

    t0 = time.perf_counter()
    rounds = 0
    for r in range(max_rounds):
        rounds = r + 1
        prev = dist if (r + 1) % check_every == 0 else None
        if prev is not None:
            prev = dist.clone()
        for j in range(D):
            # Relaxing one neighbour slot at a time keeps the temporary at
            # (ns, nb) instead of (ns, nb, D), avoiding a much larger tensor.
            cand = dist[:, nbr[:, j].clamp_min(0)] + w[:, j].unsqueeze(0)
            torch.minimum(dist, cand, out=dist)
        if prev is not None and bool(torch.equal(dist, prev)):
            break
    torch.cuda.synchronize() if d.type == "cuda" else None
    relax_s = time.perf_counter() - t0

    # Predecessor: from b heading for s, step to the neighbour that lies on a
    # shortest path. Recovered in one pass now that distances are final.
    t1 = time.perf_counter()
    best = torch.full((ns, nb), _INF, dtype=torch.float32, device=d)
    pred = torch.full((ns, nb), NO_PATH, dtype=torch.int32, device=d)
    for j in range(D):
        nj = nbr[:, j].clamp_min(0)
        cand = dist[:, nj] + w[:, j].unsqueeze(0)
        better = cand < best
        best = torch.where(better, cand, best)
        pred = torch.where(better, nbr[:, j].to(torch.int32).unsqueeze(0), pred)
    # A block that already *is* the shelter has no next hop, and an unreachable
    # one must stay flagged rather than inherit a bogus neighbour.
    pred = torch.where(best >= _INF * 0.5,
                       torch.full_like(pred, NO_PATH), pred)
    pred[torch.arange(ns, device=d), src] = src.to(torch.int32)
    torch.cuda.synchronize() if d.type == "cuda" else None
    pred_s = time.perf_counter() - t1

    reach = float((pred != NO_PATH).to(torch.float32).mean().item())
    if log:
        log(f"routing: {ns} sources x {nb:,} blocks, {rounds} relax rounds in "
            f"{relax_s:.1f} s + {pred_s:.1f} s predecessors; "
            f"{dist.numel()*4/1024**2:.0f} MB dist + "
            f"{pred.numel()*4/1024**2:.0f} MB pred; reachable {reach*100:.1f}%")

    out_d = dist.cpu().numpy()
    out_p = pred.cpu().numpy()
    del dist, pred, best, w, nbr, nbr_safe, valid
    if d.type == "cuda":
        torch.cuda.empty_cache()
    return out_d, out_p


def cache_routing(path, neigh, bx, by, shelter_blocks, device: str = "cuda",
                  log=print, **kw):
    from pathlib import Path
    path = Path(path)
    if path.exists():
        z = np.load(path)
        log(f"routing cache hit {path.name}")
        return z["dist"], z["pred"]
    dist, pred = build_routing(neigh, bx, by, shelter_blocks, device=device,
                               log=log)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, dist=dist, pred=pred, shelter_blocks=shelter_blocks)
    log(f"routing cached to {path} ({path.stat().st_size/1024**2:.0f} MB)")
    return dist, pred
