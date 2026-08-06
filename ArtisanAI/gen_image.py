# pip install accelerate transformers safetensors diffusers

import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HOME"] = os.path.join(os.path.dirname(__file__), "models")

# ---- Quantization toggle (set to False for fp16) ----
USE_NF4 = False

import hashlib
import time

import torch
from PIL import Image

# Input shapes are fixed (1024x1024, batch 1), so let MIOpen autotune conv algorithms.
# The one-off tuning cost is absorbed by the startup warmup and cached on disk.
torch.backends.cudnn.benchmark = True

from controlnet_aux import CannyDetector
from transformers import BitsAndBytesConfig
from diffusers import ControlNetModel, StableDiffusionXLControlNetImg2ImgPipeline, AutoencoderKL, EulerDiscreteScheduler, UNet2DConditionModel
from diffusers.utils import load_image

# Canny needs no weights; the distilled small ControlNet is 160M params vs 1.25B for a full one.
canny_processor = CannyDetector()
controlnet = ControlNetModel.from_pretrained(
    "diffusers/controlnet-canny-sdxl-1.0-small",
    variant="fp16",
    use_safetensors=True,
    torch_dtype=torch.float16,
)
vae = AutoencoderKL.from_pretrained("madebyollin/sdxl-vae-fp16-fix", torch_dtype=torch.float16)

if USE_NF4:
    quant_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_quant_type="nf4",
    )
    unet = UNet2DConditionModel.from_pretrained(
        "stabilityai/stable-diffusion-xl-base-1.0",
        subfolder="unet",
        quantization_config=quant_config,
        device_map={"": "cuda"},
    )
    pipe = StableDiffusionXLControlNetImg2ImgPipeline.from_pretrained(
        "stabilityai/stable-diffusion-xl-base-1.0",
        controlnet=controlnet,
        vae=vae,
        unet=unet,
        variant="fp16",
        use_safetensors=True,
        torch_dtype=torch.float16,
    )
    # UNet already on cuda via device_map; only move other components
    pipe.vae = pipe.vae.to("cuda")
    pipe.controlnet = pipe.controlnet.to("cuda")
    pipe.text_encoder = pipe.text_encoder.to("cuda")
    pipe.text_encoder_2 = pipe.text_encoder_2.to("cuda")
else:
    pipe = StableDiffusionXLControlNetImg2ImgPipeline.from_pretrained(
        "stabilityai/stable-diffusion-xl-base-1.0",
        controlnet=controlnet,
        vae=vae,
        variant="fp16",
        use_safetensors=True,
        torch_dtype=torch.float16,
    )
    pipe = pipe.to("cuda")
pipe.load_lora_weights("ByteDance/SDXL-Lightning", weight_name="sdxl_lightning_8step_lora.safetensors")
pipe.scheduler = EulerDiscreteScheduler.from_config(pipe.scheduler.config, timestep_spacing="trailing")
# Lightning adapter name.
LIGHTNING_ADAPTER = pipe.get_active_adapters()[0]

# LoRA manifest: display_name -> {repo_id, adapter_name, prompt, scale}
# First use downloads and caches weights under models/.
LORA_MANIFEST = {
    "无": {"repo_id": None, "adapter_name": None, "prompt": "A robot, 4k photo", "scale": 0.8},
    "日式动漫": {
        "repo_id": "ntc-ai/SDXL-LoRA-slider.anime",
        "adapter_name": "anime",
        "prompt": "anime style, Japanese animation, cel shading, clean lines, vibrant colors, detailed character design",
        "scale": 1.0,
    },
    "像素艺术": {
        "repo_id": "ntc-ai/SDXL-LoRA-slider.pixel-art",
        "adapter_name": "pixel_art",
        "prompt": "pixel art style, 8-bit retro game aesthetic, blocky pixels, limited color palette, crisp dithering",
        "scale": 1.0,
    },
    "吉卜力工作室": {
        "repo_id": "ntc-ai/SDXL-LoRA-slider.Studio-Ghibli-style",
        "adapter_name": "ghibli",
        "prompt": "A beautiful Ghibli style portrait, hand-drawn animation, soft lighting, Miyazaki aesthetic, vibrant colors",
        "scale": 1.0,
    },
    "卡通": {
        "repo_id": "ntc-ai/SDXL-LoRA-slider.cartoon",
        "adapter_name": "cartoon",
        "prompt": "cartoon style, bold outlines, flat bright colors, simplified shapes, playful exaggerated features",
        "scale": 1.0,
    },
    "油画": {
        "repo_id": "ntc-ai/SDXL-LoRA-slider.oil-painting",
        "adapter_name": "oil",
        "prompt": "oil painting style, thick brushstrokes, rich textures, classical composition, impasto technique",
        "scale": 1.0,
    },
    "皮克斯动画": {
        "repo_id": "ntc-ai/SDXL-LoRA-slider.pixar-style",
        "adapter_name": "pixar",
        "prompt": "Pixar style, 3D animation render, cartoon aesthetic, soft lighting, expressive character, Disney CGI look",
        "scale": 1.0,
    },
    "超写实插画": {
        "repo_id": "ntc-ai/SDXL-LoRA-slider.ultra-realistic-illustration",
        "adapter_name": "ultra_realistic",
        "prompt": "ultra realistic illustration, highly detailed digital painting, refined shading, lifelike textures, artstation quality",
        "scale": 1.0,
    },
    "千禧独立漫画": {
        "repo_id": "ntc-ai/SDXL-LoRA-slider.2000s-indie-comic-art-style",
        "adapter_name": "indie_comic",
        "prompt": "2000s indie comic art style, inked linework, halftone shading, gritty alternative comic book aesthetic",
        "scale": 1.0,
    },
}


def preload_style_loras():
    print("Loading style LoRAs...")
    for display_name, info in LORA_MANIFEST.items():
        repo_id = info.get("repo_id")
        adapter_name = info.get("adapter_name")
        if not repo_id:
            continue
        if not adapter_name:
            raise ValueError(f"LoRA '{display_name}' is missing adapter_name")

        pipe.load_lora_weights(repo_id, adapter_name=adapter_name)
        print(f"  Loaded {display_name}: {repo_id} as '{adapter_name}'")

    pipe.set_adapters([LIGHTNING_ADAPTER], adapter_weights=[1.0])
    print("Style LoRAs loaded.")


def apply_lora(lora_name):
    info = LORA_MANIFEST.get(lora_name, LORA_MANIFEST["无"])
    adapter_name = info.get("adapter_name")
    if adapter_name:
        pipe.set_adapters(
            [LIGHTNING_ADAPTER, adapter_name],
            adapter_weights=[1.0, info.get("scale", 1.0)],
        )
    else:
        pipe.set_adapters([LIGHTNING_ADAPTER], adapter_weights=[1.0])


preload_style_loras()


def get_canny_map(image, low_threshold=100, high_threshold=200):
    return canny_processor(
        image,
        low_threshold=low_threshold,
        high_threshold=high_threshold,
        detect_resolution=1024,
        image_resolution=1024,
    )


# Cache the last Canny map: users typically tweak prompt/style on the same image
_canny_cache = None  # (image_hash, canny_image)


def get_canny_cached(image):
    global _canny_cache
    key = hashlib.md5(image.tobytes()).hexdigest()
    if _canny_cache is not None and _canny_cache[0] == key:
        return _canny_cache[1], True
    canny_image = get_canny_map(image)
    _canny_cache = (key, canny_image)
    return canny_image, False


def generate_image(image, prompt, negative_prompt="", strength=0.7, steps=8,
                   conditioning_scale=0.5, guidance_scale=1.0, seed=42, lora_name="无"):
    """Generate one 1024x1024 image. Returns (PIL image, timing report string)."""
    t_total = time.time()
    torch.cuda.reset_peak_memory_stats()

    t_lora_start = time.time()
    apply_lora(lora_name)
    torch.cuda.synchronize()
    t_lora = time.time() - t_lora_start

    image = image.resize((1024, 1024))

    t_canny_start = time.time()
    canny_image, canny_cached = get_canny_cached(image)
    torch.cuda.synchronize()
    t_canny = time.time() - t_canny_start

    if seed < 0:
        seed = torch.randint(0, 2**32 - 1, (1,)).item()
    generator = torch.Generator(device="cuda").manual_seed(seed)

    # Track per-step denoising time
    step_durations = []
    def step_callback(pipe, step, timestep, callback_kwargs):
        nonlocal t_last
        torch.cuda.synchronize()
        now = time.time()
        step_durations.append(now - t_last)
        t_last = now
        return callback_kwargs

    t_pipe_start = time.time()
    t_last = t_pipe_start
    result = pipe(
        prompt=prompt,
        negative_prompt=negative_prompt or None,
        image=image,
        control_image=canny_image,
        strength=strength,
        num_inference_steps=int(steps),
        controlnet_conditioning_scale=conditioning_scale,
        guidance_scale=guidance_scale,
        generator=generator,
        callback_on_step_end=step_callback,
    ).images[0]
    torch.cuda.synchronize()
    t_pipe = time.time() - t_pipe_start

    # step_durations[0] = encode+step1, [1..] = step2..N, t_pipe - sum = VAE decode
    if len(step_durations) > 1:
        t_setup = step_durations[0]  # VAE/text encode + step1
        t_per_step = sum(step_durations[1:]) / (len(step_durations) - 1)
    else:
        t_setup = t_pipe
        t_per_step = t_pipe
    t_vae = max(t_pipe - sum(step_durations), 0.0)

    elapsed = time.time() - t_total

    # Actual denoise steps = int(steps * strength) in img2img, not the slider value
    timing_text = "\n".join([
        f"⏱ Total: {elapsed:.2f}s  ·  seed {seed}",
        f"├─ LoRA:       {t_lora * 1000:.1f}ms ({lora_name})",
        f"├─ Canny:      {t_canny:.2f}s{' (cached)' if canny_cached else ''}",
        f"├─ Setup:      {t_setup:.2f}s (encode + step1)",
        f"├─ Denoise:    {t_per_step:.3f}s/step × {len(step_durations)}",
        f"├─ VAE decode: {t_vae:.2f}s",
        f"├─ Pipe total: {t_pipe:.2f}s",
        f"└─ VRAM peak:  {torch.cuda.max_memory_allocated() / 2**30:.2f} GB allocated"
        f" / {torch.cuda.max_memory_reserved() / 2**30:.2f} GB reserved",
    ])
    return result, timing_text


if __name__ == "__main__":
    images_dir = os.path.join(os.path.dirname(__file__), "images")
    image_path = os.path.join(images_dir, "cat.png")
    if not os.path.exists(image_path):
        os.makedirs(images_dir, exist_ok=True)
        load_image(
            "https://hf-mirror.com/datasets/hf-internal-testing/diffusers-images/resolve/main"
            "/kandinsky/cat.png"
        ).resize((1024, 1024)).save(image_path)
    image = Image.open(image_path).convert("RGB")

    prompt = "A robot, 4k photo"

    # First run pays kernel compilation and MIOpen autotuning; discard its timings.
    print("Warming up...")
    generate_image(image, prompt)

    _canny_cache = None  # force a cache miss so the Canny number is the real one
    result, timing = generate_image(image, prompt)
    print(timing)

    output_dir = os.path.join(os.path.dirname(__file__), "output_images")
    os.makedirs(output_dir, exist_ok=True)
    result.save(os.path.join(output_dir, "robot_cat.png"))
    print(f"Saved to {os.path.join(output_dir, 'robot_cat.png')}")
