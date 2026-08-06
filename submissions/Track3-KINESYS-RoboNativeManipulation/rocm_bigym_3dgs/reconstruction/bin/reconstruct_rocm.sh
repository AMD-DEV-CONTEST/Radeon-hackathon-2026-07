#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
EXPECTED_SCENE_HASH=90e70328f9196bc78c7e6c695c1e8cbb55a3c961cccf34c566966a5e2d8d8947
EXPECTED_ARCHIVE_BYTES=910995448
EXPECTED_ARCHIVE_SHA256=9765ce6dd3661ba125b6689c0cc50717645480ec2ce5790a4636129521341adb
EXPECTED_OPENSPLAT_COMMIT=9fb62fde8b7b8c416121d3cbdcda278ffd9682f7

if [[ "${1:-}" == "--print-contract" ]]; then
  printf '%s\n' \
    '{' \
    '  "schema_version": 2,' \
    '  "entrypoint": "reconstruct-rocm",' \
    '  "hardware_gate": "AMD Radeon gfx1100 plus ROCm/HIP",' \
    '  "trainer": "OpenSplat native HIP backend",' \
    '  "opensplat_commit": "9fb62fde8b7b8c416121d3cbdcda278ffd9682f7",' \
    '  "default_train_steps": 15000,' \
    '  "required_env": ["SOURCE_ARCHIVE", "SOURCE_REPORT"],' \
    '  "output_status": "amd_rocm_reproduction_passed"' \
    '}'
  exit 0
fi

SOURCE_ARCHIVE=${SOURCE_ARCHIVE:?set SOURCE_ARCHIVE to the pinned DL3DV archive}
SOURCE_REPORT=${SOURCE_REPORT:?set SOURCE_REPORT to source.json from the downloader}
WORK_ROOT=${WORK_ROOT:-${AMD_BIGYM_ROOT:-/workspace/persistent/amd-bigym-3dgs}/output/reconstruction-rocm}
ROCM_VENV=${ROCM_VENV:-/root/opensplat-env}
OPENSPLAT_SOURCE=${OPENSPLAT_SOURCE:-/root/OpenSplat}
OPENSPLAT_BIN=${OPENSPLAT_BIN:-$OPENSPLAT_SOURCE/build/opensplat}
PYTHON_BIN=${PYTHON_BIN:-$ROCM_VENV/bin/python}
TRAIN_STEPS=${TRAIN_STEPS:-15000}
SAVE_EVERY=${SAVE_EVERY:-$TRAIN_STEPS}
DATA_FACTOR=${DATA_FACTOR:-1}
VALIDATION_IMAGE=${VALIDATION_IMAGE:-frame_00176.png}
HIP_VISIBLE_DEVICES=${HIP_VISIBLE_DEVICES:-0}
BIGYM_DIR=${BIGYM_DIR:-}
WORKSPACE_OBB=${WORKSPACE_OBB:-}
SOURCE_SCREENING_REPORT=${SOURCE_SCREENING_REPORT:-}

PREPARED="$WORK_ROOT/prepared"
TRAINING="$WORK_ROOT/training-$TRAIN_STEPS"
CLEANED="$WORK_ROOT/cleaned-$TRAIN_STEPS"
QUALITY_RAW="$WORK_ROOT/quality-raw-$TRAIN_STEPS"
QUALITY_CLEAN="$WORK_ROOT/quality-clean-$TRAIN_STEPS"
SHELL_ASSETS="$WORK_ROOT/shell-assets-$TRAIN_STEPS"
REPORTS="$WORK_ROOT/reports"
mkdir -p "$TRAINING" "$CLEANED" "$REPORTS"

test -f "$SOURCE_ARCHIVE" || { printf 'Missing source archive: %s\n' "$SOURCE_ARCHIVE" >&2; exit 2; }
test -f "$SOURCE_REPORT" || { printf 'Missing source report: %s\n' "$SOURCE_REPORT" >&2; exit 2; }
test -x "$PYTHON_BIN" || { printf 'Missing ROCm Python: %s\n' "$PYTHON_BIN" >&2; exit 2; }
test "$TRAIN_STEPS" -gt 0 || { printf 'TRAIN_STEPS must be positive.\n' >&2; exit 2; }

"$PYTHON_BIN" - "$SOURCE_ARCHIVE" "$SOURCE_REPORT" \
  "$EXPECTED_SCENE_HASH" "$EXPECTED_ARCHIVE_BYTES" "$EXPECTED_ARCHIVE_SHA256" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

archive = Path(sys.argv[1])
report = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
expected_scene, expected_bytes, expected_sha = sys.argv[3], int(sys.argv[4]), sys.argv[5]
digest = hashlib.sha256()
with archive.open("rb") as handle:
    for chunk in iter(lambda: handle.read(32 * 1024 * 1024), b""):
        digest.update(chunk)
actual = {"bytes": archive.stat().st_size, "sha256": digest.hexdigest()}
if report.get("status") != "complete":
    raise SystemExit("source report is not complete")
if report.get("scene_hash") != expected_scene:
    raise SystemExit("source scene hash mismatch")
if actual != {"bytes": expected_bytes, "sha256": expected_sha}:
    raise SystemExit(f"source archive mismatch: {actual}")
if report.get("archive", {}).get("bytes") != expected_bytes:
    raise SystemExit("source report byte count mismatch")
if report.get("archive", {}).get("sha256") != expected_sha:
    raise SystemExit("source report SHA-256 mismatch")
print(json.dumps({"status": "passed", "scene_hash": expected_scene, **actual}))
PY

"$PYTHON_BIN" - "$REPORTS/amd-rocm-preflight.json" "$HIP_VISIBLE_DEVICES" <<'PY'
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import torch

if not torch.cuda.is_available():
    raise SystemExit("ROCm device is unavailable")
device = torch.cuda.get_device_name(0)
if "AMD" not in device and "Radeon" not in device:
    raise SystemExit(f"expected an AMD Radeon device, found {device!r}")
if not torch.version.hip:
    raise SystemExit("PyTorch does not expose a HIP runtime")
probe = (torch.arange(4096, device="cuda", dtype=torch.float32) ** 2).sum().item()
payload = {
    "schema_version": 1,
    "status": "passed",
    "checked_at": datetime.now(timezone.utc).isoformat(),
    "platform": platform.platform(),
    "python": platform.python_version(),
    "torch": torch.__version__,
    "hip": torch.version.hip,
    "device": device,
    "hip_visible_devices": sys.argv[2],
    "tensor_probe": probe,
}
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print(json.dumps(payload))
PY

if [[ ! -x "$OPENSPLAT_BIN" ]]; then
  "$REPO_ROOT/reconstruction/bin/build_rocm_opensplat_gfx1100.sh" "$OPENSPLAT_SOURCE"
fi
actual_opensplat_commit=$(git -C "$OPENSPLAT_SOURCE" rev-parse HEAD)
if [[ "$actual_opensplat_commit" != "$EXPECTED_OPENSPLAT_COMMIT" ]]; then
  printf 'OpenSplat revision mismatch: %s != %s\n' \
    "$actual_opensplat_commit" "$EXPECTED_OPENSPLAT_COMMIT" >&2
  exit 2
fi

if [[ ! -f "$REPORTS/dataset-preparation.json" ]]; then
  PYTHONPATH="$REPO_ROOT" "$PYTHON_BIN" \
    "$REPO_ROOT/reconstruction/src/prepare_dl3dv_scene.py" \
    --archive "$SOURCE_ARCHIVE" \
    --output "$PREPARED" \
    --report "$REPORTS/dataset-preparation.json"
fi
DATASET="$PREPARED/dataset"
TRANSFORMS=$(find "$PREPARED/extracted" -name transforms.json -type f -print -quit)
test -n "$TRANSFORMS" || { printf 'Prepared scene lacks transforms.json\n' >&2; exit 2; }
REFERENCE_IMAGE=$(find -L "$DATASET/images" -name "$VALIDATION_IMAGE" -type f -print -quit)
test -n "$REFERENCE_IMAGE" || {
  printf 'Held-out image is absent: %s\n' "$VALIDATION_IMAGE" >&2
  exit 2
}

if [[ ! -s "$TRAINING/reconstruction.ply" ]]; then
  STEPS="$TRAIN_STEPS" \
  SAVE_EVERY="$SAVE_EVERY" \
  HIP_VISIBLE_DEVICES="$HIP_VISIBLE_DEVICES" \
  VALIDATION_IMAGE="$VALIDATION_IMAGE" \
  DATA_FACTOR="$DATA_FACTOR" \
  OPENSPLAT_BIN="$OPENSPLAT_BIN" \
  ROCM_VENV="$ROCM_VENV" \
    "$REPO_ROOT/reconstruction/bin/run_rocm_opensplat.sh" \
    "$DATASET" "$TRAINING"
fi

VALIDATION_RENDER="$TRAINING/validation/$TRAIN_STEPS.png"
test -s "$VALIDATION_RENDER" || {
  printf 'OpenSplat validation render is missing: %s\n' "$VALIDATION_RENDER" >&2
  exit 2
}

PYTHONPATH="$REPO_ROOT" "$PYTHON_BIN" \
  "$REPO_ROOT/reconstruction/src/compute_image_metrics.py" \
  --reference "$REFERENCE_IMAGE" \
  --render "$VALIDATION_RENDER" \
  --output "$REPORTS/heldout-metrics.json"

PYTHONPATH="$REPO_ROOT" "$PYTHON_BIN" \
  "$REPO_ROOT/reconstruction/src/validate_gaussian_ply.py" \
  --input "$TRAINING/reconstruction.ply" \
  --camera-path "$TRANSFORMS" \
  --output-dir "$QUALITY_RAW" \
  --clean-output "$CLEANED/reconstruction-cleaned.ply" \
  --metrics "$REPORTS/heldout-metrics.json" \
  --scene-hash "$EXPECTED_SCENE_HASH" \
  --resolution 1920x1080

PYTHONPATH="$REPO_ROOT" "$PYTHON_BIN" \
  "$REPO_ROOT/reconstruction/src/validate_gaussian_ply.py" \
  --input "$CLEANED/reconstruction-cleaned.ply" \
  --camera-path "$TRANSFORMS" \
  --output-dir "$QUALITY_CLEAN" \
  --metrics "$REPORTS/heldout-metrics.json" \
  --scene-hash "$EXPECTED_SCENE_HASH" \
  --resolution 1920x1080

workspace_args=()
if [[ -n "$WORKSPACE_OBB" ]]; then
  test -f "$WORKSPACE_OBB"
  workspace_args=(--workspace-obb "$WORKSPACE_OBB")
elif [[ -n "$BIGYM_DIR" ]]; then
  PYTHONPATH="$BIGYM_DIR:$REPO_ROOT" "$PYTHON_BIN" \
    "$REPO_ROOT/reconstruction/src/measure_bigym_workspace.py" \
    --bigym-dir "$BIGYM_DIR" \
    --task DishwasherUnloadCutleryLong \
    --output "$REPORTS/workspace-obb.json"
  workspace_args=(--workspace-obb "$REPORTS/workspace-obb.json")
fi
screening_args=()
if [[ -n "$SOURCE_SCREENING_REPORT" ]]; then
  test -f "$SOURCE_SCREENING_REPORT"
  screening_args=(--source-screening-report "$SOURCE_SCREENING_REPORT")
fi

PYTHONPATH="$REPO_ROOT" "$PYTHON_BIN" \
  "$REPO_ROOT/reconstruction/src/export_scene_shell.py" \
  --input "$CLEANED/reconstruction-cleaned.ply" \
  --camera-path "$TRANSFORMS" \
  --output "$SHELL_ASSETS" \
  --source-report "$SOURCE_REPORT" \
  --workspace-margin 0.30 \
  --camera-height 1.55 \
  "${workspace_args[@]}" \
  "${screening_args[@]}" \
  >"$REPORTS/scene-shell-export.json"

PYTHONPATH="$REPO_ROOT" "$PYTHON_BIN" \
  "$REPO_ROOT/reconstruction/src/verify_shell_export.py" "$SHELL_ASSETS"

"$PYTHON_BIN" - "$WORK_ROOT" "$TRAIN_STEPS" "$actual_opensplat_commit" \
  "$(basename "$TRAINING")" "$(basename "$CLEANED")" \
  "$(basename "$QUALITY_RAW")" "$(basename "$QUALITY_CLEAN")" \
  "$(basename "$SHELL_ASSETS")" <<'PY'
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1])

def read(relative: str) -> dict:
    return json.loads((root / relative).read_text(encoding="utf-8"))

def artifact(relative: str) -> dict:
    path = root / relative
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(32 * 1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": relative,
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }

training_dir, cleaned_dir = sys.argv[4], sys.argv[5]
quality_raw_dir, quality_clean_dir, shell_dir = sys.argv[6], sys.argv[7], sys.argv[8]
preflight = read("reports/amd-rocm-preflight.json")
metrics = read("reports/heldout-metrics.json")
health = read(f"{quality_clean_dir}/gaussian-health.json")
shell = read(f"{shell_dir}/scene-shell-profile.json")
technical_gates = {
    "amd_rocm_runtime": preflight.get("status") == "passed",
    "heldout_psnr_at_least_27_5": float(metrics["psnr"]) >= 27.5,
    "heldout_ssim_at_least_0_93": float(metrics["ssim"]) >= 0.93,
    "standard_graphdeco_sh3": health["format"]["graphdeco_sh3_exact_order"],
    "finite_gaussians": health["non_finite_records"] == 0,
    "unit_quaternions": health["quaternion_norm"]["max_unit_deviation"] <= 1e-4,
    "no_projected_spikes": health["projected_spikes"]["unique_projected_spikes"] == 0,
    "collision_free_shell": shell["background_physics"]["collision_count"] == 0,
    "empty_central_workspace": shell["central_exclusion"]["visible_gaussian_violations"] == 0,
}
strict_photo_grade_gates = {
    "heldout_psnr_at_least_32": float(metrics["psnr"]) >= 32.0,
    "heldout_ssim_at_least_0_965": float(metrics["ssim"]) >= 0.965,
    "heldout_lpips_measured": metrics.get("lpips") is not None,
}
status = (
    "amd_rocm_reproduction_passed"
    if all(technical_gates.values())
    else "amd_rocm_reproduction_failed"
)
payload = {
    "schema_version": 2,
    "status": status,
    "completed_at": datetime.now(timezone.utc).isoformat(),
    "source_scene_hash": "90e70328f9196bc78c7e6c695c1e8cbb55a3c961cccf34c566966a5e2d8d8947",
    "runtime": preflight,
    "trainer": {
        "name": "OpenSplat",
        "backend": "HIP",
        "commit": sys.argv[3],
        "steps": int(sys.argv[2]),
    },
    "metrics": metrics,
    "technical_gates": technical_gates,
    "strict_photo_grade_gates": strict_photo_grade_gates,
    "quality_status": (
        "strict_photo_grade_passed"
        if all(strict_photo_grade_gates.values())
        else "clear_heldout_pass_strict_photo_grade_target_not_met"
    ),
    "artifacts": {
        "raw_ply": artifact(f"{training_dir}/reconstruction.ply"),
        "cleaned_ply": artifact(f"{cleaned_dir}/reconstruction-cleaned.ply"),
        "shell_ply": artifact(f"{shell_dir}/gaussians_shell.ply"),
        "validation_render": artifact(
            f"{training_dir}/validation/{sys.argv[2]}.png"
        ),
    },
    "cleanup": read(f"{quality_raw_dir}/preview-clean-report.json"),
    "shell_profile": shell,
}
receipt = root / "reports/amd-rocm-reproduction.json"
receipt.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps({"status": status, "receipt": str(receipt), "technical_gates": technical_gates}))
if status != "amd_rocm_reproduction_passed":
    raise SystemExit(1)
PY

printf 'AMD ROCm reproduction passed: %s\n' \
  "$REPORTS/amd-rocm-reproduction.json"
