# ArtisanAI — SDXL Stylized Image Generation

An image-to-image application built on **SDXL + Canny ControlNet (distilled) + SDXL-Lightning**, with a Gradio web interface and one-click switching between 8 style LoRAs (anime, pixel art, Studio Ghibli, cartoon, oil painting, Pixar, ultra-realistic illustration, 2000s indie comic).

- `app.py` — Gradio web UI, **main entry point**
- `gen_image.py` — model loading, LoRA management, Canny extraction and the instrumented `generate_image()`; imported by `app.py`, and runnable on its own

---

## 1. Environment Setup

### 1.1 Hardware Requirements

| Item | Requirement |
| --- | --- |
| GPU | 1×, ≥ 16 GB VRAM (full fp16 pipeline, no CPU offload) |
| Disk | ≥ 25 GB free (model weights are cached in the project-local `models/`) |
| RAM | ≥ 16 GB |

The code uses PyTorch's `cuda` device name throughout. Under the ROCm build of PyTorch this same API targets the AMD GPU, so no code changes are needed.

### 1.2 Activate the Python Environment

The competition container ships with PyTorch and the other base packages preinstalled — just activate it:

```bash
source /opt/venv/bin/activate
```

> Do not upgrade or uninstall pip packages in this environment. The PyTorch build is tied to the platform driver version.

### 1.3 Install Project Dependencies

```bash
# In restricted networks, if you hit certificate errors
git config --global http.sslVerify false

pip install -r requirement.txt
```

`requirement.txt` only lists the packages that need to be installed on top of the base environment; see the full "Dependencies" section below. If `transformers` / `accelerate` / `peft` are missing from the base environment, install them as well:

```bash
pip install accelerate transformers safetensors peft
```

### 1.4 Model Download (Automatic)

The scripts set the following at import time:

```python
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"          # Hugging Face mirror
os.environ["HF_HOME"]     = "<project dir>/models"           # weight cache directory
```

The first run automatically pulls all weights from the mirror into the project-local `models/` directory (10 GB+ in total, expect a long download). Subsequent launches read straight from the cache. **No manual download is required.**

Models used:

| Purpose | Model |
| --- | --- |
| Base model | `stabilityai/stable-diffusion-xl-base-1.0` (fp16 variant) |
| ControlNet | `diffusers/controlnet-canny-sdxl-1.0-small` (fp16, 320 MB / 160M params — distilled, ~7.8x smaller than a full SDXL ControlNet) |
| VAE | `madebyollin/sdxl-vae-fp16-fix` |
| Acceleration LoRA | `ByteDance/SDXL-Lightning` (`sdxl_lightning_8step_lora.safetensors`) |
| Style LoRAs ×8 | See table below — all from the `ntc-ai/SDXL-LoRA-slider.*` series, 9 MB each |

Style LoRA details (selected by Hugging Face download count, descending):

| UI label | Style | Repository |
| --- | --- | --- |
| 日式动漫 | Anime | `ntc-ai/SDXL-LoRA-slider.anime` |
| 像素艺术 | Pixel art | `ntc-ai/SDXL-LoRA-slider.pixel-art` |
| 吉卜力工作室 | Studio Ghibli | `ntc-ai/SDXL-LoRA-slider.Studio-Ghibli-style` |
| 卡通 | Cartoon | `ntc-ai/SDXL-LoRA-slider.cartoon` |
| 油画 | Oil painting | `ntc-ai/SDXL-LoRA-slider.oil-painting` |
| 皮克斯动画 | Pixar | `ntc-ai/SDXL-LoRA-slider.pixar-style` |
| 超写实插画 | Ultra-realistic illustration | `ntc-ai/SDXL-LoRA-slider.ultra-realistic-illustration` |
| 千禧独立漫画 | 2000s indie comic | `ntc-ai/SDXL-LoRA-slider.2000s-indie-comic-art-style` |

---

## 2. Getting Started

```bash
source /opt/venv/bin/activate
python app.py
```

Startup sequence: load the base model → preload all style LoRAs into VRAM → run one warmup pass on the built-in sample image (compiles CUDA kernels so the first user request isn't slow) → print `Warmup done.` → start the server.

The server listens on `0.0.0.0:7860`:

```
http://<server-ip>:7860
```

If you are running inside a remote container, use SSH port forwarding to reach it from your local machine:

```bash
ssh -L 7860:localhost:7860 <user>@<host>
# then open http://localhost:7860 locally
```

### 2.1 UI Parameters

| Parameter | Default | Description |
| --- | --- | --- |
| Input Image | built-in sample cat image | Input image; resized to 1024×1024 internally, output is restored to the original size |
| Style LoRA | 无 (none) | Switching a style also fills in that style's recommended prompt |
| Prompt / Negative Prompt | varies by LoRA | Positive / negative prompts |
| Strength | 0.7 | Denoising strength — higher means further from the input image |
| ControlNet Scale | 0.5 | Canny conditioning strength — higher means closer to the input edges. Canny gives hard edges, so lower values (0.3-0.4) often look more natural for heavy stylization |
| Steps | 8 | Denoising steps; 8 is enough with the Lightning 8-step LoRA |
| Guidance Scale | 1.0 | `1.0` disables classifier-free guidance, halving the UNet/ControlNet batch. Values above 1 re-enable CFG and roughly double the cost — Lightning is a distilled model and does not need it |
| Seed | 42 | `-1` for random |

Alongside the output image, the UI prints a per-run breakdown — LoRA switch time, Canny extraction (marked `(cached)` on a cache hit), setup, per-step denoise, pipeline total, and peak VRAM — which is handy for performance comparisons:

```
⏱ Total: X.XXs
├─ LoRA:       X.Xms (日式动漫)
├─ Canny:      X.XXs (cached)
├─ Setup:      X.XXs (encode + step1)
├─ Denoise:    X.XXXs/step × 5
├─ Pipe total: X.XXs
└─ VRAM peak:  X.XX GB allocated / X.XX GB reserved
```

Note that the denoise step count shown is the *actual* number executed — in img2img this is `int(steps × strength)`, so the defaults (8 steps × 0.7) run 5 steps, not 8.

### 2.2 Optional: Command-Line Single-Image Generation

To generate one image without starting the UI:

```bash
python gen_image.py
```

Uses the built-in sample image with the prompt `"A robot, 4k photo"`, writes the result to `output_images/robot_cat.png`, and prints **the same timing breakdown the web UI shows**. It runs one warmup pass first and reports only the second run, so the numbers are steady-state — handy for benchmarking without a browser.

`generate_image()` is the single instrumented entry point shared by both the CLI and the web UI, so the two report identical metrics.

---

## 3. Dependencies

### 3.1 Installed on top of the base environment (`requirement.txt`)

| Package | Version constraint | Purpose |
| --- | --- | --- |
| `diffusers` | — | SDXL / ControlNet pipeline |
| `gradio` | `>=4,<5` | Web UI |
| `bitsandbytes` | — | NF4 quantization (the `USE_NF4` switch in `gen_image.py`, off by default) |
| `controlnet-aux` | — | Canny edge detector (`CannyDetector`, OpenCV-based, no weights) |
| `scikit-image` | `>=0.25.0` | Required by `controlnet-aux` |

### 3.2 Required in the base environment

| Package | Purpose |
| --- | --- |
| `torch` | Core framework (tied to the platform driver version — do not upgrade) |
| `transformers` | CLIP text encoders |
| `accelerate` | Model loading and device placement |
| `safetensors` | Weight format |
| `peft` | Multi-LoRA adapter loading and weight blending (`set_adapters`) |
| `numpy` / `Pillow` | Image data handling |

### 3.3 Install Everything

```bash
pip install -r requirement.txt
pip install accelerate transformers safetensors peft
```

---

## 4. Project Layout

```
ArtisanAI/
├── app.py              # Gradio web UI, main entry point
├── gen_image.py        # model/LoRA loading + single-image generation
├── requirement.txt     # additional dependencies
├── models/             # HF model cache (auto-created, gitignored)
├── images/             # input images (sample auto-downloaded, gitignored)
└── output_images/      # single-image output (gitignored)
```

---

## 5. Performance

### 5.1 Measured Results

On the target platform (AMD Radeon Graphics, gfx1100 / RDNA 3, 48 GB VRAM, ROCm 7.2.1, PyTorch 2.9.1), at 1024x1024 with the UI defaults (`steps=8`, `strength=0.7` -> 5 actual denoise steps, `guidance_scale=1.0`), steady state after warmup:

| Stage | Time | Share |
| --- | --- | --- |
| LoRA switch (`set_adapters`) | 48.1 ms | 2.3% |
| Canny extraction | 0.01 s | 0.5% |
| Setup (text/VAE encode + step 1) | 0.60 s | 29.3% |
| Denoise | 0.246 s/step x 4 | 48.0% |
| VAE decode | 0.40 s | 19.5% |
| **End-to-end** | **2.05 s** | 100% |

Peak VRAM: 9.91 GB allocated / 11.21 GB reserved (23% of the 48 GB available).

The 48 ms LoRA switch is the payoff of preloading every adapter into VRAM — reloading from disk on each style change would cost seconds instead.

### 5.2 Optimizations Already in Place


1. **SDXL-Lightning 8-step LoRA** + `EulerDiscreteScheduler(timestep_spacing="trailing")`, cutting 50 steps down to 8.
2. **All style LoRAs preloaded into VRAM** — switching styles only calls `set_adapters` to adjust weights instead of reloading from disk.
3. **Full fp16 pipeline** + `sdxl-vae-fp16-fix` (works around the numerical overflow of the stock VAE in fp16).
4. **Warmup at startup**, moving kernel-compilation cost out of the first user request.
5. **Classifier-free guidance disabled** (`guidance_scale = 1.0`) — the distilled Lightning model does not need CFG, and turning it off halves the UNet/ControlNet batch size.
6. **Distilled ControlNet** — `controlnet-canny-sdxl-1.0-small` has 160M params against the 1.25B of a full SDXL ControlNet, and the Canny detector itself needs no model weights at all.
7. **Canny map caching** — the edge map for the most recent input image is reused, so tweaking the prompt or switching styles on the same image skips edge detection entirely.
8. **`torch.backends.cudnn.benchmark = True`** — input shapes are fixed (1024×1024, batch 1), so MIOpen autotunes convolution algorithms once; the cost is absorbed by the startup warmup and cached on disk.
9. The `USE_NF4` NF4 quantization path is kept but disabled by default (measured gains were poor — see `gen_image.py:8`).

---

## 6. FAQ

**Q: Model downloads are slow or failing.**
The `hf-mirror.com` mirror is already the default. If it still fails, just re-run the script (the HF cache supports resuming), or set `export HF_ENDPOINT=https://hf-mirror.com` beforehand.

**Q: Startup fails with a `gradio_client` schema error.**
`app.py:23-39` already monkey-patches the pydantic-v2 bool-schema bug in `gradio_client 1.3.0`; nothing else is needed.

**Q: Out of memory (OOM).**
Replace `pipe.to("cuda")` with `pipe.enable_model_cpu_offload()` in `gen_image.py`, at the cost of speed.

**Q: Switching LoRAs raises an adapter-related error.**
Check that `peft` is installed — multi-adapter blending depends on it.

---

## Appendix: Development Environment Notes

Enable SSH login inside the container:

```bash
sudo apt update
sudo apt install -y openssh-server
mkdir -p /run/sshd
/usr/sbin/sshd
```

For git push caveats see `.pi/skills/git-push/SKILL.md` (no `git pull` — use fetch + rebase; SSH goes over port 443).
