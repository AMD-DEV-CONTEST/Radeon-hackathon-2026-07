# -*- coding: utf-8 -*-
"""Outpainting v2 — canvas extension + SDXL inpainting fill."""
from __future__ import annotations

import colorsys

import numpy as np
from PIL import Image

from ..device import Timer, peak_memory_gb, reset_peak_memory
from ..utils import blur_mask, dilate_mask, make_generator, resize_long_edge
from .inpaint import DEFAULT_NEGATIVE


def _tone_hint(image: Image.Image) -> tuple[str, dict]:
    """Describe the source image's palette/lighting in prompt words so the
    invented surroundings MATCH instead of clashing (the 'yellow bedroom
    around a dark-blue night scene' failure). Also returns meta flags so the
    caller can aim the negative prompt at the likely clash."""
    arr = np.asarray(image.resize((96, 96))).astype(np.float32) / 255.0
    lum = float(arr.mean())
    # dominant hue of chromatic pixels
    flat = arr.reshape(-1, 3)
    mx, mn = flat.max(1), flat.min(1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    chroma = flat[sat > 0.18]
    words = []
    meta = {"cool": False, "dark": lum < 0.5}
    if lum < 0.32:
        words += ["dark scene", "dim nighttime lighting"]
    elif lum < 0.5:
        words += ["low-key lighting", "muted tones"]
    elif lum > 0.72:
        words += ["bright airy lighting", "high-key tones"]
    if len(chroma) > 200:
        hsv = np.array([colorsys.rgb_to_hsv(*p) for p in chroma[::7]])
        mean_ang = np.arctan2(np.mean(np.sin(hsv[:, 0] * 2 * np.pi)),
                              np.mean(np.cos(hsv[:, 0] * 2 * np.pi)))
        hue = (np.degrees(mean_ang) + 360) % 360
        names = [(20, "red"), (45, "orange"), (70, "yellow"), (160, "green"),
                 (200, "teal"), (255, "blue"), (290, "purple"), (330, "pink"),
                 (360, "red")]
        name = next(n for lim, n in names if hue <= lim)
        words.append(f"{name}-dominant color palette")
        meta["cool"] = name in ("teal", "blue", "purple", "green")
    else:
        words.append("desaturated neutral palette")
    return ", ".join(words), meta


def _harmonize_seam(result: Image.Image, mask: Image.Image,
                    band: int = 64, strength: float = 0.85) -> Image.Image:
    """Per-channel mean/std match of the WHOLE generated area to the original
    pixels just inside the seam (Reinhard transfer), applied across the full
    generated region — not just a fading ring. A narrow ring-only correction
    leaves the far extension in whatever clashing palette the model invented
    (warm yellow walls around a cool night scene); matching the full region
    forces global palette continuity."""
    import cv2
    m = np.asarray(mask) > 128
    if m.sum() < 100 or (~m).sum() < 100:
        return result

    def _dilate(a: np.ndarray, r: int) -> np.ndarray:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
        return cv2.dilate(a.astype(np.uint8), k) > 0

    ring_src = _dilate(m, band) & ~m               # original side of the seam
    gen_all = m                                    # whole generated region
    if ring_src.sum() < 50 or gen_all.sum() < 50:
        return result
    arr = np.asarray(result).astype(np.float32)
    src, gen = arr[ring_src], arr[gen_all]
    ms, ss = src.mean(0), src.std(0) + 1e-3
    mg, sg = gen.mean(0), gen.std(0) + 1e-3
    gain = np.clip(ss / sg, 0.5, 2.0)
    shift = ms - gain * mg
    w = np.where(m, strength, 0.0)[..., None]
    arr = arr * (1 - w) + np.clip(arr * gain + shift, 0, 255) * w
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8), "RGB")


def _extend_canvas(image: Image.Image, left: int, right: int, top: int,
                   bottom: int, overlap: int = 48):
    """Build the extended canvas and the fill mask (white = area to generate).
    The mask overlaps `overlap` px into the original image for a seamless join."""
    w, h = image.size
    W, H = w + left + right, h + top + bottom
    # Seed the new area with edge-replicated content (better than flat color)
    arr = np.asarray(image)
    canvas_arr = np.zeros((H, W, 3), dtype=np.uint8)
    canvas_arr[top:top + h, left:left + w] = arr
    if left:    canvas_arr[top:top + h, :left] = arr[:, :1]
    if right:   canvas_arr[top:top + h, left + w:] = arr[:, -1:]
    if top:     canvas_arr[:top, :] = canvas_arr[top:top + 1, :]
    if bottom:  canvas_arr[top + h:, :] = canvas_arr[top + h - 1:top + h, :]
    canvas = Image.fromarray(canvas_arr)

    mask = Image.new("L", (W, H), 255)
    # Keep the original image except an overlap ring ON THE EXTENDED SIDES
    # ONLY — a ring on non-extended sides needlessly repaints real content
    # (the model 'continued' the subject's foot at the far edge, creating a
    # translucent ghost limb there).
    mask.paste(0, (left + (overlap if left else 0),
                   top + (overlap if top else 0),
                   left + w - (overlap if right else 0),
                   top + h - (overlap if bottom else 0)))
    return canvas, mask


def run_outpaint(manager, image: Image.Image, left: int, right: int,
                 top: int, bottom: int, prompt: str, negative: str = "",
                 steps: int = 30, guidance: float = 7.5, seed: int = -1,
                 fast: bool = False):
    """Returns (result_image, perf_dict, used_seed)."""
    if image is None:
        raise ValueError("Please upload an image first.")
    if not any([left, right, top, bottom]):
        raise ValueError("Set at least one direction to extend.")
    if not (prompt or "").strip():
        raise ValueError("Describe the full extended scene in the prompt.")

    s = manager.settings
    pipe = manager.get_inpaint_pipe()
    manager.set_lcm(pipe, fast)

    # Palette/lighting hint from the SOURCE image — the model otherwise
    # invents the surroundings in a clashing palette (warm yellow bedroom
    # around a dark-blue night scene). The hint goes FIRST: SDXL weighs the
    # front of the prompt most. Style continuity words keep an anime source
    # from growing photoreal walls (and vice versa).
    from .style import _looks_anime
    hint, meta = _tone_hint(image)
    style_word = ("anime style background illustration, cel shading, "
                  "hand-drawn 2d anime scenery") if _looks_anime(image) else \
                 "photorealistic, natural photographic detail"
    prompt = f"{hint}, {style_word}, {prompt}, seamless color and lighting continuity"
    negative = (negative or DEFAULT_NEGATIVE) + \
        ", color mismatch, inconsistent lighting, jarring border, " \
        "person, people, human, face, extra limbs, duplicated limbs, " \
        "extra legs, extra feet, extra arms, cloned body parts"
    if meta.get("cool"):
        negative += ", yellow walls, warm color cast, orange tint, sepia"

    canvas, mask = _extend_canvas(image, int(left), int(right), int(top), int(bottom))
    work = resize_long_edge(canvas, s.max_working_size, multiple=16,
                            upscale_min=s.max_working_size)

    # Bucket the working shape (same reason as inpaint: MIOpen autotunes per
    # input shape, ~6 min one-time per unseen size). Fit inside the nearest
    # native bucket + edge-replicate pad; the padding is cropped off after.
    from .background import _native_bucket
    tw, th = _native_bucket(*work.size)
    wscale = min(tw / work.width, th / work.height)
    fw = max(16, round(work.width * wscale / 16) * 16)
    fh = max(16, round(work.height * wscale / 16) * 16)
    fit = work.resize((fw, fh), Image.LANCZOS)
    warr = np.asarray(fit)
    wcanvas = np.zeros((th, tw, 3), dtype=np.uint8)
    wcanvas[:fh, :fw] = warr
    if tw > fw:
        wcanvas[:fh, fw:] = warr[:, -1:]
    if th > fh:
        wcanvas[fh:, :] = wcanvas[fh - 1:fh, :]
    work = Image.fromarray(wcanvas)
    work_mask = Image.new("L", (tw, th), 0)
    work_mask.paste(mask.resize((fw, fh), Image.NEAREST), (0, 0))
    work_mask = blur_mask(work_mask, radius=12.0)

    gen, used_seed = make_generator("cuda" if manager.info.is_gpu else "cpu", seed)
    n_steps = s.lcm_steps if fast else int(steps)
    cfg = s.lcm_guidance if fast else float(guidance)

    reset_peak_memory()
    with Timer() as t:
        out = pipe(
            prompt=prompt,
            negative_prompt=negative or DEFAULT_NEGATIVE,
            image=work,
            mask_image=work_mask,
            strength=1.0,
            num_inference_steps=n_steps,
            guidance_scale=cfg,
            generator=gen,
        ).images[0]

    out = out.crop((0, 0, fw, fh)).resize(canvas.size, Image.LANCZOS)
    # Paste through the mask: the original photo area stays pixel-exact,
    # only the generated ring + new area come from the pipe output. A wide
    # feather (16 px) hides the tone seam between pipe output and original.
    full_mask = blur_mask(mask, radius=16.0)
    result = canvas.copy()
    result.paste(out, (0, 0), full_mask)
    # Reinhard tone-match the generated area to the original seam pixels —
    # guarantees palette continuity even if the model drifted.
    result = _harmonize_seam(result, mask)
    perf = {
        "Time": f"{t.elapsed:.2f} s",
        "Speed": f"{t.elapsed / max(n_steps, 1) * 1000:.0f} ms/step",
        "Peak VRAM": f"{peak_memory_gb():.2f} GB",
        "Working size": f"{work.size[0]}×{work.size[1]}",
        "Output size": f"{result.size[0]}×{result.size[1]}",
        "Palette hint": hint,
        "Sampler": "LCM turbo" if fast and s.enable_lcm else "Standard",
        "Seed": used_seed,
    }
    return result, perf, used_seed
