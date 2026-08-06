# -*- coding: utf-8 -*-
"""Object / watermark removal v2 — LaMa primary, SDXL inpainting fallback."""
from __future__ import annotations

from PIL import Image

from ..device import Timer, peak_memory_gb, reset_peak_memory
from ..utils import blur_mask, dilate_mask, make_generator
from .inpaint import DEFAULT_NEGATIVE


def run_remove(manager, image: Image.Image, mask: Image.Image,
               expand_px: int = 12, engine: str = "auto"):
    """Returns (result_image, perf_dict)."""
    if image is None or mask is None:
        raise ValueError("Please upload an image and brush over what to erase.")
    mask = dilate_mask(mask, int(expand_px))

    reset_peak_memory()
    # ---------------- primary: LaMa (fast, prompt-free) ----------------
    if engine in ("auto", "lama"):
        try:
            lama = manager.get_lama()
            with Timer() as t:
                result = lama(image, mask)
            # simple_lama pads inputs to a multiple of 8 and never crops back —
            # restore the exact original size so downstream compositing aligns.
            if result.size != image.size:
                if result.width >= image.width and result.height >= image.height:
                    result = result.crop((0, 0, image.width, image.height))
                else:
                    result = result.resize(image.size, Image.LANCZOS)
            perf = {
                "Time": f"{t.elapsed:.2f} s",
                "Peak VRAM": f"{peak_memory_gb():.2f} GB",
                "Engine": "LaMa (dedicated removal model)",
            }
            return result, perf
        except Exception as e:
            if engine == "lama":
                raise
            lama_err = f"{type(e).__name__}: {e}"

    # ---------------- fallback: SDXL inpainting ----------------
    s = manager.settings
    pipe = manager.get_inpaint_pipe()
    manager.set_lcm(pipe, False)
    gen, used_seed = make_generator("cuda" if manager.info.is_gpu else "cpu", -1)
    soft = blur_mask(mask, radius=6.0)
    from ..utils import resize_long_edge
    work = resize_long_edge(image, s.max_working_size, multiple=16,
                            upscale_min=768)
    soft = soft.resize(work.size, Image.NEAREST)
    with Timer() as t:
        out = pipe(
            prompt="empty clean background, seamless texture, high quality",
            negative_prompt=DEFAULT_NEGATIVE + ", object, person, watermark",
            image=work, mask_image=soft, strength=1.0,
            num_inference_steps=30, guidance_scale=7.0, generator=gen,
        ).images[0]
    result = out.resize(image.size, Image.LANCZOS)
    perf = {
        "Time": f"{t.elapsed:.2f} s",
        "Peak VRAM": f"{peak_memory_gb():.2f} GB",
        "Engine": "SDXL inpaint fallback",
    }
    return result, perf
