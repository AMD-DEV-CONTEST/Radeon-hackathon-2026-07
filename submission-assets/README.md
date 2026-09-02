# Generated Poster Gallery

AI-generated music event posters produced by StagePoster on AMD Radeon PRO W7900 + ROCm 7.2.

Each run shows the full workflow: Qwen3.5-9B art direction → Z-Image Turbo GPU generation → user selection → deterministic Go composition → Qwen Vision review optimization.

## Structure

Each poster run contains 3 stages:

| File | Description |
|---|---|
| `*-final.png` | Final composed poster (1024×1536, 300 DPI) — text + logo + QR composed deterministically in Go |
| `*-review2.png` | After Qwen Vision round-2 auto-optimization |
| `*-thumb.png` | Thumbnail (512×768) |

## Poster Runs

| Run | GPU candidates | Review rounds | Model |
|---|---|---|---|
| `5b5c743a` | 3 | 2 | Z-Image Turbo BF16 |
| `617769eb` | 3 | 2 | Z-Image Turbo BF16 |
| `680e73d2` | 3 | 2 | Z-Image Turbo BF16 |

All images generated live on AMD Radeon PRO W7900 48 GB via ROCm 7.2, ComfyUI + Z-Image Turbo + Z-Image ControlNet.
