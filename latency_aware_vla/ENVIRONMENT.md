# Environment pins (AMD Radeon Cloud)

Frozen for formal numbers in `artifacts/formal/RESULTS.md`.

## Host

| Item | Value |
|---|---|
| OS | Ubuntu 24.04.4 LTS (noble) |
| Kernel | 6.8.0-79-generic |
| GPU | AMD Radeon Graphics · **gfx1100** · PCI `0x744b` · **48 GB** |
| ROCm | **7.2.1** |
| Python env | `/workspace/rdna` (venv) |

## Python stack (`/workspace/rdna`)

| Package | Version |
|---|---|
| Python | 3.12.3 |
| PyTorch | 2.9.1+rocm7.2.1 |
| LeRobot | **0.4.4** (SmolVLA + π0.5 / RTC path) |
| Genesis (`genesis-world`) | **1.3.1** |
| transformers | 4.53.3 (+ local openpi patch for π0.5) |
| accelerate | 1.14.0 |
| numpy | 2.2.6 |
| Pillow | 11.3.0 |

Full freeze of the venv used for train/eval: `requirements-lock.txt`.

## Notes

- Formal scores use Genesis **AMD GPU render** only (no llvmpipe).
- π0.5 runs in the **same** LeRobot 0.4.4 env with a transformers openpi compatibility patch; we did **not** overwrite the workshop stack with a separate LeRobot 0.6.x install.
- Large weights live under `/workspace/models/` (not committed). Dataset: `datasets/franka-kitchen-fruit-place-120ep`.
