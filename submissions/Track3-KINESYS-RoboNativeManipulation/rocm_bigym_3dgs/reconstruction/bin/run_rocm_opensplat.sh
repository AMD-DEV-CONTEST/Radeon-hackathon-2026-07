#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 DATASET_DIR OUTPUT_DIR" >&2
  exit 2
fi

dataset_dir=$1
output_dir=$2
steps=${STEPS:-7000}
save_every=${SAVE_EVERY:-3500}
gpu_id=${HIP_VISIBLE_DEVICES:-0}
validation_image=${VALIDATION_IMAGE:-}
data_factor=${DATA_FACTOR:-1}
opensplat_bin=${OPENSPLAT_BIN:-/root/OpenSplat/build/opensplat}
rocm_venv=${ROCM_VENV:-/root/opensplat-env}
site_packages=${ROCM_SITE_PACKAGES:-$rocm_venv/lib/python3.12/site-packages}

if [[ ! -d "$dataset_dir/images" ||
      ! -f "$dataset_dir/sparse/0/cameras.bin" ||
      ! -f "$dataset_dir/sparse/0/images.bin" ||
      ! -f "$dataset_dir/sparse/0/points3D.bin" ]]; then
  echo "expected a COLMAP dataset with images/ and sparse/0/*.bin: $dataset_dir" >&2
  exit 1
fi
if [[ ! -x "$opensplat_bin" ]]; then
  echo "OpenSplat executable is missing or not executable: $opensplat_bin" >&2
  exit 1
fi
if [[ ! -x "$rocm_venv/bin/python" ]]; then
  echo "ROCm Python environment is missing: $rocm_venv" >&2
  exit 1
fi

mkdir -p "$output_dir/validation"

export PATH="$rocm_venv/bin:$PATH"
export HIP_VISIBLE_DEVICES="$gpu_id"
export LD_LIBRARY_PATH="$site_packages/torch/lib:$site_packages/_rocm_sdk_core/lib:$site_packages/_rocm_sdk_core/lib/host-math/lib:$site_packages/_rocm_sdk_core/lib/rocm_sysdeps/lib:$site_packages/_rocm_sdk_devel/lib:$site_packages/_rocm_sdk_devel/lib/host-math/lib:$site_packages/_rocm_sdk_libraries_gfx110X_all/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

"$rocm_venv/bin/python" - "$output_dir/run-metadata.json" "$opensplat_bin" "$steps" <<'PY'
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import torch

path = Path(sys.argv[1])
opensplat_bin = Path(sys.argv[2])
steps = int(sys.argv[3])
commit = subprocess.run(
    ["git", "-C", str(opensplat_bin.parent.parent), "rev-parse", "HEAD"],
    check=False,
    capture_output=True,
    text=True,
).stdout.strip()
payload = {
    "schema_version": 1,
    "started_at": datetime.now(timezone.utc).isoformat(),
    "steps": steps,
    "hip_visible_devices": os.environ["HIP_VISIBLE_DEVICES"],
    "torch": torch.__version__,
    "torch_hip": torch.version.hip,
    "gpu": torch.cuda.get_device_name(0),
    "opensplat_commit": commit or None,
}
path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY

validation_args=()
if [[ -n "$validation_image" ]]; then
  validation_args=(--val-image "$validation_image")
fi

"$opensplat_bin" "$dataset_dir" \
  -n "$steps" \
  -d "$data_factor" \
  --num-downscales 0 \
  --val \
  "${validation_args[@]}" \
  --val-render "$output_dir/validation" \
  -s "$save_every" \
  -o "$output_dir/reconstruction.ply" \
  2>&1 | tee "$output_dir/train.log"
