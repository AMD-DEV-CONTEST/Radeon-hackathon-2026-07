# Canonical reconstruction

This directory contains two explicit reconstruction paths for the same pinned
DL3DV commercial-kitchen scene:

- `reconstruct_rocm.sh`: the AMD Radeon `gfx1100` main path, using OpenSplat's
  native HIP backend;
- `reconstruct.sh`: the locked cross-platform/legacy gsplat reference implementation retained
  for provenance and cross-platform comparison.

The source object is
[`4K/90e70328...zip`](https://huggingface.co/datasets/DL3DV/DL3DV-ALL-2K/blob/e035bc5efd8dc5b2fa1e704cb2b1086fd9ec2c5c/4K/90e70328f9196bc78c7e6c695c1e8cbb55a3c961cccf34c566966a5e2d8d8947.zip)
at revision `e035bc5efd8dc5b2fa1e704cb2b1086fd9ec2c5c`.

## AMD Radeon / ROCm path

The reproduced environment is AMD Radeon PRO W7900D (`gfx1100`) with
PyTorch ROCm and OpenSplat commit
`9fb62fde8b7b8c416121d3cbdcda278ffd9682f7`.

Install the Python-side data and validation dependencies into the same ROCm
environment that provides PyTorch:

```bash
python -m pip install -r reconstruction/requirements-core.txt

git clone https://github.com/pierotofy/OpenSplat.git /root/OpenSplat
git -C /root/OpenSplat checkout --detach \
  9fb62fde8b7b8c416121d3cbdcda278ffd9682f7

export ROCM_VENV=/root/opensplat-env
export OPENSPLAT_SOURCE=/root/OpenSplat
make build-opensplat
```

The build helper applies only the two checked-in HIP portability patches,
targets `gfx1100`, and refuses any other OpenSplat commit.

Download and verify the gated source locally:

```bash
hf auth login
python -m pip install -r reconstruction/requirements-core.txt
make download-reference-data
```

Then load the example environment and run the complete AMD path:

```bash
cp reconstruction/config/rocm.env.example .rocm.env
set -a && source .rocm.env && set +a
make reconstruct-rocm
```

The entrypoint verifies the exact source bytes, runs a live AMD tensor probe,
trains and renders a held-out view, normalizes OpenSplat quaternions, removes
robust-radius outliers invisible from every supplied camera and obvious
high-alpha projected streaks, validates the cleaned PLY, and exports the
collision-free room-shell layers. A run is accepted only when its
machine-readable receipt is
`amd_rocm_reproduction_passed`.

## Cross-platform reference path

The legacy reference path remains:

```bash
export SOURCE_ARCHIVE="$PWD/data/private/dl3dv-kitchen/90e70328f9196bc78c7e6c695c1e8cbb55a3c961cccf34c566966a5e2d8d8947.zip"
export SOURCE_REPORT="$PWD/data/private/dl3dv-kitchen/source.json"
export GSPLAT_DIR=/workspace/gsplat
export BIGYM_DIR=/workspace/amd-bigym-3dgs/src/bigym
export WORK_ROOT=/workspace/runs/dl3dv-commercial-kitchen-reference
reconstruction/bin/reconstruct.sh
```

Its exact published hashes are locked in
`data/manifests/reference-reconstruction.public.json`.

## CPU contract test

```bash
make smoke-reconstruction
```

This license-free test verifies the exporter and zero-background-physics
contract. It does not substitute for either GPU run.
