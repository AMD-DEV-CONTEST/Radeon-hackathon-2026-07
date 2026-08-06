from __future__ import annotations

import os
from pathlib import Path

import yaml
from PIL import Image, ImageDraw

from src.device import detect_device, torch_device_string, vram_profile
from src.models_schema import CharacterCard
from src.paths import ROOT


def _image_cfg() -> dict:
    p = ROOT / "configs" / "models.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    return data.get("image") or {}


def _mock_portrait(card: CharacterCard, out_path: Path) -> Path:
    cfg = _image_cfg()
    w, h = int(cfg.get("width", 832)), int(cfg.get("height", 1216))
    img = Image.new("RGB", (w, h), (32, 40, 64))
    d = ImageDraw.Draw(img)
    d.rectangle([40, 40, w - 40, h - 40], outline=(120, 180, 255), width=4)
    d.text((60, 80), card.name[:20], fill=(240, 240, 255))
    d.text((60, 140), card.primary_affinity, fill=(180, 220, 255))
    d.text((60, 200), "MOCK PORTRAIT", fill=(200, 200, 120))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


_pipe = None


def generate_portrait(
    card: CharacterCard,
    out_path: str | Path,
    ref_image: Image.Image | None = None,
    mock: bool | None = None,
    ref_scale: float | None = None,
) -> Path:
    if mock is None:
        mock = os.environ.get("MOCK", "0").strip() in {"1", "true", "True", "yes"}
    out_path = Path(out_path)
    if mock:
        return _mock_portrait(card, out_path)

    return _generate_diffusers(card, out_path, ref_image, ref_scale)


def _generate_diffusers(
    card: CharacterCard,
    out_path: Path,
    ref_image: Image.Image | None,
    ref_scale: float | None,
) -> Path:
    import torch
    from diffusers import StableDiffusionXLPipeline, StableDiffusionXLImg2ImgPipeline

    from src.model_paths import has_local_image, local_image_dir

    global _pipe
    cfg = _image_cfg()
    model_id = cfg["model_id"]
    if has_local_image():
        model_id = str(local_image_dir())
    device = torch_device_string()
    info = detect_device()
    profile = vram_profile(info)

    width = int(cfg.get("width", 832))
    height = int(cfg.get("height", 1216))
    steps = int(cfg.get("steps", 30))
    if profile == "16gb":
        width, height = min(width, 768), min(height, 1024)
        steps = min(steps, 28)
    if profile == "low":
        width, height = 512, 768
        steps = min(steps, 24)

    dtype = torch.float16 if device == "cuda" else torch.float32
    if _pipe is None:
        _pipe = StableDiffusionXLPipeline.from_pretrained(
            model_id, torch_dtype=dtype, use_safetensors=True
        )
        if cfg.get("enable_attention_slicing", True):
            _pipe.enable_attention_slicing()
        if cfg.get("enable_vae_tiling", True) and hasattr(_pipe, "enable_vae_tiling"):
            _pipe.enable_vae_tiling()
        _pipe = _pipe.to(device)

    prompt = card.image_prompt
    negative = card.image_negative or ""
    guidance = float(cfg.get("guidance", 6.0))
    scale = float(ref_scale if ref_scale is not None else cfg.get("ref_scale", 0.65))

    generator = torch.Generator(device=device).manual_seed(42)

    if ref_image is not None:
        # img2img path (IP-Adapter can replace later)
        img2img = StableDiffusionXLImg2ImgPipeline(
            vae=_pipe.vae,
            text_encoder=_pipe.text_encoder,
            text_encoder_2=_pipe.text_encoder_2,
            tokenizer=_pipe.tokenizer,
            tokenizer_2=_pipe.tokenizer_2,
            unet=_pipe.unet,
            scheduler=_pipe.scheduler,
        )
        img2img = img2img.to(device)
        init = ref_image.convert("RGB").resize((width, height))
        result = img2img(
            prompt=prompt,
            negative_prompt=negative,
            image=init,
            strength=min(0.95, max(0.2, 1.0 - scale * 0.5)),
            num_inference_steps=steps,
            guidance_scale=guidance,
            generator=generator,
        )
        image = result.images[0]
    else:
        result = _pipe(
            prompt=prompt,
            negative_prompt=negative,
            width=width,
            height=height,
            num_inference_steps=steps,
            guidance_scale=guidance,
            generator=generator,
        )
        image = result.images[0]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
    return out_path


def unload_image_models() -> None:
    global _pipe
    _pipe = None
    try:
        import torch
        import gc

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
