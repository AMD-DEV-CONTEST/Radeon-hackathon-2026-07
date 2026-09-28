# Radeon Cloud session 1: 45-minute maximum

## Goal and stop rules

Prove one real, disclosed image-to-image inference on the existing Radeon Cloud template, capture the environment and one output, then destroy the instance. Target credit use is **no more than 0.75 GPU-hour**, leaving at least 4.25 of the five available hours.

Do not fine-tune, install ComfyUI, download the SDXL refiner, add ControlNet/IP-Adapter, or debug one issue for more than five minutes. If SDXL cannot run after one documented memory/offload adjustment, switch to the smaller fallback. If persistence is uncertain, save reports before proceeding. Always destroy the instance by minute 45.

## 0–5 minutes — launch and hardware identity

1. Launch the existing BrandPilot Track 1 template. Record the wall-clock start time.
2. Open the Jupyter terminal. Do not expose the notebook publicly.
3. Run:

```bash
date -u +"%Y-%m-%dT%H:%M:%SZ"
hostnamectl || uname -a
rocm-smi
rocm-smi --showmeminfo vram --showuse --showproductname
rocminfo | sed -n '1,160p'
ls -l /dev/kfd /dev/dri/render* 2>/dev/null
```

Stop if `rocm-smi` cannot see a GPU or `/dev/kfd` is unavailable. Save the exact error; do not guess.

## 5–10 minutes — Python and PyTorch

```bash
python3 --version
python3 -m pip --version
python3 - <<'PY'
import json
import torch

report = {
    "torch_version": torch.__version__,
    "hip_version": getattr(torch.version, "hip", None),
    "cuda_api_available": torch.cuda.is_available(),
    "device_count": torch.cuda.device_count(),
    "devices": [],
}
for index in range(torch.cuda.device_count()):
    properties = torch.cuda.get_device_properties(index)
    report["devices"].append({
        "index": index,
        "name": torch.cuda.get_device_name(index),
        "total_memory_bytes": getattr(properties, "total_memory", None),
    })
print(json.dumps(report, indent=2))
PY
python3 -m torch.utils.collect_env | tee /tmp/brandpilot-torch-environment.txt
```

Pass criteria: PyTorch imports, `torch.cuda.is_available()` is `True`, `torch.version.hip` is non-empty, at least one device exists, and the device name is recorded. PyTorch uses the `cuda` API name for HIP devices; this is expected.

## 10–20 minutes — verify persistence and prepare the repository

The template's documented persistent mount must be confirmed in the Radeon Cloud UI or `df` output. The commands below use `/workspace`; if the template exposes a different persistent mount, set `PERSIST_ROOT` to that exact mount before continuing.

```bash
df -hT
mount | sort | tee /tmp/brandpilot-mounts.txt
export PERSIST_ROOT=/workspace
test -d "$PERSIST_ROOT" && test -w "$PERSIST_ROOT"
touch "$PERSIST_ROOT/.brandpilot-persistence-test"
sync
test -s /proc/mounts
ls -la "$PERSIST_ROOT/.brandpilot-persistence-test"

export PROJECT_ROOT="$PERSIST_ROOT/brandpilot-local"
if test -d "$PROJECT_ROOT/.git"; then
  git -C "$PROJECT_ROOT" fetch origin
  git -C "$PROJECT_ROOT" switch amd-inference
  git -C "$PROJECT_ROOT" pull --ff-only origin amd-inference
else
  git clone --branch amd-inference --single-branch \
    https://github.com/kmt9967/brandpilot-local.git "$PROJECT_ROOT"
fi
cd "$PROJECT_ROOT"
git status --short --branch
git rev-parse HEAD
```

Create a small environment without downloading any model yet:

```bash
python3 -m venv --system-site-packages "$PERSIST_ROOT/venvs/brandpilot-rocm"
source "$PERSIST_ROOT/venvs/brandpilot-rocm/bin/activate"
python -m pip install --upgrade pip wheel
python -m pip install diffusers transformers accelerate safetensors pillow
python scripts/radeon_environment_check.py \
  --output "$PERSIST_ROOT/evidence/session-1/environment.json"
```

Use the PyTorch already supplied by the Radeon template. Do not replace it unless the environment check proves it is absent or incompatible; installing a ROCm wheel can consume much of the session.

## 20–35 minutes — smallest real inference

Before download, record free space and choose one path:

```bash
df -h "$PERSIST_ROOT"
mkdir -p "$PERSIST_ROOT/model-cache" "$PERSIST_ROOT/outputs/session-1" "$PERSIST_ROOT/evidence/session-1"
export HF_HOME="$PERSIST_ROOT/model-cache"
export MODEL_ID=stabilityai/stable-diffusion-xl-base-1.0
export MODEL_CACHE_DIR="$PERSIST_ROOT/model-cache"
export OUTPUT_DIR="$PERSIST_ROOT/outputs/session-1"
export DEVICE=cuda
export DTYPE=float16
```

Run exactly one real image-to-image smoke test. This command performs real
Diffusers inference and writes measured load/generation timings; it never calls
the mock pipeline:

```bash
python - <<'PY' | tee "$PERSIST_ROOT/evidence/session-1/inference.log"
import json
import os
from pathlib import Path
from time import perf_counter

import torch
from diffusers import AutoPipelineForImage2Image
from PIL import Image, ImageOps

model_id = os.environ["MODEL_ID"]
cache_dir = os.environ["MODEL_CACHE_DIR"]
output_dir = Path(os.environ["OUTPUT_DIR"])
output_dir.mkdir(parents=True, exist_ok=True)
size = 512 if "v1-5" in model_id else 768
output_path = output_dir / "img2img-smoke.png"
input_path = Path("examples/browser-test-product.png")

source = Image.open(input_path).convert("RGB")
fitted = ImageOps.contain(source, (size, size))
canvas = Image.new("RGB", (size, size), (24, 24, 28))
canvas.paste(fitted, ((size - fitted.width) // 2, (size - fitted.height) // 2))

load_started = perf_counter()
pipeline = AutoPipelineForImage2Image.from_pretrained(
    model_id,
    cache_dir=cache_dir,
    torch_dtype=torch.float16,
    use_safetensors=True,
).to("cuda")
torch.cuda.synchronize()
load_seconds = perf_counter() - load_started

torch.cuda.reset_peak_memory_stats()
generator = torch.Generator(device="cuda").manual_seed(20260725)
generation_started = perf_counter()
result = pipeline(
    prompt="premium studio product advertisement, refined red accent, clean background, product centered, no text",
    negative_prompt="distorted product, duplicate product, illegible label, watermark, people",
    image=canvas,
    strength=0.35,
    num_inference_steps=10,
    guidance_scale=5.0,
    generator=generator,
).images[0]
torch.cuda.synchronize()
generation_seconds = perf_counter() - generation_started
result.save(output_path)

print(json.dumps({
    "model": model_id,
    "input": str(input_path),
    "output": str(output_path),
    "width": size,
    "height": size,
    "steps": 10,
    "strength": 0.35,
    "guidance_scale": 5.0,
    "seed": 20260725,
    "load_seconds": load_seconds,
    "generation_seconds": generation_seconds,
    "peak_gpu_memory_bytes": torch.cuda.max_memory_allocated(),
    "device": torch.cuda.get_device_name(0),
    "pytorch_version": torch.__version__,
    "hip_version": torch.version.hip,
}, indent=2))
PY
```

Record the command, wall time, and errors verbatim. Do not call the mock pipeline and do not mark success unless a real output file is created. If SDXL fails for memory, record `rocm-smi`, try one documented Diffusers model-offload configuration, and then switch to:

```bash
export MODEL_ID=stable-diffusion-v1-5/stable-diffusion-v1-5
```

The fallback uses 512×512, 10 steps, strength 0.35, guidance 5.0, and the same seed. Do not try both models after one succeeds.

## 35–40 minutes — evidence and persistence

```bash
date -u +"%Y-%m-%dT%H:%M:%SZ"
rocm-smi --showmeminfo vram --showuse --showproductname \
  | tee "$PERSIST_ROOT/evidence/session-1/rocm-smi-final.txt"
python scripts/radeon_environment_check.py \
  --output "$PERSIST_ROOT/evidence/session-1/environment-final.json"
cp /tmp/brandpilot-torch-environment.txt \
  "$PERSIST_ROOT/evidence/session-1/torch-environment.txt"
cp /tmp/brandpilot-mounts.txt \
  "$PERSIST_ROOT/evidence/session-1/mounts.txt"
find "$PERSIST_ROOT/outputs/session-1" -maxdepth 1 -type f -printf '%f %s bytes\n'
find "$PERSIST_ROOT/evidence/session-1" -maxdepth 1 -type f -printf '%f %s bytes\n'
sync
```

Open the Jupyter file browser and confirm the output and JSON reports are visible under the persistent mount. Do not commit generated output, environment reports containing machine-specific paths, or model caches.

## 40–45 minutes — stop and destroy

```bash
jobs -p
pkill -f 'uvicorn|next-server|jupyter.*brandpilot' 2>/dev/null || true
jobs -p
date -u +"%Y-%m-%dT%H:%M:%SZ"
sync
```

1. Close the terminal.
2. Stop the Radeon Cloud instance.
3. Destroy the instance; do not merely disconnect.
4. Refresh the resource page and confirm no instance is Running, Starting, or Stopping.
5. Record stop time and estimated usage. The maximum target is 45 minutes / 0.75 GPU-hour.

## Evidence checklist

- Start and stop timestamps
- Template/profile name and GPU name
- `rocm-smi`, `rocminfo`, and `/dev/kfd` evidence
- Python, PyTorch, and HIP versions
- Device count/name and total/free VRAM where available
- Repository commit
- Exact model ID and revision
- Exact prompt, input, seed, dimensions, steps, strength, and guidance
- One real output or the exact failure
- Warm-up/load and generation latency kept distinct
- Final proof the instance was destroyed
