# MiniMax H3 · AMD Radeon (ROCm) Benchmarks

Measured on: **AMD Radeon PRO W7900** (gfx1100, RDNA3, 48 GB VRAM, 864 GB/s)
ROCm 7.2.4 · ComfyUI 0.30.0 · pruned int8 diffusion + int8 Qwen3-VL-32B

## Summary

| Mode | Resolution | Frames | Duration | Wall time | Note |
|------|-----------|--------|----------|-----------|------|
| T2V | 864x480 | 124 | ~5.2s | cold start 10:42 | includes model load |
| T2V | 608x352 | 56 | ~2.3s | 75s | warm models |
| T2V | 864x480 | 56 | ~2.3s | 170s | warm models |
| T2V | 864x480 | 56 | ~2.3s | 170s | warm models |
| **I2V** | 864x480 | 124 | ~5.2s | **617s** | keyframe-conditioned, warm models |
| **I2V** | 864x480 | 124 | ~5.2s | **553s** | keyframe-conditioned, warm models |

> I2V (image-conditioned) is the slowest mode: reference/keyframe tokens ride
> through every sampling step. Honest disclosure: a ~5 s I2V clip at 864x480
> takes ~9-10 minutes on this card.
>
> First run (cold) also loads ~26 GB UNet + 26 GB text encoder + VAEs from disk.
> Once loaded, subsequent runs only pay sampling + decode time.

## Model footprint (int8 pruned set, fits 48 GB VRAM)

| Component | File | Size |
|-----------|------|------|
| Diffusion (FL2VA) | minimax_h3_fl2va_pruned_int8_convrot.safetensors | 20.97 GB |
| Diffusion (Ref2VA) | minimax_h3_ref2va_pruned_int8_convrot.safetensors | 20.97 GB |
| Text encoder | qwen3vl_32b_minimax_h3_int8_convrot.safetensors | 27.14 GB |
| Video VAE | minimax_h3_video_vae_fp16.safetensors | 5.21 GB |
| Audio VAE | minimax_h3_audio_vae_fp32.safetensors | 0.61 GB |

## Sampling config

- Sampler: `res_multistep`
- Scheduler: `simple`
- Steps: 20
- Frame grid: 17k+5 @ 24 fps (56 frames ≈ 2.3 s, 124 ≈ 5.2 s)

## Reproduction

```bash
# start ComfyUI
cd /opt/ComfyUI && /opt/venv/bin/python main.py --listen 0.0.0.0 --port 8188

# validate all three modes against the live server (no generation)
python app/bench.py --all --skip-queue

# run a timed T2V generation
python app/bench.py --mode t2v --width 864 --height 480 --duration 5 --out benchmarks/run.json

# unit tests (no GPU / server needed)
python app/test_comfy_client.py
```

`app/bench.py` also samples the runner's peak RSS (per run) and writes JSON
results for reproducible reporting.
