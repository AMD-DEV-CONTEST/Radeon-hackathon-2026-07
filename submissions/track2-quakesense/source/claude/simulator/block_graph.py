"""Real block adjacency from shared polygon edges.

Two road-enclosed blocks are neighbours if they share a boundary segment, not
if their centroids happen to be close. A k-nearest-centroid graph would let
people step across a river or a rail corridor, which is exactly the error the
resistance surface exists to prevent.

The construction is fully vectorised: quantise every vertex to an integer id,
emit one (u, v) pair per polygon edge, sort each pair, and group identical
pairs. An edge shared by exactly two polygons is an adjacency.
"""

from __future__ import annotations

import numpy as np

#: Vertex quantisation, ~1.1 cm at the equator. Coarse enough that two
#: polygons digitised from the same road centreline land on the same id,
#: fine enough not to merge genuinely distinct corners.
_SCALE = 1e7
_LAT_SPAN = 1 << 31


def _vertex_ids(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    qlon = np.rint((lon + 180.0) * _SCALE).astype(np.int64)
    qlat = np.rint((lat + 90.0) * _SCALE).astype(np.int64)
    return qlon * _LAT_SPAN + qlat


def _rings(geom):
    """Yield exterior rings for Polygon and MultiPolygon."""
    t = geom.get("type")
    if t == "Polygon":
        if geom["coordinates"]:
            yield geom["coordinates"][0]
    elif t == "MultiPolygon":
        for poly in geom["coordinates"]:
            if poly:
                yield poly[0]


def build_adjacency(features, max_degree: int = 12):
    """Return ``(neighbours, valid_count)`` padded to ``max_degree``.

    ``neighbours[b, j]`` is the j-th neighbour of block b, or -1 past its
    degree. Padding to a fixed width is what lets the step loop gather all
    neighbours of all agents in one indexed read instead of walking a CSR.
    """
    lon_parts, lat_parts, owner_parts = [], [], []
    for bid, feat in enumerate(features):
        for ring in _rings(feat.get("geometry") or {}):
            if len(ring) < 4:
                continue
            arr = np.asarray(ring, dtype=np.float64)
            lon_parts.append(arr[:, 0])
            lat_parts.append(arr[:, 1])
            owner_parts.append(np.full(arr.shape[0], bid, dtype=np.int32))

    if not lon_parts:
        raise ValueError("no polygon rings found; cannot build adjacency")

    # Per-ring edges: vertex i -> i+1, with the ring closed by its own repeat.
    us, vs, own = [], [], []
    for lon_r, lat_r, o in zip(lon_parts, lat_parts, owner_parts):
        vid = _vertex_ids(lon_r, lat_r)
        us.append(vid[:-1])
        vs.append(vid[1:])
        own.append(o[:-1])
    u = np.concatenate(us)
    v = np.concatenate(vs)
    owner = np.concatenate(own)

    pair = np.stack([np.minimum(u, v), np.maximum(u, v)], axis=1)
    # Drop degenerate edges created by duplicated vertices.
    keep = pair[:, 0] != pair[:, 1]
    pair, owner = pair[keep], owner[keep]

    order = np.lexsort((pair[:, 1], pair[:, 0]))
    pair, owner = pair[order], owner[order]

    same = np.empty(pair.shape[0], dtype=bool)
    same[0] = False
    same[1:] = (pair[1:, 0] == pair[:-1, 0]) & (pair[1:, 1] == pair[:-1, 1])

    # A shared edge is a run of length >= 2. Pair each element of a run with
    # its predecessor; that catches every 2-block edge and, for the rare
    # 3-block artefact, still yields real adjacencies.
    a = owner[1:][same[1:]]
    b = owner[:-1][same[1:]]
    both = (a != b)
    a, b = a[both], b[both]

    # Symmetrise, then deduplicate.
    src = np.concatenate([a, b])
    dst = np.concatenate([b, a])
    key = src.astype(np.int64) * (int(owner.max()) + 1) + dst.astype(np.int64)
    uniq = np.unique(key)
    n_blocks = len(features)
    src = (uniq // (int(owner.max()) + 1)).astype(np.int32)
    dst = (uniq % (int(owner.max()) + 1)).astype(np.int32)

    return _pack(src, dst, n_blocks, max_degree)


def _pack(src, dst, n_blocks, max_degree):
    deg = np.bincount(src, minlength=n_blocks)
    nb = np.full((n_blocks, max_degree), -1, dtype=np.int32)
    starts = np.concatenate([[0], np.cumsum(deg)[:-1]])
    slot = np.arange(len(src), dtype=np.int64) - np.repeat(starts, deg)
    fits = slot < max_degree
    nb[src[fits], slot[fits]] = dst[fits]
    return nb, np.minimum(deg, max_degree).astype(np.int32)


def _components(neigh, n_blocks):
    """Connected components by iterative label propagation.

    Vectorised rather than a union-find loop so large block layers remain
    practical without a Python-level union-find pass.
    """
    lab = np.arange(n_blocks, dtype=np.int64)
    nbr = neigh.astype(np.int64)
    valid = nbr >= 0
    safe = np.where(valid, nbr, 0)
    while True:
        cand = np.where(valid, lab[safe], np.iinfo(np.int64).max)
        new = np.minimum(lab, cand.min(axis=1))
        new = np.minimum(new, new[new])          # path compression
        if np.array_equal(new, lab):
            return lab
        lab = new


def bridge_components(neigh, bx, by, population, max_degree: int = 12,
                      log=print):
    """Connect disjoint components with their shortest inter-component link.

    Road-derived block layers can contain disconnected components when the
    source geometry omits a short connector. That can make residents appear
    unreachable even when adjacent polygons are only a short walk apart.

    Bridging adds, for each stranded component, the single shortest link to an
    already-connected block. This is a topological repair of the input, not a
    behavioural assumption: it asserts only that a person can walk between two
    adjacent blocks, which the geometry already implies.
    """
    n = len(bx)
    lab = _components(neigh, n)
    roots, counts = np.unique(lab, return_counts=True)
    if len(roots) == 1:
        return neigh, 0
    main = roots[np.argmax(counts)]

    src_e = np.repeat(np.arange(n, dtype=np.int32), neigh.shape[1])
    dst_e = neigh.reshape(-1)
    keep = dst_e >= 0
    src_e, dst_e = src_e[keep], dst_e[keep].astype(np.int32)

    connected = np.flatnonzero(lab == main)
    added = []
    # Process components largest-first so each bridge lands on a big target.
    order = roots[np.argsort(-counts)]
    for r in order:
        if r == main:
            continue
        members = np.flatnonzero(lab == r)
        # Nearest pair between this component and everything already connected.
        best = (np.inf, -1, -1)
        step = max(1, len(connected) // 20000)
        pool = connected[::step]
        for i in range(0, len(members), 256):
            m = members[i:i + 256]
            d2 = ((bx[pool][None, :] - bx[m][:, None]) ** 2
                  + (by[pool][None, :] - by[m][:, None]) ** 2)
            j = np.unravel_index(np.argmin(d2), d2.shape)
            if d2[j] < best[0]:
                best = (float(d2[j]), int(m[j[0]]), int(pool[j[1]]))
        _, a, b = best
        added.append((a, b))
        connected = np.concatenate([connected, members])

    if not added:
        return neigh, 0
    aa = np.array([a for a, _ in added], dtype=np.int32)
    bb = np.array([b for _, b in added], dtype=np.int32)
    src_e = np.concatenate([aa, bb, src_e])
    dst_e = np.concatenate([bb, aa, dst_e])
    # A bridge must outrank an ordinary edge when the degree cap truncates,
    # or the one link holding a town to the city gets dropped and the repair
    # silently does nothing. _pack also needs src sorted.
    prio = np.concatenate([np.zeros(2 * len(added), dtype=np.int8),
                           np.ones(len(src_e) - 2 * len(added), dtype=np.int8)])
    order = np.lexsort((prio, src_e))
    src_e, dst_e = src_e[order], dst_e[order]
    out, deg = _pack(src_e, dst_e, n, max_degree)
    stranded_pop = float(population[lab != main].sum())
    log(f"bridged {len(added):,} components with {len(added):,} links; "
        f"recovered {stranded_pop:,.0f} people "
        f"({stranded_pop/population.sum()*100:.2f}% of the city)")
    return out, len(added)


def damage_edges(neigh, frac: float, seed: int = 42, max_degree: int = 14,
                 log=print):
    """Sever a fraction of block-to-block links, as collapse and debris do.

    An earthquake does not politely leave the network intact. Blocked links are
    what turn a 400 m walk into a 4 km detour, and because the routing tables
    are rebuilt from the damaged graph, the detour is computed rather than
    assumed. Some blocks may be cut off entirely -- that is a result, not a
    failure, and it shows up as gave_up_no_path.

    Edges are removed symmetrically: a street blocked by rubble is blocked in
    both directions.
    """
    if frac <= 0:
        return neigh, 0
    n, D = neigh.shape
    src = np.repeat(np.arange(n, dtype=np.int32), D)
    dst = neigh.reshape(-1)
    keep = dst >= 0
    src, dst = src[keep], dst[keep].astype(np.int32)
    # Canonical form so both directions of a link share one coin flip.
    lo, hi = np.minimum(src, dst), np.maximum(src, dst)
    key = lo.astype(np.int64) * n + hi.astype(np.int64)
    uniq, inv = np.unique(key, return_inverse=True)
    rng = np.random.default_rng(seed)
    cut = rng.random(uniq.size) < frac
    alive = ~cut[inv]
    out, deg = _pack(src[alive], dst[alive], n, max_degree)
    lab = _components(out, n)
    log(f"road damage {frac:.0%}: cut {int(cut.sum()):,} of {uniq.size:,} links; "
        f"mean degree {deg.mean():.2f}; components {len(np.unique(lab)):,}")
    return out, int(cut.sum())
