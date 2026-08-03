# Final Demo Recording Checklist

Target duration: 3–5 minutes

Record inside the verified Radeon Cloud container using the forwarded `rc-tunnel` URL. Keep the terminal running `python app.py` and the tunnel terminal visible when needed.

## Before recording

- Confirm the container image is `amd-oneclick-base:rocm7.2.1-py3.12-v20260416`.
- Set `TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1`.
- Confirm `torch.cuda.is_available()` is `True`.
- Clear unrelated browser tabs and close PowerPoint or other applications that may show personal information.
- Prepare one reference image and one generated PNG for upload.
- Keep the following verified values available: AMD Radeon Graphics, 47.98 GB VRAM, PyTorch 2.9.1+rocm7.2.1, ROCm/HIP 7.2.53211-e1a6bc5663.

## Shot list and narration

### 1. Opening — 0:00–0:20

Show the project title and the main UI.

Suggested narration:

> Radeon AI Creative Studio is a local multimodal image creation workstation powered by an AMD Radeon GPU and PyTorch ROCm. It supports text-to-image, image-to-image, batch ideation, and deterministic image enhancement.

### 2. Environment — 0:20–0:45

Show the terminal command and its output:

```bash
python -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0)); print(getattr(torch.version, 'hip', None))"
```

Keep the AMD GPU name and `True` visible. Open the forwarded port 7860 page.

### 3. Text-to-image — 0:45–1:25

Use the verified prompt:

```text
A compact cyberpunk night market in Shenzhen, rain reflections, warm shop lights, cinematic composition, editorial concept art
```

Use 512×512, 25 steps, and seed `20260803`. Show the generated image and the AMD GPU information panel.

Narration:

> The prompt is expanded by the local template builder, and diffusion inference runs through PyTorch ROCm on the Radeon GPU. The UI reports the GPU, resolution, seed, steps, and elapsed time for reproducibility.

### 4. Image-to-image — 1:25–2:05

Upload the generated image or a reference image. Keep 512×512, 25 steps, and strength 0.55. Generate one variation and show the result plus GPU information.

Narration:

> The image-to-image workflow preserves the reference composition while applying a new visual direction. The strength parameter controls how much of the original image is retained.

### 5. Batch creation — 2:05–2:50

Use batch size 2, 512×512, 25 steps, and starting seed `20260804`. Show both candidates and the adjacent seeds.

Narration:

> Batch creation produces multiple deterministic candidates from one idea, allowing a designer to compare directions quickly while keeping the generation reproducible.

### 6. Enhancement — 2:50–3:25

Upload one generated image. Select 2× enlargement, enable automatic contrast and detail enhancement. Show the before/after pair and the 1024×1024 output.

Narration:

> The final stage is deterministic Pillow post-processing for fast local enhancement. It is CPU post-processing, while the generation and image-to-image diffusion stages are the AMD GPU workloads.

### 7. Closing — 3:25–3:50

Show the history gallery and output files.

Suggested narration:

> Radeon AI Creative Studio provides a complete local workflow from creative idea or reference image to reproducible candidates and enhanced output, running the key diffusion stages locally on AMD Radeon GPU through ROCm.

## Required screenshots

Capture clear screenshots of:

1. Terminal environment verification with `cuda available: True` and AMD GPU name.
2. Text-to-image result with GPU panel, seed, and elapsed time.
3. Image-to-image result with strength, GPU panel, seed, and elapsed time.
4. Batch gallery showing two candidates and batch GPU information.
5. Enhancement before/after comparison showing 2× output and processing time.
6. History gallery containing the generated outputs.

## Verified values to report

These values were measured on 2026-08-03 and are recorded in `docs/benchmark.md`:

| Function | Result |
|---|---|
| Text-to-image | 512×512, 25 steps, seed 20260803, 105.5 s |
| Image-to-image | 512×512, 25 steps, strength 0.55, seed 300957580, 9.24 s |
| Batch text-to-image | 2 images, 512×512, 25 steps, seed 20260804, 168.56 s total |
| Enhancement | 512×512 → 1024×1024, 2×, 0.092 s |

## Final submission check

- [ ] Video is between 3 and 5 minutes.
- [ ] Actual Radeon GPU execution is visible.
- [ ] All four functions are demonstrated.
- [ ] No fabricated benchmark values are used.
- [ ] README, project PDF, poster, benchmark, and source code are present.
- [ ] Final GitHub PR uses the `dev` branch.
