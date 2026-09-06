"""Turning one generated clip into stills for every format.

The GPU runs once per pack. Everything else is derived from those frames, so
two questions have to be answered here: which frames make good stills, and how
a square-ish generated frame becomes a 9:16 story without clipping the product.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

#: Laplacian. Its response variance is the standard cheap focus measure, and it
#: is what separates a frame mid-motion from one the camera has settled on.
_LAPLACIAN = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)


def sharpness(image: Image.Image) -> float:
    a = np.asarray(image.convert("L"), dtype=np.float32) / 255.0
    lap = (
        _LAPLACIAN[0, 1] * np.roll(a, 1, 0)
        + _LAPLACIAN[2, 1] * np.roll(a, -1, 0)
        + _LAPLACIAN[1, 0] * np.roll(a, 1, 1)
        + _LAPLACIAN[1, 2] * np.roll(a, -1, 1)
        + _LAPLACIAN[1, 1] * a
    )[1:-1, 1:-1]
    return float(lap.var())


def pick_frames(frames: list[Image.Image], k: int) -> list[int]:
    """Pick k frames: spread across the clip, sharpest within each window.

    Spread first, because two stills lifted from adjacent frames are the same
    picture and the seller gets three copies of one creative. Sharpest within
    the window second, because a frame caught mid-push is soft, and a soft
    still is the one thing a printed banner cannot hide.

    The first frame is never eligible: it is the plate the model was given, so
    it shows none of what the model did.
    """
    if k <= 0 or not frames:
        return []
    usable = list(range(1, len(frames))) or [0]
    if k >= len(usable):
        return usable[:k] if len(usable) >= k else usable + [usable[-1]] * (k - len(usable))

    edges = np.linspace(0, len(usable), k + 1).astype(int)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        window = usable[lo:hi] or [usable[min(lo, len(usable) - 1)]]
        out.append(max(window, key=lambda i: sharpness(frames[i])))
    return out


def fit_scene(frame: Image.Image, size: tuple[int, int], feather: float = 24.0) -> Image.Image:
    """Place a generated frame in a format of a different shape.

    Cover-cropping is the usual move and it is wrong here: cropping a square
    frame to 9:16 cuts the sides off, and the product is what lives in the
    middle of those sides. So the frame is scaled to fit whole and the bands
    left over are filled from the frame's own content.

    They are filled by reflection, not by stretching the edge row. Stretching
    works on a plain wash and falls apart on anything with texture: extending a
    bokeh background sideways draws it into long horizontal streaks that read
    immediately as a mistake. Reflecting continues the texture instead, so the
    band looks like more of the same scene, and blurring the join hides the
    mirror line.
    """
    tw, th = size
    scale = min(tw / frame.width, th / frame.height)
    inner = frame.resize((max(int(frame.width * scale), 1), max(int(frame.height * scale), 1)),
                         Image.LANCZOS)
    if inner.size == size:
        return inner.convert("RGB")

    ox, oy = (tw - inner.width) // 2, (th - inner.height) // 2
    a = np.asarray(inner.convert("RGB"), dtype=np.uint8)
    canvas = np.empty((th, tw, 3), dtype=np.uint8)

    def reflect(idx: np.ndarray, n: int) -> np.ndarray:
        if n < 2:
            return np.zeros_like(idx)
        period = 2 * n - 2
        idx = np.mod(idx, period)
        return np.where(idx < n, idx, period - idx)

    ys = reflect(np.arange(th) - oy, inner.height)
    xs = reflect(np.arange(tw) - ox, inner.width)
    canvas[:] = a[ys[:, None], xs[None, :]]

    out = Image.fromarray(canvas, "RGB")
    if feather and (ox or oy):
        # Blur only the stretched bands, so the real frame stays crisp.
        blurred = out.filter(ImageFilter.GaussianBlur(feather))
        mask = Image.new("L", size, 255)
        mask.paste(0, (ox, oy, ox + inner.width, oy + inner.height))
        mask = mask.filter(ImageFilter.GaussianBlur(feather / 2))
        out = Image.composite(blurred, out, mask)
    return out
