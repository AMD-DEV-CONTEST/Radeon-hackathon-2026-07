"""Tests for mask post-processing utilities (policycut/vision/masks.py).

Covers: postprocess_mask (hole filling / dilation keeps coverage),
union_with_box (padded box union), and the npz save/load roundtrip used for
analysis/masks/<track_id>.npz.
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

import policycut.vision.masks as masks_mod


def _call_flexible(fn, *args):
    """Call fn(*args) filling any extra required numeric params with defaults."""
    try:
        return fn(*args)
    except TypeError:
        sig = inspect.signature(fn)
        params = list(sig.parameters.values())
        extra = []
        for p in params[len(args):]:
            if p.default is not inspect.Parameter.empty:
                break
            ann = p.annotation
            if ann in (int, float) or p.name.endswith(("_px", "_ms", "px")):
                extra.append(2)
            elif ann is bool:
                extra.append(True)
            else:
                extra.append(2)
        return fn(*args, *extra)


def _as_binary(mask) -> np.ndarray:
    """Normalize a returned mask (bool / uint8 / float feathered) to bool."""
    arr = np.asarray(mask)
    if arr.dtype == bool:
        return arr
    if np.issubdtype(arr.dtype, np.floating):
        return arr > 0.5
    return arr > 0


def _ring_mask(size: int = 80, r_out: int = 20, r_in: int = 6) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Filled circle with a punched hole. Returns (mask, ring, hole)."""
    yy, xx = np.mgrid[0:size, 0:size]
    c = size // 2
    dist2 = (yy - c) ** 2 + (xx - c) ** 2
    disk = dist2 <= r_out**2
    hole = dist2 <= r_in**2
    ring = disk & ~hole
    return ring.copy(), ring, hole


class TestPostprocessMask:
    def test_shape_preserved(self):
        mask, _, _ = _ring_mask()
        out = _call_flexible(masks_mod.postprocess_mask, mask)
        assert np.asarray(out).shape == mask.shape

    def test_holes_filled(self):
        mask, _, hole = _ring_mask()
        out = _as_binary(_call_flexible(masks_mod.postprocess_mask, mask))
        # center of the punched hole must now be inside the mask
        c = mask.shape[0] // 2
        assert out[c, c], "postprocess_mask must fill interior holes"
        assert out[hole].mean() > 0.9

    def test_original_coverage_retained(self):
        mask, ring, _ = _ring_mask()
        out = _as_binary(_call_flexible(masks_mod.postprocess_mask, mask))
        kept = out[ring].mean()
        assert kept > 0.9, f"postprocess must keep original coverage (kept {kept:.2f})"

    def test_empty_mask_stays_effectively_empty(self):
        empty = np.zeros((60, 60), dtype=bool)
        out = _as_binary(_call_flexible(masks_mod.postprocess_mask, empty))
        assert out.sum() <= 4  # allow trivial numeric noise, but nothing meaningful


class TestUnionWithBox:
    def _union(self, mask, box_xywh_norm):
        fn = masks_mod.union_with_box
        h, w = mask.shape
        x, y, bw, bh = box_xywh_norm
        candidates = [
            (mask, (x, y, bw, bh)),
            (mask, [x, y, bw, bh]),
            (mask, {"x": x, "y": y, "w": bw, "h": bh}),
            (mask, (int(x * w), int(y * h), int(bw * w), int(bh * h))),  # pixel box
        ]
        last_exc = None
        for args in candidates:
            try:
                out = _as_binary(_call_flexible(fn, *args))
            except Exception as exc:
                last_exc = exc
                continue
            # accept the first interpretation that actually covers the box center
            cy = int((y + bh / 2) * h)
            cx = int((x + bw / 2) * w)
            if out[cy, cx]:
                return out
        pytest.fail(f"union_with_box did not cover the box under any calling convention: {last_exc}")

    def test_box_region_added(self):
        mask = np.zeros((80, 80), dtype=bool)
        mask[8:14, 8:14] = True  # small pre-existing blob
        out = self._union(mask, (0.5, 0.5, 0.4, 0.4))
        # box center covered (checked by _union) and box interior mostly covered
        assert out[int(0.6 * 80), int(0.6 * 80)]

    def test_existing_mask_retained(self):
        mask = np.zeros((80, 80), dtype=bool)
        mask[8:14, 8:14] = True
        out = self._union(mask, (0.5, 0.5, 0.4, 0.4))
        assert out[10, 10], "union must retain the original mask pixels"

    def test_shape_preserved(self):
        mask = np.zeros((48, 64), dtype=bool)
        out = self._union(mask, (0.25, 0.25, 0.5, 0.5))
        assert out.shape == mask.shape


class TestNpzRoundtrip:
    SAVE_NAMES = ["save_masks", "save_track_masks", "write_masks", "masks_to_npz", "save_npz"]
    LOAD_NAMES = ["load_masks", "load_track_masks", "read_masks", "masks_from_npz", "load_npz"]

    def _find(self, names, verbs):
        for n in names:
            fn = getattr(masks_mod, n, None)
            if callable(fn):
                return fn
        for n in dir(masks_mod):
            if n.startswith("_"):
                continue
            fn = getattr(masks_mod, n)
            if callable(fn) and any(v in n.lower() for v in verbs) and "mask" in n.lower():
                return fn
        pytest.fail(f"no npz mask io function found in policycut.vision.masks (tried {names})")

    def _save(self, path, masks):
        fn = self._find(self.SAVE_NAMES, ("save", "write", "dump"))
        for args in ((path, masks), (masks, path), (str(path), masks), (masks, str(path))):
            try:
                fn(*args)
                return
            except (TypeError, AttributeError):
                continue
        pytest.fail("could not call the mask save function with (path, masks) or (masks, path)")

    def _load(self, path):
        fn = self._find(self.LOAD_NAMES, ("load", "read"))
        try:
            return fn(path)
        except TypeError:
            return fn(str(path))

    @staticmethod
    def _to_dict(loaded) -> dict[float, np.ndarray]:
        if isinstance(loaded, dict):
            return {float(k): np.asarray(v) for k, v in loaded.items()}
        if isinstance(loaded, tuple) and len(loaded) == 2:
            ts, stack = loaded
            return {float(t): np.asarray(m) for t, m in zip(np.asarray(ts).tolist(), stack)}
        # npz-like mapping
        if hasattr(loaded, "files"):
            return {float(k): np.asarray(loaded[k]) for k in loaded.files}
        pytest.fail(f"unrecognized loaded-mask container: {type(loaded)}")

    @staticmethod
    def _rect_mask(h: int, w: int, y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
        """Rectangle mask with even-aligned bounds (survives 2x downsample exactly)."""
        m = np.zeros((h, w), dtype=bool)
        m[y0:y1, x0:x1] = True
        return m

    def test_roundtrip(self, tmp_path):
        # Contract (docs/CONTRACTS.md §12): masks are stored per keyframe at the
        # input resolution DOWNSAMPLED 2x; load returns the stored resolution
        # and callers upscale when applying. Keys are frame indices
        # (frame = round(t * fps) per §0). Even-aligned rectangles make the
        # downsample lossless so content can be checked exactly.
        masks = {
            0: self._rect_mask(40, 60, 10, 30, 20, 48),
            12: self._rect_mask(40, 60, 2, 38, 4, 12),
            25: np.zeros((40, 60), dtype=bool),
        }
        path = tmp_path / "t_0123456789.npz"
        self._save(path, masks)
        assert path.exists() and path.stat().st_size > 0

        loaded = self._to_dict(self._load(path))
        assert len(loaded) == len(masks)
        for t, original in masks.items():
            match_t = min(loaded.keys(), key=lambda k: abs(k - t))
            assert abs(match_t - t) < 1e-3, f"timestamp {t} not found in {sorted(loaded)}"
            got = loaded[match_t]
            h, w = original.shape
            assert got.shape == ((h + 1) // 2, (w + 1) // 2), "stored at 2x-downsampled resolution"
            np.testing.assert_array_equal(got.astype(bool), original[::2, ::2])

    def test_roundtrip_preserves_bool_content_compactly(self, tmp_path):
        # masks are stored as packed/compressed bool arrays; a large empty mask
        # must not explode in size
        masks = {0: np.zeros((360, 640), dtype=bool)}
        path = tmp_path / "t_compact.npz"
        self._save(path, masks)
        assert path.stat().st_size < 200_000
