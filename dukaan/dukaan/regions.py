"""Connected regions of a boolean mask, without pulling in SciPy.

The cutout decides per pixel whether something is product or backdrop, and per
pixel is not enough information. Two failures come out of that, both visible in
the shipped gallery before this existed:

- A blue-and-white vase photographed on a lit sweep has porcelain almost the
  same brightness as the backdrop behind it, so the middle of the vase is
  classified as background and the product ends up full of holes.
- The same photograph's vignette leaves a bright lobe that no plausible
  backdrop fit removes, and it survives as a streak floating beside the product.

Both are obvious once you look at whole regions instead of pixels: the holes are
background that cannot reach the edge of the image, and the streak is a blob
that is not the product. Neither needs a heavyweight dependency, so this labels
runs per row and unions them across rows, which is a few thousand operations
rather than the several hundred thousand a pixel flood fill would take. PIL's
own `ImageDraw.floodfill` is not an option: on Pillow 12.3 it fills nothing at
all, including on a 10x10 test image.
"""
from __future__ import annotations

import numpy as np


def _row_runs(row: np.ndarray) -> list[tuple[int, int]]:
    """Half-open [start, end) spans of True in one row."""
    if not row.any():
        return []
    d = np.diff(row.astype(np.int8))
    starts = (np.nonzero(d == 1)[0] + 1).tolist()
    ends = (np.nonzero(d == -1)[0] + 1).tolist()
    if row[0]:
        starts.insert(0, 0)
    if row[-1]:
        ends.append(len(row))
    return list(zip(starts, ends))


def label(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """Label connected True regions, 4-connected. Returns (labels, count)."""
    h, _ = mask.shape
    runs: list[list[tuple[int, int]]] = [_row_runs(mask[y]) for y in range(h)]

    parent: list[int] = [0]

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    ids: list[list[int]] = []
    for y, row in enumerate(runs):
        ids.append([])
        for (x0, x1) in row:
            parent.append(len(parent))
            mine = len(parent) - 1
            if y:
                for j, (px0, px1) in enumerate(runs[y - 1]):
                    if px0 < x1 and x0 < px1:          # spans overlap
                        union(mine, ids[y - 1][j])
            ids[y].append(mine)

    remap: dict[int, int] = {}
    out = np.zeros(mask.shape, dtype=np.int32)
    for y, row in enumerate(runs):
        for j, (x0, x1) in enumerate(row):
            root = find(ids[y][j])
            if root not in remap:
                remap[root] = len(remap) + 1
            out[y, x0:x1] = remap[root]
    return out, len(remap)


def fill_holes(mask: np.ndarray, max_frac: float = 0.02) -> np.ndarray:
    """Close background pockets inside the product, but only small ones.

    "Enclosed by the product" is not the same as "part of the product". A pair
    of bangles encloses two large circles of real backdrop, and a teapot handle
    encloses another; filling those turns rings into discs. Measured on the
    gilt bangles, an unrestricted fill nearly doubled the mask, from 14.7% of
    the frame to 28.2%.

    So size decides. Speckle from a product that merely resembles its backdrop
    is small against the product; a bangle's interior is a large fraction of it.
    `max_frac` is that fraction, measured against the product's own area.
    """
    lab, n = label(~mask)
    if n == 0:
        return mask
    edge = set(lab[0].tolist()) | set(lab[-1].tolist())
    edge |= set(lab[:, 0].tolist()) | set(lab[:, -1].tolist())
    edge.discard(0)

    sizes = np.bincount(lab.ravel())
    limit = max(int(mask.sum() * max_frac), 1)
    fillable = [i for i in range(1, len(sizes))
                if i not in edge and sizes[i] <= limit]
    if not fillable:
        return mask
    return mask | np.isin(lab, fillable)


def largest_region(mask: np.ndarray, keep_ratio: float = 0.12) -> np.ndarray:
    """Keep the biggest region, plus any region at least `keep_ratio` of it.

    The ratio is not zero because plenty of real products are genuinely several
    pieces: a pair of bangles, a lid beside a pot. It is not one either, because
    a stray lobe of misread backdrop is usually far smaller than the product.
    """
    lab, n = label(mask)
    if n <= 1:
        return mask
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    biggest = int(sizes.max())
    keep = [i for i in range(1, len(sizes)) if sizes[i] >= biggest * keep_ratio]
    return np.isin(lab, keep)


def _morph(mask: np.ndarray, k: int, grow: bool) -> np.ndarray:
    """Grow or shrink by `k`, with a plus-shaped neighbourhood each step."""
    out = mask
    for _ in range(k):
        nb = (out,
              np.pad(out[1:], ((0, 1), (0, 0))), np.pad(out[:-1], ((1, 0), (0, 0))),
              np.pad(out[:, 1:], ((0, 0), (0, 1))), np.pad(out[:, :-1], ((0, 0), (1, 0))))
        out = np.logical_or.reduce(nb) if grow else np.logical_and.reduce(nb)
    return out


#: Opening is available but off, because it was measured and it does not pay.
#:
#: The case it was meant for is a lobe of misread backdrop fused to the product,
#: which no component filter can separate. On the porcelain vase, whose lit
#: sweep leaves a vignette behind the object, the lobe survives every radius
#: that leaves the other products intact: at 6 it still holds 33,110 pixels, at
#: 12 still 15,403, and by 10 the brass ewer has lost 1.9 points of frame, which
#: is its spout and handle. Paying real product detail for a defect that stays
#: is a bad trade, so the default is off and the vase is documented as a known
#: limitation instead. Pass a radius explicitly if a particular photograph wants
#: it.
OPEN_RADIUS = 0


def clean(mask: np.ndarray, open_radius: int = OPEN_RADIUS,
          prune: bool = False) -> np.ndarray:
    """Close the small holes inside the product. Nothing else, by default.

    `largest_region` is deliberately NOT applied here, and that is the whole
    lesson of this module. It looks obviously right, because a misread patch of
    backdrop is usually a small separate blob. But fine detail fragments the
    mask too: the silver bracelet's engraved lower band is thin and barely
    darker than the sweep behind it, so it comes back as 1,507 pieces, of which
    exactly one is the body. Pruning to the largest deleted 7,555 pixels across
    1,506 regions, and those pixels were the band. It survived as a broken,
    half-missing arc in every one of the four styles.

    So the rule is inverted: keep everything unless there is a specific reason
    not to. `prune=True` is there for a caller that knows its photograph has a
    detached artefact and no fine detail to lose.
    """
    m = fill_holes(largest_region(mask) if prune else mask)
    if open_radius <= 0:
        return m
    core = largest_region(_morph(m, open_radius, grow=False))
    if not core.any():
        return m
    return _morph(core, open_radius, grow=True) & m
