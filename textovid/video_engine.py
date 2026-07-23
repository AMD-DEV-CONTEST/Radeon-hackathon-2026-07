"""
Textovid — Video Panel Engine
Animates static comic panels into short video clips using LTX Video on ROCm.
Optional feature — enabled via TEXTOVID_ENABLE_VIDEO=1 env var or config.
"""

import os
import time
import torch
from PIL import Image
from typing import Optional
import config


_pipe = None
_device = None


def is_available() -> bool:
    """Check if video generation is enabled and dependencies are available."""
    if not config.VIDEO_ENABLED:
        return False
    try:
        import diffusers
        return True
    except ImportError:
        return False


def get_device() -> str:
    global _device
    if _device is None:
        _device = "cuda" if torch.cuda.is_available() else "cpu"
    return _device


def load_video_pipeline(progress_callback=None):
    """
    Load LTX Video pipeline on ROCm.
 LTX Video generates short video clips from images.
    """
    global _pipe
    if _pipe is not None:
        return _pipe

    if progress_callback:
        progress_callback(0.5, "Loading LTX Video model...")

    try:
        from diffusers import LTXVideoPipeline
        import imageio
    except ImportError as e:
        print(f"[WARN] Video dependencies missing: {e}")
        return None

    device = get_device()
    dtype = torch.float16 if device == "cuda" else torch.float32

    try:
        _pipe = LTXVideoPipeline.from_pretrained(
            config.VIDEO_MODEL_ID,
            torch_dtype=dtype,
        )
        _pipe.to(device)

        if device == "cuda":
            try:
                _pipe.enable_model_cpu_offload()
            except Exception:
                pass

        if progress_callback:
            progress_callback(0.55, "LTX Video loaded!")
    except Exception as e:
        print(f"[WARN] Could not load LTX Video: {e}")
        return None

    return _pipe


def animate_panel(
    image: Image.Image,
    prompt: str = "",
    num_frames: int = 25,
    steps: int = 20,
 seed: int = -1,
    fps: int = 8,
    progress_callback=None,
) -> Optional[str]:
    """
    Animate a single comic panel into a short video clip.
    Returns the path to the saved .mp4 file, or None on failure.
    """
    pipe = load_video_pipeline(progress_callback)
    if pipe is None:
        return None

    try:
        import imageio.v2 as imageio
    except ImportError:
        return None

    device = get_device()
    gen_seed = seed if seed >= 0 else torch.randint(0, 2**32, (1,)).item()
    generator = torch.Generator(device=device).manual_seed(gen_seed)

    if progress_callback:
        progress_callback(0.6, f"Animating panel ({num_frames} frames)...")

    t0 = time.time()

    # LTX Video: image-to-video
    result = pipe(
        image=image,
        prompt=prompt or "subtle camera motion, cinematic, smooth",
        num_frames=num_frames,
        num_inference_steps=steps,
        generator=generator,
    )
    frames = result.frames[0]  # (num_frames, H, W, C)
    elapsed = time.time() - t0

    # Save as MP4
    timestamp = int(time.time())
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(config.OUTPUT_DIR, f"panel_anim_{timestamp}_{gen_seed % 10000}.mp4")

    imageio.mimsave(out_path, frames, fps=fps)

    if progress_callback:
        progress_callback(0.65, f"Animation saved: {elapsed:.1f}s")

    return out_path
