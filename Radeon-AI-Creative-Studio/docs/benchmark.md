# Radeon Cloud Benchmark Record

This file records the verified Radeon Cloud run completed on 2026-08-03. The timings below are copied from the application UI.

## Environment

- Date: 2026-08-03 (UTC+8)
- Container image: AMD OneClick Base (`amd-oneclick-base:rocm7.2.1-py3.12-v20260416`)
- GPU: AMD Radeon Graphics
- VRAM: 47.98 GB
- ROCm/HIP: 7.2.53211-e1a6bc5663
- Python: 3.12.3
- PyTorch: 2.9.1+rocm7.2.1.gitff65f5bc
- Diffusers: 0.35.1
- Gradio: 5.38.2

## Verification command

```bash
python -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
```

## Measurements

| Task | Resolution | Steps | Batch | Seed | Time | Result |
|---|---:|---:|---:|---:|---:|---|
| Text-to-Image | 512x512 | 25 | 1 | 20260803 | 105.5 s | Pass |
| Image-to-Image | 512x512 | 25 | 1 | 300957580 | 9.24 s | Pass |
| Batch Text-to-Image | 512x512 | 25 | 2 | 20260804 | 168.56 s total | Pass |
| Image Enhancement | 512x512 → 1024x1024 | n/a | 1 | n/a | 0.092 s | Pass |

## Evidence to capture

- Terminal output showing `torch.cuda.is_available(): True`.
- Terminal output showing the AMD Radeon GPU name.
- UI screenshot showing the AMD GPU inference panel.
- One text-to-image result.
- One image-to-image result.
- One batch gallery result.
- One enhancement before/after result.

## Interpretation notes

- The first text-to-image run was the first generation after application startup and may include model warm-up or initialization overhead. The UI-reported value is retained exactly as observed.
- The image enhancement stage uses deterministic Pillow CPU post-processing. It is not presented as AMD GPU neural inference; the text-to-image, image-to-image, and batch diffusion stages ran through PyTorch ROCm on the AMD Radeon GPU.
