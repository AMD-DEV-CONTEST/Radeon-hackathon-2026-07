"""
Textovid — Image Generation Engine
Runs Stable Diffusion XL on AMD Radeon GPU via ROCm.
Supports High-Res Fix (2x upscale pass) for 4K-quality panels.
"""

import time
import torch
from diffusers import (
    StableDiffusionXLPipeline,
    StableDiffusionXLImg2ImgPipeline,
    DPMSolverMultistepScheduler,
)
from PIL import Image
from typing import Optional, List, Tuple
import config
from uniqueness import get_art_style_prompt


# ── Global pipelines (loaded once) ────────────────────────────────────
_pipe = None
_refiner = None
_device = None


def get_device() -> str:
    global _device
    if _device is None:
        _device = "cuda" if torch.cuda.is_available() else "cpu"
    return _device


def load_pipeline(progress_callback=None):
    """
    Load SDXL pipeline with ROCm-optimised settings.
    Optionally loads the refiner for High-Res Fix.
    """
    global _pipe, _refiner
    if _pipe is not None:
        return _pipe

    if progress_callback:
        progress_callback(0, "Loading SDXL base model...")

    device = get_device()
    dtype = torch.float16 if device == "cuda" else torch.float32

    if progress_callback:
        progress_callback(0.02, f"Loading {config.IMAGE_MODEL_ID} on {device}...")

    _pipe = StableDiffusionXLPipeline.from_pretrained(
        config.IMAGE_MODEL_ID,
        torch_dtype=dtype,
        use_safetensors=True,
        variant="fp16" if device == "cuda" else None,
    )
    _pipe.to(device)

    # Optimised scheduler for fewer steps with good quality
    _pipe.scheduler = DPMSolverMultistepScheduler.from_config(
        _pipe.scheduler.config, use_karras_sigmas=True
    )

    # ROCm-specific: enable memory-efficient attention if available
    if device == "cuda":
        try:
            _pipe.enable_xformers_memory_efficient_attention()
        except Exception:
            pass  # xformers not installed — fall back to default

    if progress_callback:
        progress_callback(0.08, "SDXL base loaded!")

    # Load refiner for high-res fix
    if config.HIGH_RES_FIX and _refiner is None:
        try:
            if progress_callback:
                progress_callback(0.09, "Loading SDXL refiner...")
            _refiner = StableDiffusionXLImg2ImgPipeline.from_pretrained(
                config.IMAGE_REFINER_ID,
                torch_dtype=dtype,
                use_safetensors=True,
                variant="fp16" if device == "cuda" else None,
            )
            _refiner.to(device)
            _refiner.scheduler = DPMSolverMultistepScheduler.from_config(
                _refiner.scheduler.config, use_karras_sigmas=True
            )
            if progress_callback:
                progress_callback(0.1, "SDXL refiner loaded!")
        except Exception as e:
            print(f"[WARN] Could not load refiner, using base only: {e}")
            _refiner = None

    if progress_callback:
        progress_callback(0.1, "All image models loaded!")
    return _pipe


def build_image_prompt(
    scene_description: str,
    art_style: str,
    character_descriptions: Optional[List[str]] = None,
    mood: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Combine scene description with art-style keywords and
    quality boosters for the best possible SDXL output.
    Returns (positive_prompt, negative_prompt).
    """
    style_kw = get_art_style_prompt(art_style)

    parts = [
        scene_description,
        style_kw,
        "masterpiece, best quality, highly detailed, sharp focus",
        "professional comic book panel, cinematic composition",
    ]

    if mood:
        mood_map = {
            "Dark": "dark atmosphere, moody lighting, deep shadows, chiaroscuro",
            "Epic": "epic scale, dramatic composition, cinematic lighting, golden hour",
            "Intimate": "soft lighting, close-up composition, warm tones, shallow depth of field",
            "Surreal": "surreal atmosphere, dreamlike, impossible geometry, vibrant colors",
            "Gritty": "gritty texture, rough edges, desaturated palette, film grain",
            "Lighthearted": "bright colors, soft lighting, cheerful atmosphere, pastel tones",
            "Tense": "high contrast, harsh shadows, claustrophobic framing, dutch angle",
            "Triumphant": "golden light, dynamic pose, radiant atmosphere, lens flare",
            "Melancholic": "muted colors, rain, solitary figure, fog, desaturated",
            "Whimsical": "playful, colorful, exaggerated proportions, fantasy, dreamlike",
        }
        parts.append(mood_map.get(mood, ""))

    if character_descriptions:
        for cd in character_descriptions[:2]:  # max 2 to keep prompt focused
            parts.append(f"character: {cd}")

    negative = (
        "blurry, low quality, deformed, ugly, bad anatomy, "
        "bad hands, extra fingers, missing fingers, text, watermark, "
        "signature, jpeg artifacts, cropped, worst quality, low resolution"
    )

    return ", ".join(parts), negative


def generate_panel_image(
    scene_description: str,
    art_style: str = "Western Comic (Marvel/DC style)",
    character_descriptions: Optional[List[str]] = None,
    mood: Optional[str] = None,
    width: int = None,
    height: int = None,
    steps: int = None,
    cfg_scale: float = None,
    seed: int = None,
    high_res: bool = True,
    progress_callback=None,
) -> Tuple[Image.Image, float, int]:
    """
    Generate a single panel image, optionally with High-Res Fix.
    Returns: (PIL.Image, generation_time_seconds, seed_used)
    """
    pipe = load_pipeline(progress_callback)

    w = width or config.DEFAULT_WIDTH
    h = height or config.DEFAULT_HEIGHT
    num_steps = steps or config.DEFAULT_STEPS
    guidance = cfg_scale or config.DEFAULT_CFG_SCALE
    generator_seed = seed if seed is not None and seed >= 0 else torch.randint(0, 2**32, (1,)).item()
    generator = torch.Generator(device=get_device()).manual_seed(generator_seed)

    prompt, negative_prompt = build_image_prompt(
        scene_description, art_style, character_descriptions, mood
    )

    # ── Pass 1: Base generation ─────────────────────────────────────
    t0 = time.time()
    result = pipe(
        prompt=prompt,
        negative_prompt=negative_prompt,
        width=w,
        height=h,
        num_inference_steps=num_steps,
        guidance_scale=guidance,
        generator=generator,
    )
    base_image = result.images[0]

    # ── Pass 2: High-Res Fix (refiner at 2x) ─────────────────────────
    if high_res and _refiner is not None:
        hr_w = w * 2
        hr_h = h * 2
        base_image = base_image.resize((hr_w, hr_h), Image.LANCZOS)
        refiner_gen = torch.Generator(device=get_device()).manual_seed(generator_seed + 1)
        result2 = _refiner(
            prompt=prompt,
            negative_prompt=negative_prompt,
            image=base_image,
            num_inference_steps=max(num_steps // 3, 5),
            guidance_scale=guidance * 0.8,
            denoising_strength=config.HIGH_RES_DENOISE,
            generator=refiner_gen,
        )
        base_image = result2.images[0]

    elapsed = time.time() - t0
    return base_image, elapsed, generator_seed


def generate_all_panels(
    flat_panels: list,
    art_style: str,
    mood: Optional[str] = None,
    character_descs: Optional[List[str]] = None,
    steps: int = None,
    cfg_scale: float = None,
    high_res: bool = True,
    progress_callback=None,
) -> list:
    """
    Generate images for all panels sequentially.
    flat_panels: list of (page_idx, panel_dict) tuples.
    Returns: list of (page_idx, PIL.Image, gen_time, seed) tuples.
    """
    load_pipeline(progress_callback)  # Ensure loaded
    total = len(flat_panels)
    results = []

    for i, (page_idx, panel) in enumerate(flat_panels):
        frac = 0.1 + 0.7 * (i / max(total, 1))

        if progress_callback:
            progress_callback(
                frac,
                f"Generating panel {i+1}/{total} (page {page_idx+1})..."
            )

        scene = panel.get("scene_description", "a dramatic comic panel scene")
        img, elapsed, seed = generate_panel_image(
            scene_description=scene,
            art_style=art_style,
            character_descriptions=character_descs,
            mood=mood,
            steps=steps,
            cfg_scale=cfg_scale,
            high_res=high_res,
            progress_callback=progress_callback,
        )
        results.append((page_idx, img, elapsed, seed))

    return results
