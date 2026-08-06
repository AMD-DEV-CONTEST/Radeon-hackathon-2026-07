# -*- coding: utf-8 -*-
"""Inpainting v2 — crop-to-mask SDXL img2img with masked compositing.

Instead of regenerating the whole frame, we crop a padded box around the
brushed region, repaint the crop at SDXL's native resolution, and paste it
back through the soft mask. Local edits stay local and keep full detail.

Note: we deliberately use the base SDXL img2img pipeline rather than the
stable-diffusion-xl-1.0-inpainting-0.1 checkpoint. That checkpoint anchors
hard to the surrounding pixels and ignores prompt colors (verified on
Radeon: a "purple uniform" prompt came back red at any strength). The base
model follows the prompt; the soft-mask composite keeps the edit local.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from PIL import Image

from ..device import Timer, peak_memory_gb, reset_peak_memory
from ..utils import (blur_mask, dilate_mask, expand_bbox, make_generator,
                     mask_bbox, resize_long_edge)

DEFAULT_NEGATIVE = ("blurry, low quality, deformed, bad anatomy, watermark, "
                    "text, signature, jpeg artifacts")

# Negative extras for repaint: the model loves inventing a NEW person when the
# brush covers head+body, and translucent "ghost" cloth where the mask spills
# onto background. Suppress both. Always appended to any user negative.
_REPAINT_EXTRA = ("different person, new face, changed face, ghost, "
                  "translucent, floating objects, disembodied")
REPAINT_NEGATIVE = DEFAULT_NEGATIVE + ", " + _REPAINT_EXTRA


# ---------------------------------------------------------------------------
# Subject gate — clip a sloppy brush mask to the foreground subject.
#
# User brushes are ALWAYS sloppier than the object they mean ("brush the hair"
# also covers face and background). Diffusion/img2img then repaints whatever
# sits under the mask — producing translucent ghosts in the backdrop and
# changed faces (both seen in the wild). BiRefNet already ships with the app
# for cutouts; reusing it as a gate keeps the edit strictly on the subject.
# If the brush clearly targets the backdrop (little overlap with the matte)
# or no subject is found, the original mask is respected untouched.
# ---------------------------------------------------------------------------

def _subject_gate(manager, image: Image.Image, mask: Image.Image):
    """Return (mask, gated). `gated` is True when the brush was clipped."""
    try:
        from ..birefnet import matte
        alpha = matte(manager, image)
    except Exception:
        return mask, False
    subj = np.asarray(alpha.resize(image.size, Image.BILINEAR)) > 96
    frac = float(subj.mean())
    if frac < 0.01 or frac > 0.95:
        return mask, False                       # no clear subject
    m = np.asarray(mask) > 128
    if not m.any():
        return mask, False
    inter = float((m & subj).sum())
    recall = inter / float(subj.sum())           # how much of the subject is brushed
    precision = inter / float(m.sum())           # how much of the brush is subject
    if recall < 0.35 and precision < 0.60:
        return mask, False                       # user edits the backdrop
    dil = max(8, image.width // 96)              # keep hair/edge fringe
    subj_img = dilate_mask(Image.fromarray(subj.astype(np.uint8) * 255), dil)
    gated = np.minimum(np.asarray(mask, dtype=np.uint8),
                       np.asarray(subj_img, dtype=np.uint8))
    return Image.fromarray(gated, "L"), True


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _region_kind(region: str) -> str | None:
    """Classify a region word as living in the UPPER (hair/hat) or LOWER
    (garment) subject zone. Regions without vertical structure (eyes, lips,
    skin, background) return None — the brush alone localizes them."""
    r = (region or "").lower()
    if not r:
        return None
    if any(k in r for k in ("头发", "发丝", "刘海", "hair",
                            "帽", "hat", "cap", "beret")):
        return "hair"
    if any(k in r for k in ("衬衫", "外套", "衣", "裙", "裤", "领", "鞋", "靴",
                            "coat", "shirt", "dress", "jacket", "cloth",
                            "skirt", "pants", "jeans", "hoodie", "sweater",
                            "blouse", "top", "shoe", "boot", "sneaker")):
        return "cloth"
    return None


def _region_prior(region: str, shape: tuple, hard: np.ndarray):
    """Spatial prior from the target's REGION word ("头发" / "外套"…).

    Color-fit alone cannot honor semantics: asked "hair → black" on a
    vividly dyed anime head, the black target finds no dark pixels and the
    vivid one steals the hair instead (acceptance test s09: purple hair!).
    In portrait/bust inputs hair sits in the UPPER part of the masked
    subject and clothes BELOW it, so the region word becomes a soft
    vertical prior. Returns a 0-1 weight map, or None for unknown regions.
    """
    kind = _region_kind(region)
    if kind is None:
        return None
    ys = np.nonzero(hard.any(axis=1))[0]
    if not len(ys):
        return None
    y0, y1 = float(ys.min()), float(ys.max())
    rel = (np.arange(shape[0], dtype=np.float32) - y0)[:, None] / max(y1 - y0, 1.0)
    w_map = _sigmoid((0.58 - rel) * 10.0) if kind == "hair" \
        else _sigmoid((rel - 0.42) * 10.0)
    # materialize to (H, W): callers boolean-index with `prior > 0.5`
    return np.broadcast_to(w_map, (shape[0], shape[1])).copy()


# ---------------------------------------------------------------------------
# Face & skin protection — recoloring must NEVER touch skin or faces.
#
# HSV-only skin guesses fail in both directions (both seen in the wild):
# pale anime faces (v≈0.9, s≈0.1) were veiled gray by "hair → black", and
# real thighs/cleavage inside a dress brush were tinted blue. We therefore
# fuse three independent detectors:
#   1. a YCrCb skin ellipsoid — reliable for real skin, hue-independent,
#      suppressed on very saturated pixels so dyed hair is NOT "skin";
#   2. warm-HSV skin — catches lighter/desaturated skin tones;
#   3. face cascades (anime LBP + Haar frontal/profile) — a semantic
#      "this is a face" signal that works even on flat gray anime skin.
# ---------------------------------------------------------------------------

_FACE_CASCADE: dict = {}


def _cascade(kind: str):
    """Lazy-load a cv2 cascade; returns None when unavailable."""
    if kind in _FACE_CASCADE:
        return _FACE_CASCADE[kind]
    cas = None
    try:
        import cv2
        if kind == "anime":
            path = (Path(__file__).resolve().parents[2]
                    / "assets" / "models" / "lbpcascade_animeface.xml")
        else:
            name = ("haarcascade_frontalface_default.xml" if kind == "haar"
                    else "haarcascade_profileface.xml")
            path = Path(cv2.data.haarcascades) / name
        if path.exists():
            c = cv2.CascadeClassifier(str(path))
            cas = c if not c.empty() else None
    except Exception:
        cas = None
    _FACE_CASCADE[kind] = cas
    return cas


def _looks_cel(img_rgb: Image.Image) -> bool:
    """Cel/anime art detection (measured on the v8 acceptance set):
    cel scans have large near-white flat fills (paper/background) — the
    fraction of s<0.05 pixels is 0.25-0.36 on anime vs ≤0.11 on photos;
    a 24-color quantize top-6 coverage >0.48 is a secondary signal.
    Skin gates must be strict for cel (vivid dyed hair is NOT skin) and
    lenient for photos (sunlit skin is fairly saturated)."""
    small = img_rgb.resize((256, 256))
    hsv = np.asarray(small.convert("HSV"), dtype=np.float32)
    s = hsv[..., 1] / 255.0
    if float((s < 0.05).mean()) > 0.15:
        return True
    q = small.quantize(colors=24).convert("RGB")
    _, counts = np.unique(np.asarray(q).reshape(-1, 3), axis=0,
                          return_counts=True)
    top6 = np.sort(counts)[::-1][:6].sum()
    return float(top6) / float(counts.sum()) > 0.48


def _face_soft_mask(img_rgb: Image.Image, warm: np.ndarray) -> np.ndarray:
    """Soft 0-1 elliptical mask over detected faces (zeros when none found).
    `warm` (HSV skin map) is used to reject phantom boxes — cascades fire
    on clothing folds, and a phantom ellipse over the torso blocks garment
    recoloring entirely (acceptance v8: coat stayed gray)."""
    wid, hgt = img_rgb.size
    out = np.zeros((hgt, wid), dtype=np.float32)
    try:
        import cv2
        gray = cv2.cvtColor(np.asarray(img_rgb), cv2.COLOR_RGB2GRAY)
        eq = cv2.equalizeHist(gray)
        boxes = []
        # anime LBP needs scaleFactor 1.05 — at 1.1 it steps over the face
        for kind, src, nb, sf in (("anime", eq, 5, 1.05), ("haar", gray, 5, 1.1),
                                  ("profile", gray, 5, 1.1)):
            cas = _cascade(kind)
            if cas is None:
                continue
            for (x, y, w, hh) in cas.detectMultiScale(
                    src, scaleFactor=sf, minNeighbors=nb, minSize=(36, 36)):
                boxes.append((x, y, w, hh))
        if boxes:
            # content check: a real face box is warm-skin-heavy in its
            # central 60 %; a torso/fabric phantom is not.
            def _box_warm(b):
                x, y, w, hh = b
                mx, my = int(w * 0.2), int(hh * 0.2)
                xa, ya = max(0, x + mx), max(0, y + my)
                xb, yb = min(wid, x + w - mx), min(hgt, y + hh - my)
                if xb <= xa or yb <= ya:
                    return 0.0
                return float(warm[ya:yb, xa:xb].mean())
            kept = [b for b in boxes if _box_warm(b) > 0.18]
            if not kept:
                # ambiguous evidence: trust only the topmost detection,
                # and only if it shows at least some skin
                top = min(boxes, key=lambda b: b[1])
                if _box_warm(top) > 0.10:
                    kept = [top]
            boxes = kept
        if boxes:
            yy, xx = np.mgrid[0:hgt, 0:wid].astype(np.float32)
            for (x, y, w, hh) in boxes:
                cx, cy = x + w / 2.0, y + hh * 0.45   # bias up: box has hair
                rx, ry = w * 0.62, hh * 0.68
                e = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
                blob = np.clip(1.8 - 1.5 * e, 0.0, 1.0)
                blob = blob * (yy < (y + hh * 1.15))  # never reach the torso
                out = np.maximum(out, blob)
    except Exception:
        pass
    return out


def _protect_mask(img_rgb: Image.Image):
    """Return (guard_map, (h, s, v)): guard_map is a 0-1 'do NOT recolor'
    weight over faces and skin."""
    h, s, v = _hsv_arrays(img_rgb)
    cel = _looks_cel(img_rgb)
    # Warm-HSV skin. Cel art: HARD cap at s≈0.30 — anime skin is s≈0.1,
    # dyed hair s≥0.45, so the separation is clean; anything vivid stays
    # recolorable. Photos: soft high cap so sunlit/orange-lit skin
    # (s≈0.5) stays protected (v8 acceptance: arm tinted blue).
    if cel:
        warm = (((h > 5.0) & (h < 48.0)).astype(np.float32)
                * _sigmoid((s - 0.11) * 30.0)
                * (1.0 - _sigmoid((s - 0.30) * 16.0))
                * _sigmoid((v - 0.32) * 16.0))
    else:
        warm = (((h > 5.0) & (h < 52.0)).astype(np.float32)
                * _sigmoid((s - 0.11) * 30.0)
                * (1.0 - _sigmoid((s - 0.58) * 12.0))
                * _sigmoid((v - 0.32) * 16.0))
    skin = warm
    if cel:
        # pale anime skin sits at s≈0.11, v≈0.96 — exactly between the
        # warm gate's knees (v8 acceptance: gray smudge on cheeks). Cel
        # only: on photos this would shield white satin dresses.
        pale = (_sigmoid((0.16 - s) * 20.0) * _sigmoid((v - 0.85) * 20.0)
                * ((h > 5.0) & (h < 45.0)).astype(np.float32))
        skin = np.maximum(skin, pale)
    try:
        import cv2
        ycc = cv2.cvtColor(np.asarray(img_rgb), cv2.COLOR_RGB2YCrCb) \
            .astype(np.float32)
        cr, cb = ycc[..., 1], ycc[..., 2]      # Y,Cr,Cb channel order!
        dcd_cap = 62.0 if cel else 72.0
        ycrcb = (_sigmoid((cr - 133.0) / 4.0) * _sigmoid((176.0 - cr) / 5.0)
                 * _sigmoid((cb - 80.0) / 3.5) * _sigmoid((132.0 - cb) / 4.0)
                 * _sigmoid(((cr - cb) - 8.0) / 3.0)
                 * _sigmoid((dcd_cap - (cr - cb)) / 5.0))
        # vividly dyed pixels (orange/pink hair) trip the YCrCb ellipsoid but
        # are NOT skin — suppress by saturation. Cel art: full veto above
        # s≈0.45. Photos: 0.75 discount (sunlit skin is saturated too).
        ycrcb = ycrcb * ((1.0 - _sigmoid((s - 0.45) * 18.0)) if cel
                         else (1.0 - 0.75 * _sigmoid((s - 0.55) * 14.0)))
        skin = np.maximum(skin, ycrcb)
    except Exception:
        pass
    face = _face_soft_mask(img_rgb, warm)
    if float(face.max()) > 0:
        if cel:
            # the face ellipse spills onto hair/chest — restrict it to
            # face-colored or near-neutral pixels and never to vivid ones
            # (dyed bangs, bows, teal collars are NOT face).
            hue_gate = np.maximum(
                ((h > 3.0) & (h < 45.0)).astype(np.float32),
                1.0 - _sigmoid((s - 0.08) * 20.0))
            face = face * hue_gate * (1.0 - _sigmoid((s - 0.42) * 16.0))
        skin = np.maximum(skin, _sigmoid((face - 0.45) * 16.0))
    # Confidence lift: pixels the detectors are sure about (>0.55) snap
    # toward full protection, so "protected" really means zero change.
    skin = np.maximum(skin, _sigmoid((skin - 0.55) * 18.0))
    return np.clip(skin, 0.0, 1.0), (h, s, v)

# ---------------------------------------------------------------------------
# Recolor mode — pure hue-shift recoloring, no diffusion.
#
# AI repaint (img2img) always trades off: low strength keeps the old color,
# high strength repaints the style too. For the extremely common "same item,
# different color" edit we instead rotate the hue inside the mask, keeping
# saturation/value (shading, folds, lineart) 100 % intact. Runs in <1 s.
# ---------------------------------------------------------------------------

# chromatic targets: word → hue degrees
_CHROMA = {
    "sky blue": 200, "skyblue": 200,
    "red": 0, "crimson": 348, "scarlet": 6, "vermilion": 12, "coral": 14,
    "orange": 25, "amber": 38,
    "yellow": 55, "lemon": 58, "gold": 45, "golden": 45, "khaki": 55,
    "green": 125, "emerald": 145, "lime": 85, "olive": 70, "mint": 150,
    "teal": 175, "cyan": 185, "turquoise": 172, "aqua": 180,
    "blue": 225, "navy": 232, "azure": 205, "cobalt": 215, "indigo": 248,
    "purple": 275, "violet": 265, "lavender": 258, "lilac": 270, "plum": 305,
    "magenta": 300, "fuchsia": 300, "pink": 332, "rose": 340,
    "brown": 22, "maroon": 350, "burgundy": 345,
    # 复合词（必须长于单字词条，靠 end-position 取胜）
    "navy blue": 232, "royal blue": 225, "dark blue": 240, "light blue": 195,
    "baby blue": 200, "ice blue": 190, "hot pink": 330, "deep purple": 270,
    "dark red": 0, "wine red": 345, "bright red": 0, "rose red": 340,
    "dark green": 120, "light green": 120, "olive green": 75,
    # 中文
    "红": 0, "橙": 25, "橘": 25, "黄": 55, "金": 45, "绿": 125,
    "青": 180, "蓝": 225, "靛": 248, "紫": 275, "粉": 332, "玫": 340,
    "棕": 22, "褐": 22,
    # 中文复合
    "深蓝": 232, "藏蓝": 232, "浅蓝": 195, "天蓝": 200, "湖蓝": 195,
    "宝蓝": 225, "深紫": 270, "浅紫": 280, "粉红": 332, "浅粉": 340,
    "玫红": 330, "深红": 0, "墨绿": 150, "深绿": 130, "浅绿": 120,
    "金黄": 48,
}
_ACHROMA = {"black": "black", "white": "white", "gray": "gray",
            "grey": "gray", "silver": "gray",
            "黑": "black", "白": "white", "灰": "gray", "银": "gray"}


_LATIN_CONN = re.compile(r"(?:^|[\s,;])(?:with|to|into|by)\s*$")
_CN_CONN = ("成", "为", "→")


def _parse_target_color(prompt: str):
    """Return (word, hue_deg | None, achroma_kind | None) for the TARGET color
    in the prompt, else None.

    When several color words appear ("replace the red shirt with purple"),
    the target is the one after a connector (with/to/into/成/为/→); otherwise
    the last color word wins — replace-style phrasing always puts the desired
    color last.  Single-color prompts are unaffected.
    """
    text = prompt.lower()
    matches = []  # (pos, word, hue, achroma)
    for table, is_chroma in ((_CHROMA, True), (_ACHROMA, False)):
        for word, val in table.items():
            if ord(word[0]) < 128:  # latin → word boundary
                ms = list(re.finditer(r"\b" + re.escape(word) + r"\b", text))
            else:
                ms = list(re.finditer(re.escape(word), text))
            for m in ms:
                matches.append((m.start(), word, val if is_chroma else None,
                                None if is_chroma else val))
    if not matches:
        return None
    matches.sort(key=lambda x: x[0])
    anchored = [m for m in matches
                if _LATIN_CONN.search(text[:m[0]])
                or text[:m[0]].rstrip().endswith(_CN_CONN)]
    # "last color word" by end position, so the phrase "navy blue" (ends 17)
    # beats its own tail "blue" (ends 14) in e.g. "make it navy blue".
    best = anchored[0] if anchored else max(
        matches, key=lambda m: (m[0] + len(m[1]), len(m[1])))
    return best[1], best[2], best[3]


def _hsv_arrays(img_rgb: Image.Image):
    """uint8 HSV arrays via PIL (H,S,V ∈ [0,255])."""
    hsv = np.asarray(img_rgb.convert("HSV"), dtype=np.float32)
    return hsv[..., 0] * (360.0 / 255.0), hsv[..., 1] / 255.0, hsv[..., 2] / 255.0


def _hsv_to_rgb(h: np.ndarray, s: np.ndarray, v: np.ndarray) -> Image.Image:
    hsv = np.stack([h * (255.0 / 360.0), s * 255.0, v * 255.0], axis=-1)
    return Image.fromarray(hsv.clip(0, 255).astype(np.uint8), "HSV").convert("RGB")


def run_recolor(image: Image.Image, mask: Image.Image, prompt: str,
                region: str = ""):
    """Hue-shift the masked region toward the color named in `prompt`.
    Returns (result_image, perf_dict)."""
    parsed = _parse_target_color(prompt)
    if parsed is None:
        raise ValueError(
            "Recolor mode needs a color word in the prompt, e.g. \"purple\", "
            "\"navy blue\", \"pink\" (or 中文：紫、蓝、黑…).")
    word, target_h, achroma = parsed

    img = image.convert("RGB")
    m = np.asarray(blur_mask(mask, 4.0), dtype=np.float32) / 255.0  # soft mask
    if m.max() <= 0:
        raise ValueError("Empty mask — brush the area you want to recolor first.")
    skin, (h, s, v) = _protect_mask(img)
    guard = 1.0 - skin          # faces & skin stay 100 % untouched
    hard = m > 0.5
    prior = _region_prior(region, v.shape, hard) if region else None
    # A region word ("dress", "hair") fences the recolor into its vertical
    # zone; a 15 % leak keeps the boundary soft instead of a hard cut.
    fence = (0.15 + 0.85 * prior) if prior is not None else 1.0

    with Timer() as t:
        # Judge the source material on NON-SKIN pixels only: a dress brush
        # always catches cleavage/thighs, and their warm saturation used to
        # push the transform decision into the wrong path.
        pool = hard & (skin < 0.5) & (v > 0.15)
        if not pool.any():
            pool = hard & (v > 0.15)
        med_sat = float(np.median(s[pool])) if pool.any() else 0.0
        val_gate = np.clip((v - 0.04) / 0.12, 0.0, 1.0)  # keep dark lineart

        if achroma is not None:
            # black / white / gray: desaturate + remap value, KEEP TEXTURE.
            # A gamma curve preserves relative shading (highlights stay
            # brighter than shadows), a paper gate spares near-white
            # background, and a line gate keeps dark lineart dark for
            # white/gray targets.
            paper = (np.clip((v - 0.94) / 0.06, 0.0, 1.0)
                     * np.clip((0.10 - s) / 0.08, 0.0, 1.0))
            paper_gate = 1.0 - paper
            line_gate = np.clip((v - 0.05) / 0.13, 0.0, 1.0)   # 0 on v≤0.05
            if achroma == "black":
                # s*0.05 kills residual hue so dyed material reads BLACK,
                # not brown; the gamma keeps strand shading readable.
                t_s = s * 0.05
                t_v = (v ** 2.4) * 0.38
                alpha = m * paper_gate
            elif achroma == "white":
                t_s = s * 0.08
                t_v = v + (1.0 - v) * 0.8
                alpha = m * line_gate
            else:  # gray / silver
                t_s = s * 0.12
                t_v = (v ** 1.4) * 0.45 + 0.28
                alpha = m * line_gate * paper_gate
            alpha = alpha * guard * fence
            mode_desc = f"achroma→{achroma}"
        elif med_sat < 0.16:
            # gray/white item → tint: force hue & lift saturation.
            # tint_gate: dark pixels (v<0.10: hair, lineart, deep shadows)
            # must NOT take the tint — a brushed white dress always has dark
            # hair strands across it, and tinting them blue looks like a
            # marker accident (seen in acceptance testing on s03).
            tint_gate = np.clip((v - 0.10) / 0.18, 0.0, 1.0)
            t_h = np.full_like(h, target_h)
            t_s = np.maximum(s, 0.6)
            t_v = v
            alpha = m * tint_gate * guard * fence
            mode_desc = "tint (low-sat source)"
        else:
            # colored item → rotate hue by the shortest arc; skin pixels are
            # excluded from the source-hue estimate AND from the result.
            w_sat = s[hard] * m[hard] * guard[hard]
            ang = np.deg2rad(h[hard])
            if w_sat.sum() > 1e-6:
                mean_ang = np.arctan2((w_sat * np.sin(ang)).sum(),
                                      (w_sat * np.cos(ang)).sum())
                src_h = float(np.rad2deg(mean_ang)) % 360.0
            else:
                src_h = 0.0
            delta = ((target_h - src_h + 540.0) % 360.0) - 180.0
            t_h = (h + delta) % 360.0
            # dusty/gray sources (s 0.16-0.45) keep their shading but need a
            # saturation floor — rotating a washed-out teal by hue alone
            # yields an invisible pastel instead of the requested color.
            t_s = np.maximum(s, 0.45) if med_sat < 0.45 else s
            t_v = v
            sat_gate = np.clip((s - 0.06) / 0.14, 0.0, 1.0)  # keep grays/whites
            alpha = m * sat_gate * val_gate * guard * fence
            mode_desc = f"hue-rotate {delta:+.0f}°"

        if achroma is not None:
            t_h = h  # hue irrelevant once desaturated
        recolored = np.asarray(_hsv_to_rgb(t_h % 360.0, t_s.clip(0, 1),
                                           t_v.clip(0, 1)), dtype=np.float32)
        orig = np.asarray(img, dtype=np.float32)
        a = alpha[..., None]
        out = orig * (1.0 - a) + recolored * a
        result = Image.fromarray(out.clip(0, 255).astype(np.uint8), "RGB")

    perf = {
        "Mode": f"Recolor ({mode_desc})",
        "Target color": f"{word}" + (f" ({target_h}°)" if target_h is not None else ""),
        "Time": f"{t.elapsed:.2f} s (no GPU — instant)",
        "Mask coverage": f"{float((m > 0.5).mean()) * 100:.1f}% of frame",
        "Source median saturation": f"{med_sat:.2f}",
        "Face/skin guard": "on (YCrCb + HSV + face cascade)",
        "Region fence": region or "off",
    }
    return result, perf


def _blend_hsv(out: np.ndarray, t_h, t_s, t_v,
               alpha: np.ndarray) -> np.ndarray:
    """Composite transformed HSV pixels into `out` (float RGB) via `alpha`."""
    recolored = np.asarray(_hsv_to_rgb(t_h % 360.0, t_s.clip(0, 1),
                                       t_v.clip(0, 1)), dtype=np.float32)
    a = alpha[..., None]
    return out * (1.0 - a) + recolored * a


def run_recolor_multi(image: Image.Image, mask: Image.Image,
                      targets: list[dict]):
    """Several color targets inside ONE brushed region, e.g.
    "shirt purple + hair black" → targets=[{region:shirt,color:purple},
    {region:hair,color:black}].

    A diffusion repaint of the whole mask cannot bind multiple attributes
    (it painted the hair purple AND invented a ghost person in the backdrop
    during acceptance testing). Instead each pixel of the (subject-gated)
    mask is assigned to the target it fits best — dark targets take dark
    pixels, vivid targets take saturated pixels — and every subset gets a
    plain hue/value transform. Lineart, shading and identity stay 100 %
    intact, the backdrop is untouched, and it runs in ~1 s.
    """
    parsed: list[tuple[str, str, float | None, str | None]] = []
    for t in targets or []:
        if isinstance(t, dict):
            region, cword = str(t.get("region", "")), str(t.get("color", ""))
        else:
            region, cword = "", str(t)
        p = _parse_target_color(cword)
        if p:
            parsed.append((region, p[0], p[1], p[2]))
    if len(parsed) < 2:
        raise ValueError("recolor_multi needs ≥2 parseable color targets.")
    parsed = parsed[:4]

    img = image.convert("RGB")
    m = np.asarray(blur_mask(mask, 4.0), dtype=np.float32) / 255.0
    if m.max() <= 0:
        raise ValueError("Empty mask — brush the areas you want to recolor first.")
    h, s, v = _hsv_arrays(img)
    hard = m > 0.5

    with Timer() as t:
        out = np.asarray(img, dtype=np.float32)
        rem = m.copy()          # unassigned soft-mask mass
        paper = (np.clip((v - 0.94) / 0.06, 0.0, 1.0)
                 * np.clip((0.10 - s) / 0.08, 0.0, 1.0))
        paper_gate = 1.0 - paper
        val_gate = np.clip((v - 0.04) / 0.12, 0.0, 1.0)
        sat_gate = np.clip((s - 0.06) / 0.14, 0.0, 1.0)
        applied = []

        # Assignment pivots from the masked pixel population. EXTREME
        # quantiles (not the median) so ambiguous pixels — skin, shading —
        # fall below the sigmoid pivot and stay UNCHANGED instead of being
        # dragged into the nearest target (a median pivot tinted the face
        # purple in testing). The dark/bright pivots are additionally CAPPED:
        # with lots of truly dark hair in the mask, the raw 35% quantile lands
        # at v≈0.55 and "black" starts owning the shaded folds of vivid red
        # cloth (v 0.4-0.55), blocking the purple target from the shirt.
        q = lambda a, p: float(np.quantile(a[hard], p))
        p65_s, p20_s = q(s, 0.65), q(s, 0.20)
        p35_v = min(q(v, 0.35), 0.40)
        p65_v = max(q(v, 0.65), 0.72)
        # vividly saturated pixels are never "black"/"gray" material — a
        # shaded red fold is still RED cloth, not a dark object.
        vivid_penalty = 1.0 - _sigmoid((s - 0.60) * 18.0)

        # Achroma targets (black/white/gray) claim pixels FIRST. A chroma
        # target is then kept away from everything an achroma target owns —
        # plus a dilated fringe — otherwise anti-aliased hair edges (reddish,
        # saturated, bright) get hue-rotated into a glowing magenta halo
        # around the blackened hair (seen in acceptance testing).
        order = sorted(range(len(parsed)),
                       key=lambda j: 0 if parsed[j][3] else 1)
        achroma_claim = np.zeros_like(v)
        fringe_px = max(10, img.width // 64)
        mask_mass = float(m.sum())
        # Fused YCrCb + HSV + face-cascade protection: pale anime faces and
        # real skin survive even inside the hair zone (acceptance s09 veiled
        # the face gray; v8 acceptance: face/skin pixel diff must be 0).
        skin, _ = _protect_mask(img)

        def _zone_dhue(prior):
            """Angular distance to the DOMINANT dyed hue of a prior zone.
            Accessories (red bows on orange hair) sit far from the dominant
            cluster and must survive "hair → black"."""
            zone = (prior > 0.5) & hard
            zsat = s[zone] * m[zone]
            if float(zsat.sum()) <= 1e-6:
                return None
            ang = np.deg2rad(h[zone])
            med = float(np.rad2deg(np.arctan2(
                float((zsat * np.sin(ang)).sum()),
                float((zsat * np.cos(ang)).sum())))) % 360.0
            dh = np.abs(h - med)
            return np.minimum(dh, 360.0 - dh)

        for j in order:
            region, word, t_hue, achroma = parsed[j]
            prior = _region_prior(region, v.shape, hard)
            # --- pixel→target assignment weight --------------------------
            if achroma == "black":
                w_sel = (_sigmoid((p35_v - v) * 25.0)     # darkest pixels
                         * vivid_penalty)
                if prior is not None:
                    # explicit "头发 → 黑": the user TOLD us this region is
                    # hair. Restrict the dark-pixel claim to the hair zone —
                    # a dark coat in the lower frame is NOT hair (acceptance
                    # v4: coat bottom blackened). Then claim the whole hair
                    # zone even when vividly dyed: hair zone × (dyed|dark),
                    # never skin.
                    w_sel = w_sel * (0.2 + 0.8 * prior)
                    # Dyed claim follows the zone's DOMINANT hue only: red
                    # bows/ribbons on orange hair are accessories, not hair,
                    # and stay untouched (v8 acceptance).
                    dh = _zone_dhue(prior)
                    dyed = _sigmoid((s - 0.45) * 20.0)
                    if dh is not None:
                        # tight window (measured): orange hair dh≤8°, red
                        # bows dh≈12°+ — accessories stay untouched
                        dyed = dyed * _sigmoid((8.0 - dh) * 0.8)
                    # dark claim: only hue-matching shadows or near-black
                    # lineart — a red bow's dark folds are NOT hair shadow
                    dark = _sigmoid((0.45 - v) * 12.0)
                    if dh is not None:
                        dark = dark * np.maximum(
                            _sigmoid((8.0 - dh) * 0.4),
                            _sigmoid((0.28 - v) * 25.0))
                    claim_hair = (prior * np.maximum(dyed, dark)
                                  * (1.0 - skin))
                    w_sel = np.maximum(w_sel, claim_hair)
                    # Silver/white/pastel hair is NEITHER dyed (s<0.45) NOR
                    # dark — without this it survives "hair → black" entirely
                    # (acceptance s07: white hair untouched). Claim bright,
                    # low-sat pixels in the hair zone; colored eyes (s>0.35)
                    # and pure white backdrop (paper) stay out.
                    bright_hair = (prior * _sigmoid((v - 0.60) * 10.0)
                                   * (1.0 - _sigmoid((s - 0.35) * 20.0))
                                   * (1.0 - skin) * (1.0 - paper))
                    w_sel = np.maximum(w_sel, bright_hair)
                    # Long strands (twintails) drop below the vertical prior:
                    # extend to pixels matching the hair zone's dominant hue
                    # AND clearly dyed (s>0.45) — skin (s≈0.2), gray cloth
                    # and far-hue accessories can't be mis-claimed.
                    if dh is not None:
                        strand = (_sigmoid((s - 0.45) * 20.0)
                                  * _sigmoid((8.0 - dh) * 0.8)
                                  * (1.0 - skin))
                        w_sel = np.maximum(w_sel, strand)
            elif achroma == "white":
                w_sel = (_sigmoid((v - p65_v) * 25.0)     # brightest pixels
                         * (1.0 - sat_gate))              # not already colorful
            elif achroma is not None:                     # gray/silver: mid
                w_sel = (_sigmoid((0.25 - np.abs(v - 0.5)) * 20.0)
                         * sat_gate * vivid_penalty)
            else:
                # Prefer vividly saturated items (hue rotate). Only when the
                # target finds almost NO vivid material do we also tint
                # bright unsaturated cloth — otherwise "shirt purple" would
                # splash the white skirt/scarf standing next to the red shirt.
                w_sat = _sigmoid((s - p65_s) * 25.0)
                claimed = float((rem * w_sat).sum())
                if claimed < 0.05 * mask_mass:
                    w_tint = (_sigmoid((p20_s + 0.05 - s) * 25.0)
                              * _sigmoid((v - 0.55) * 12.0))
                    w_sel = np.maximum(w_sat, w_tint)
                else:
                    w_sel = w_sat
                if achroma_claim.max() > 0:
                    # Block chroma near achroma-owned pixels — but only for
                    # LOW-SATURATION pixels. The halo we are suppressing lives
                    # on washed-out anti-aliased hair edges (s≈0.2-0.5); a
                    # vividly saturated shirt panel (s≈0.75) draped by hair is
                    # legitimate chroma material and must not be fenced out.
                    claim = np.asarray(dilate_mask(
                        Image.fromarray(
                            ((achroma_claim > 0.4) * 255).astype(np.uint8)),
                        fringe_px), dtype=np.float32) / 255.0
                    claim = claim * (1.0 - _sigmoid((s - 0.55) * 20.0))
                    w_sel = w_sel * (1.0 - claim)
                if prior is not None:
                    # Soft region fence: "外套 → 紫" must not veil the face
                    # and neck above the coat line (the tint fallback
                    # splashed skin purple in acceptance testing). A 15 %
                    # leak keeps transitions natural; skin is fenced hard.
                    w_sel = (w_sel * (0.15 + 0.85 * prior)
                             * (1.0 - 0.9 * skin))
                    # Direct cloth claim: a gray/dusty garment (hoodie,
                    # cardigan) is neither vivid NOR bright-white, so both
                    # w_sat and the tint fallback miss it and the color never
                    # lands (acceptance s09: coat stayed gray-green). With an
                    # explicit cloth region word, claim the zone's colored
                    # non-skin fabric directly, minus what achroma targets
                    # already own. The s>0.07 floor claims gray cloth
                    # (s≈0.15), while the v<0.88 ceiling — not the old s
                    # floor — is what keeps near-white fabric (camisole,
                    # blouse lining) white. The s<0.35 ceiling keeps vivid
                    # nearby accents (choker s≈0.40, bow, dyed-strand
                    # leftovers) OUT — they hijacked the subset mean hue in
                    # v4 (src_h 27° → collar rotated to green).
                    direct = (prior * (1.0 - skin)
                              * _sigmoid((s - 0.07) * 25.0)
                              * (1.0 - _sigmoid((s - 0.35) * 18.0))
                              * _sigmoid((v - 0.25) * 12.0)
                              * _sigmoid((0.88 - v) * 15.0))
                    if achroma_claim.max() > 0:
                        direct = direct * (1.0 - np.clip(achroma_claim * 2.0,
                                                         0.0, 1.0))
                    w_sel = np.maximum(w_sel, direct * 0.85)
            sel = rem * w_sel
            rem = rem * (1.0 - w_sel)
            if achroma is not None:
                achroma_claim = np.maximum(achroma_claim, sel)

            # --- per-target transform (same curves as single recolor) ----
            if achroma == "black":
                alpha = sel * paper_gate
                # crush hard: s*0.35 / v*0.42 left vividly dyed hair reading
                # BROWN (acceptance s09: orange twintails stayed brown).
                # s*0.05 kills the warm residual hue so it reads BLACK, and
                # the squared alpha pulls partial claims (dyed hair ~0.66)
                # up to ~0.89 so the black actually lands.
                a2 = 1.0 - (1.0 - alpha) ** 2
                out = _blend_hsv(out, h, s * 0.05, (v ** 2.6) * 0.36, a2)
            elif achroma == "white":
                alpha = sel * np.clip((v - 0.05) / 0.13, 0.0, 1.0)
                out = _blend_hsv(out, h, s * 0.08, v + (1.0 - v) * 0.8,
                                 alpha)
            elif achroma is not None:  # gray / silver
                alpha = (sel * np.clip((v - 0.05) / 0.13, 0.0, 1.0)
                         * paper_gate)
                out = _blend_hsv(out, h, s * 0.12,
                                 (v ** 1.4) * 0.45 + 0.28, alpha)
            else:
                # hue-rotate by the weighted mean hue of THIS subset. With a
                # region prior, weight by it as well, and fence out anything
                # an achroma target even PARTIALLY owns: scattered vivid
                # crumbs (bow, dyed-strand leftovers) must not drag src_h off
                # the garment body color (acceptance v4: coat mean hijacked
                # to 27°, the collar rotated green).
                wsub = s * sel * (prior if prior is not None else 1.0)
                if achroma_claim.max() > 0:
                    wsub = wsub * (1.0 - np.clip(achroma_claim * 2.0,
                                                 0.0, 1.0))
                ang = np.deg2rad(h)
                if float(wsub.sum()) > 1e-6:
                    src_h = float(np.rad2deg(np.arctan2(
                        float((wsub * np.sin(ang)).sum()),
                        float((wsub * np.cos(ang)).sum())))) % 360.0
                else:
                    src_h = 0.0
                delta = ((t_hue - src_h + 540.0) % 360.0) - 180.0
                # low-sat source (gray/white cloth) needs a tint, not a rotate
                sub_hard = sel > 0.3
                sub_med_s = float(np.median(s[sub_hard])) if sub_hard.any() else 0.0
                if sub_med_s < 0.16:
                    # same dark-hair guard as single recolor: dark strands
                    # across a light garment must not take the tint.
                    tint_gate = np.clip((v - 0.10) / 0.18, 0.0, 1.0)
                    alpha = sel * tint_gate
                    out = _blend_hsv(out, np.full_like(h, t_hue),
                                     np.maximum(s, 0.6), v, alpha)
                else:
                    alpha = sel * sat_gate * val_gate
                    # same saturation floor as single recolor: dusty teal /
                    # gray cloth must show the requested color, not a pastel
                    t_s2 = np.maximum(s, 0.45) if sub_med_s < 0.45 else s
                    out = _blend_hsv(out, (h + delta) % 360.0, t_s2, v,
                                     alpha)
            applied.append(f"{region or 'region'}→{word}")

        result = Image.fromarray(out.clip(0, 255).astype(np.uint8), "RGB")

    perf = {
        "Mode": "Recolor multi-target (pixel-assigned)",
        "Targets": ", ".join(applied),
        "Time": f"{t.elapsed:.2f} s (no GPU — instant)",
        "Mask coverage": f"{float(hard.mean()) * 100:.1f}% of frame",
    }
    return result, perf


def _crop_for_inpaint(image: Image.Image, mask: Image.Image, target: int):
    """Crop a padded bbox around the mask; resize crop so its long edge is
    `target` (upscaling small regions for detail, capping large ones).

    The crop is then edge-padded to the nearest SDXL native bucket. ROCm /
    MIOpen autotunes convolution kernels PER INPUT SHAPE — a one-time ~6 min
    stall for every unseen size (seen in the wild as '336 s, 42 s/step').
    Restricting ourselves to 7 canonical shapes means that tax is paid once
    per bucket ever (and the startup warmup pre-pays it)."""
    bbox = mask_bbox(mask)
    if bbox is None:
        raise ValueError("Empty mask — brush the area you want to change first.")
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = max(48, int(0.35 * max(bw, bh)))
    box = expand_bbox(bbox, image.size, pad)
    crop_img = image.crop(box)
    crop_mask = mask.crop(box)
    crop_img = resize_long_edge(crop_img, target, multiple=16, upscale_min=target)
    crop_mask = crop_mask.resize(crop_img.size, Image.NEAREST)

    # --- bucket the shape (fit inside + edge-replicate pad, never crop) ---
    from .background import _native_bucket
    tw, th = _native_bucket(*crop_img.size)
    scale = min(tw / crop_img.width, th / crop_img.height)
    fw = max(16, round(crop_img.width * scale / 16) * 16)
    fh = max(16, round(crop_img.height * scale / 16) * 16)
    fit_img = crop_img.resize((fw, fh), Image.LANCZOS)
    fit_mask = crop_mask.resize((fw, fh), Image.NEAREST)
    arr = np.asarray(fit_img)
    canvas = np.zeros((th, tw, 3), dtype=np.uint8)
    canvas[:fh, :fw] = arr
    if tw > fw:
        canvas[:fh, fw:] = arr[:, -1:]
    if th > fh:
        canvas[fh:, :] = canvas[fh - 1:fh, :]
    bucket_img = Image.fromarray(canvas)
    bucket_mask = Image.new("L", (tw, th), 0)
    bucket_mask.paste(fit_mask, (0, 0))
    return bucket_img, bucket_mask, box, (fw, fh)


def run_inpaint(manager, image: Image.Image, mask: Image.Image,
                prompt: str, negative: str = "", strength: float = 0.85,
                steps: int = 30,
                guidance: float = 7.5, seed: int = -1, fast: bool = False,
                mode: str = "ai", targets: list | None = None,
                region: str = ""):
    """Returns (result_image, perf_dict, used_seed).

    mode="recolor"       → pure hue-shift recolor (keeps lines & shading,
                           instant, no diffusion).
    mode="recolor_multi" → pixel-assigned multi-target recolor (several color
                           targets in one brush; `targets` = [{region,color}]).
    mode="ai"            → SDXL img2img repaint (design/material changes).
    """
    if image is None or mask is None:
        raise ValueError("Please upload an image and brush a mask first.")
    if mode != "recolor_multi" and not (prompt or "").strip():
        raise ValueError("Please enter a prompt describing the desired content.")

    # Clip sloppy brushes to the foreground subject so edits never bleed into
    # the backdrop (ghost artifacts) — see _subject_gate.
    mask, gated = _subject_gate(manager, image, mask)

    if mode == "recolor":
        result, perf = run_recolor(image, mask, prompt, region=region)
        perf["Subject gate"] = "on (BiRefNet)" if gated else "off"
        return result, perf, -1

    if mode == "recolor_multi":
        result, perf = run_recolor_multi(image, mask, targets or [])
        perf["Subject gate"] = "on (BiRefNet)" if gated else "off"
        return result, perf, -1

    s = manager.settings
    pipe = manager.get_img2img_pipe()
    manager.set_lcm(pipe, fast)

    crop_img, crop_mask, box, fit_size = _crop_for_inpaint(image, mask, s.inpaint_crop_size)

    gen, used_seed = make_generator("cuda" if manager.info.is_gpu else "cpu", seed)
    n_steps = (s.lcm_repaint_steps if mode == "ai" else s.lcm_steps) if fast else int(steps)
    cfg = s.lcm_guidance if fast else float(guidance)

    reset_peak_memory()
    with Timer() as t:
        neg = ((negative.rstrip(", ") + ", " + _REPAINT_EXTRA)
               if (negative or "").strip() else REPAINT_NEGATIVE)
        out = pipe(
            prompt=prompt,
            negative_prompt=neg,
            image=crop_img,
            strength=max(0.3, min(1.0, float(strength))),
            num_inference_steps=n_steps,
            guidance_scale=cfg,
            generator=gen,
        ).images[0]

    # Drop the bucket padding, then paste the regenerated crop back into the
    # original frame
    out = out.crop((0, 0, fit_size[0], fit_size[1]))
    out = out.resize((box[2] - box[0], box[3] - box[1]), Image.LANCZOS)
    result = image.copy()
    # Blend along the (blurred) mask edge for an invisible seam
    full_soft = Image.new("L", image.size, 0)
    full_soft.paste(blur_mask(crop_mask.resize(out.size, Image.NEAREST), 4.0), box)
    result.paste(out, box, full_soft.crop(box).resize(out.size, Image.NEAREST))

    perf = {
        "Time": f"{t.elapsed:.2f} s",
        "Speed": f"{t.elapsed / max(n_steps, 1) * 1000:.0f} ms/step",
        "Peak VRAM": f"{peak_memory_gb():.2f} GB",
        "Inpaint region": f"{crop_img.size[0]}×{crop_img.size[1]}",
        "Strength": f"{float(strength):.2f}",
        "Sampler": "LCM turbo" if fast and s.enable_lcm else "Standard",
        "Seed": used_seed,
        "Subject gate": "on (BiRefNet)" if gated else "off",
    }
    return result, perf, used_seed
