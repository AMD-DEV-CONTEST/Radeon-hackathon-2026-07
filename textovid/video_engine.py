# -*- coding: utf-8 -*-
"""Textovid — Video engine (LTX Video panel animation)"""

import torch
from diffusers import LTXVideoPipeline, LTXVideoScheduler
from config import LTX_VIDEO, MODEL_CACHE
from gpu_utils import get_gpu_info

_pipe: LTXVideoPipeline | None = None


def _load_pipe() -> LTXVideoPipeline:
    global _pipe
    if _pipe is not None:
        return _pipe

    info = get_gpu_info()
    print(f"[video_engine] GPU: {info['name']}  VRAM free: {info['vram_free_gb']} GB")

    print("[video_engine] Loading LTX-Video pipeline …")
    scheduler = LTXVideoScheduler.from_pretrained(LTX_VIDEO, subfolder="scheduler", cache_dir=MODEL_CACHE)
    _pipe = LTXVideoPipeline.from_pretrained(
        LTX_VIDEO,
        torch_dtype=torch.bfloat16,
        scheduler=scheduler,
        cache_dir=MODEL_CACHE,
    ).to("cuda")
    _pipe.enable_model_cpu_offload()
    return _pipe


def animate_panel(
    prompt: str,
    image: "PIL.Image.Image",
    num_frames: int = 17,
    seed: int = -1,
) -> str:
    """Animate a single panel image into a short MP4 clip.

    Returns the path to the saved .mp4 file.
    """
    pipe = _load_pipe()
    generator = torch.Generator("cuda").manual_seed(
        seed if seed >= 0 else torch.randint(0, 2**32, (1,)).item()
    )

    from config import OUTPUT_DIR
    import os
    video_path = os.path.join(OUTPUT_DIR, "panel_anim.mp4")

    result = pipe(
        prompt=prompt,
        image=image,
        num_frames=num_frames,
        generator=generator,
    )
    frames = result.frames[0]

    # Save as MP4 via imageio
    try:
        import imageio.v2 as iio
        iio.mimwrite(video_path, frames, fps=8, codec="libx264")
    except Exception:
        import imageio
        imageio.mimsave(video_path, frames, fps=8)

    return video_path
