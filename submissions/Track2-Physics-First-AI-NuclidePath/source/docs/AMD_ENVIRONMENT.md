# AMD Environment Verification

**Verified:** 28 July 2026 (final release rerun)
**Environment:** Radeon Cloud persistent workspace
**Container:** AMD OneClick Base, ROCm 7.2.1, Python 3.12

## Hardware

| Component | Verified value |
|---|---|
| GPU | AMD Radeon Graphics |
| Architecture | `gfx1100` / capability `(11, 0)` |
| Visible VRAM | 49,136 MB |
| ROCm | 7.2.1 |
| AMD driver | 6.16.13 |
| Host OS | Ubuntu 24.04.4 LTS |
| Kernel | 6.8.0-79-generic |
| `/dev/kfd` | present |
| `/dev/dri` | present |

## Toolchain

| Tool | Status |
|---|---|
| `rocminfo` | working |
| `amd-smi` | working |
| `rocm-smi` | working |
| `hipcc` | HIP 7.2.53211 |
| Python | 3.12.3 |
| PyTorch | 2.9.1 ROCm 7.2.1 |
| Triton | 3.5.1 ROCm 7.2.1 |
| NumPy | 2.5.1 |
| pytest | 9.1.1 |

## Verification results (28 July core-platform snapshot)

The following counts are evidence for the recorded AMD workspace/source snapshot,
not a fresh post-merge run of the current `main` tree.

```text
AMD environment check: 6 passed, 0 warnings, 0 failed
Environment verification tests: 4 passed
NuclidePath project suite at historical AMD benchmark checkpoint: 37 passed
Recorded gates in this snapshot: 231 passed on AMD ROCm; controller dependency-light 216 passed/13 optional-PyTorch skips; controller with PyTorch 231 passed
GPU matrix multiplication: passed
```

PyTorch reports:

```text
torch 2.9.1+rocm7.2.1.gitff65f5bc
hip 7.2.53211-e1a6bc5663
available True
count 1
device AMD Radeon Graphics
capability (11, 0)
```

## Re-entering the environment

From the controller VM:

```bash
ssh -i ~/.ssh/id_ed25519 -p <PORT> root@<HOST>
cd /workspace/nuclear-emergency-agent
. .venv/bin/activate
```

The `<HOST>` and `<PORT>` are instance-specific and must be taken from the active Radeon Cloud workspace. Do not commit credentials or private keys.
