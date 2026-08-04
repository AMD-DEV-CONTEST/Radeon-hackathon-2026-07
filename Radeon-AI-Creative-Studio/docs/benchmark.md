# Radeon Cloud Benchmark Record

This file records the verified Radeon Cloud UI evidence run completed on 2026-08-04. The timings and parameters below are copied from the application UI screenshots.

## Environment

- Date: 2026-08-04 (UTC+8)
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
python -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0)); print(getattr(torch.version, 'hip', None))"
```

## Measurements

| Task | Resolution | Steps | Batch | Seed | Time | Result |
|---|---:|---:|---:|---:|---:|---|
| Text-to-Image | 512x512 | 25 | 1 | 1065119644 | 2.14 s | Pass |
| Image-to-Image | 512x512 | 25 | 1 | 1131595709 | 0.84 s | Pass |
| Batch Text-to-Image | 512x512 | 15 | 4 | 2006462266-2006462269 | 284.11 s total | Pass |
| Image Enhancement | 512x512 -> 1024x1024 | n/a | 1 | n/a | 0.08 s | Pass |

## Evidence captured

- Text-to-Image completed result with GPU information, seed, steps, resolution, and elapsed time.
- Image-to-Image completed result with reference image, strength, GPU information, seed, and elapsed time.
- Batch gallery with four candidates, adjacent deterministic seeds, and batch GPU information.
- Enhancement before/after comparison with 2x enlargement, 1024x1024 output, and processing information.
- Terminal verification should also show `torch.cuda.is_available(): True`, the AMD Radeon GPU name, and the ROCm/HIP version.

The completed UI screenshots are stored in:

- `assets/evidence/text-to-image.png`
- `assets/evidence/image-to-image.png`
- `assets/evidence/image-enhancement.png`
- `assets/evidence/batch-candidates.png`

## Interpretation notes

- These values represent the completed UI evidence run shown in the submitted screenshots. They may differ from earlier cold-start measurements because model loading, warm-up state, batch size, inference steps, and runtime conditions affect elapsed time.
- The batch evidence run generated four candidates with adjacent deterministic seeds from base seed `2006462266`.
- The image enhancement stage uses deterministic Pillow CPU post-processing. It is not presented as AMD GPU neural inference; the text-to-image, image-to-image, and batch diffusion stages ran through PyTorch ROCm on the AMD Radeon GPU.
