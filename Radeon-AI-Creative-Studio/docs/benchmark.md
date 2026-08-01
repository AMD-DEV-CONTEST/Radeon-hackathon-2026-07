# Radeon Cloud Benchmark Record

This file is the measurement record for the final Radeon Cloud run. Replace the bracketed fields with values copied from the verified container session before submitting the pull request. Do not estimate or invent hardware or timing values.

## Environment

- Date and time: [YYYY-MM-DD HH:MM, UTC+8]
- Container image: [exact image name and tag]
- GPU: [AMD Radeon model]
- VRAM: [value]
- ROCm: [version]
- Python: [version]
- PyTorch: [version]
- Diffusers: 0.35.1
- Gradio: 5.38.2

## Verification command

```bash
python -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
```

## Measurements

| Task | Resolution | Steps | Batch | Seed | Time | Result |
|---|---:|---:|---:|---:|---:|---|
| Text-to-Image | 512x512 | 25 | 1 | [seed] | [seconds] | Pass |
| Image-to-Image | 512x512 | 25 | 1 | [seed] | [seconds] | Pass |
| Batch Text-to-Image | 512x512 | 25 | 2 | [seed] | [seconds] | Pass |
| Image Enhancement | [input] | n/a | 1 | n/a | [seconds] | Pass |

## Evidence to capture

- Terminal output showing `torch.cuda.is_available(): True`.
- Terminal output showing the AMD Radeon GPU name.
- UI screenshot showing the AMD GPU inference panel.
- One text-to-image result.
- One image-to-image result.
- One batch gallery result.
- One enhancement before/after result.
