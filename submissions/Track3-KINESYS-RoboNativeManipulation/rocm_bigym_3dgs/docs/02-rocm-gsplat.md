# ROCm reconstruction and rendering notes

## Why AMD reconstruction uses OpenSplat

This repository separates the training reconstruction stage and BiGym runtime rendering into two independent gates:

| Stage | AMD implementation | Acceptance method |
| --- | --- | --- |
| DL3DV training and PLY export | OpenSplat native HIP backend | W7900D on-device training, held-out rendering, and PLY structure/outlier checks |
| BiGym triple-camera rendering | `gfx1100` adaptation in `gsplat==1.4.0` | Native rasterization smoke test, strict triple-camera mode, no fallback |

On this W7900D hardware, the locked AMD gsplat code triggers a `rocPRIM` wave64 static assertion under wave32. The official prebuilt wheel also lacks `gfx1100` code objects. Therefore, the reconstruction entry uses OpenSplat HIP backend compiled and executed on the same hardware, with PLY export on-device, rather than treating a successful `import` or gsplat compile failure alone as completed reconstruction.

## Locked AMD reconstruction environment

| Component | On-device value |
| --- | --- |
| GPU | AMD Radeon PRO W7900D, `gfx1100`, 48GB |
| PyTorch | `2.8.0+rocm7.13.0a20260513` |
| HIP | `7.13.26183-83e9908b71` |
| OpenSplat | commit `9fb62fde8b7b8c416121d3cbdcda278ffd9682f7` |
| Input | `1920x1080` DL3DV commercial kitchen images, 352 total |
| Default training | 15,000 steps, per-frame held-out validation |

`reconstruction/bin/reconstruct_rocm.sh` executes in order:

1. Locks source package revision, byte size, SHA-256, and ZIP CRC.
2. Runs real AMD/HIP tensor probes.
3. Builds COLMAP initialization with known-pose SIFT triangulation.
4. Launches OpenSplat HIP training and outputs held-out renderings.
5. Normalizes OpenSplat quaternions, removes points outside robust radius that are invisible to all cameras, and removes obvious high-alpha streak projections.
6. Revalidates cleaned PLY and exports the central room shell with four layers, clear passage, and zero-collision constraints.
7. Writes `amd-rocm-reproduction.json`.

## gsplat runtime gate

`patches/gsplat-1.4.0-rocm-gfx1100.patch` and the isolated compiler wrapper are still used for BiGym real-time triple-camera Gaussian rasterization. It does not modify `/opt/rocm`, and JIT cache is kept in separate `TORCH_EXTENSIONS_DIR`.

`import gsplat` alone is not enough. `scripts/smoke_test_gsplat.py` must actually run rasterization, GPU synchronization, and verify RGB/alpha shape plus finite values. Reconstruction receipts and runtime rendering receipts cannot replace each other.
