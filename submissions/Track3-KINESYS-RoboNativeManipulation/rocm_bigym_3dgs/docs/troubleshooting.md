# Troubleshooting

## `torch.version.hip is None`

You are using non-ROCm PyTorch (CPU or another backend), not an ROCm build. Reinstall according to AMD official compatibility matrix, then rebuild gsplat.

## `hipcc` exists but JIT still looks for `nvcc`

Confirm `ROCM_HOME` points to the repository-created wrapper, the wrapper `bin` is first in `PATH`, and reset `TORCH_EXTENSIONS_DIR` to an empty isolated path.

## Repeated rocThrust / BF16 definitions

This is usually caused by ROCm system headers being hipified or mixed include order with duplicated headers. Reinstall/verify official `hip-dev` and `rocthrust-dev`; rebuild only in isolated wrapper and virtual environment. Do not edit `/opt/rocm/include`.

## Strange symbols after GLM HIP conversion

Do not pass GLM as `extra_include_paths` for PyTorch JIT. The project patch removes this path and uses `CPLUS_INCLUDE_PATH` to point directly to the original gsplat GLM tree.

## Many `reward=0`

Stop formal rendering and rerun 20 Hz physics-only verifier. Check demo absolute/delta representation, BiGym/MuJoCo versions, and seed; failed trajectories should not enter successful training set.

## "Only one episode" appears in folder

Do not judge by chunk count in directories. Read `meta/episodes`, data Parquet `episode_index`, row ranges, and `meta/info.json`. This repository's validator makes conclusions using these fields.

## Room shell is not visible despite running

Check in order:

1. Confirm profile points to an existing PLY.
2. `T_gaussian_to_mujoco` is not an identity placeholder.
3. Camera is near captured path.
4. strict receipt has `enabled=true`, `last_error=null`, and render count greater than 0.
5. Frame counts are not sufficient; inspect decoded multi-camera visuals.

## Shell is visible but low-angle blur/stretching remains

This is usually missing source coverage, not solved by aggressive point removal. Conservative cleanup can remove very low alpha, oversized scale, and distant outliers; for near-photo photometric quality, recollect coverage around H1 head and wrist poses and retrain.
