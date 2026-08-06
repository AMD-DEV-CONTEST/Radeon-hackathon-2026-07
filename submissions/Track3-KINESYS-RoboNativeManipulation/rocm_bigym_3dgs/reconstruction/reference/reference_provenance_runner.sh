#!/usr/bin/env bash
set -Eeuo pipefail

readonly SCRATCH="/scratch"
readonly PROJECT="${SCRATCH}/project"
readonly INPUT="${SCRATCH}/input"
readonly PREPARED="${SCRATCH}/prepared"
readonly TRAIN_ROOT="${SCRATCH}/training"
readonly FULL_ASSETS="${SCRATCH}/full-assets"
readonly SHELL_ASSETS="${SCRATCH}/shell-assets"
readonly DEMO="${SCRATCH}/demo"
readonly BIGYM_DEMO="${SCRATCH}/bigym-demo"
readonly RESULTS="${SCRATCH}/results"
readonly EXPORT="${SCRATCH}/export"
readonly FRONTEND="${SCRATCH}/frontend"
readonly GSPLAT_DIR="${SCRATCH}/gsplat-v1.4.0"
readonly DISCOVERSE_DIR="${SCRATCH}/DISCOVERSE"
readonly CUDA_TOOLKIT_DIR="${SCRATCH}/cuda-toolkit-12.1"
readonly ARCHIVE="${EXPORT}/deliverables.tar.zst"
readonly GSPLAT_URL="https://github.com/nerfstudio-project/gsplat.git"
readonly GSPLAT_REVISION="4d3a3b69db4de0326f983ccf7b7b255271a17b01"
readonly DISCOVERSE_URL="https://github.com/discoverse-dev/DISCOVERSE.git"
readonly DISCOVERSE_REVISION="d67f47c084aba0e0cf422a8725235f8b9238655a"
readonly RENDERER_VERSION="0.2.0"
readonly RENDERER_SHA256="a5068d1b58cd174d315a591cdc6e2c26b271306074a8d11cdd02c60bbe58b7de"
readonly GSPLAT_WHEEL="${INPUT}/gsplat-1.4.0-cp310-cp310-linux_x86_64.whl"
readonly GSPLAT_WHEEL_SHA="${GSPLAT_WHEEL}.sha256"
readonly EXPECTED_SCENE_PROFILE="${SCENE_SHELL_SOURCE_PROFILE:-art-gallery}"
readonly EXPECTED_SCENE_HASH="${SCENE_SHELL_SOURCE_HASH:-}"

export MUJOCO_GL=egl
export PYOPENGL_PLATFORM=egl
export QT_QPA_PLATFORM=offscreen
export CUDA_VISIBLE_DEVICES=0
export CUDA_HOME="${CUDA_TOOLKIT_DIR}"
export PATH="${CUDA_HOME}/bin:${PATH}"
export LD_LIBRARY_PATH="${CUDA_HOME}/lib:${CUDA_HOME}/lib64:${LD_LIBRARY_PATH:-}"
export MAX_JOBS=8
export TORCH_EXTENSIONS_DIR="${SCRATCH}/torch-extensions"
export XDG_CACHE_HOME="${SCRATCH}/cache"
export TORCH_HOME="${SCRATCH}/cache/torch"
export PYTHONUNBUFFERED=1
export OMP_NUM_THREADS=8
export PYTHONPATH="${PROJECT}:${DISCOVERSE_DIR}:${PYTHONPATH:-}"

mkdir -p \
  "${PROJECT}" "${INPUT}" "${PREPARED}" "${TRAIN_ROOT}" "${FULL_ASSETS}" \
  "${SHELL_ASSETS}" "${DEMO}" "${BIGYM_DEMO}" "${RESULTS}" "${EXPORT}" \
  "${FRONTEND}" "${XDG_CACHE_HOME}"

stage="waiting-for-local-input"

announce() {
  printf 'AMD_COMPETITION_SCENE_SHELL_STAGE=%s time=%s\n' \
    "${stage}" "$(date --iso-8601=seconds)"
}

write_blocked_report() {
  local report_exit_code="$1"
  python3 - "${RESULTS}" "${stage}" "${report_exit_code}" <<'PY'
import datetime
import json
import pathlib
import sys

result_dir = pathlib.Path(sys.argv[1])
result_dir.mkdir(parents=True, exist_ok=True)
report = {
    "schema_version": 1,
    "status": "blocked",
    "failed_stage": sys.argv[2],
    "exit_code": int(sys.argv[3]),
    "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "credentials_received_by_cluster": False,
}
(result_dir / "scene-shell-report.json").write_text(
    json.dumps(report, indent=2) + "\n", encoding="utf-8"
)
PY
}

package_results() {
  rm -f "${ARCHIVE}"
  python3 - "${ARCHIVE}" "${FULL_ASSETS}" "${SHELL_ASSETS}" "${DEMO}" \
    "${BIGYM_DEMO}" "${RESULTS}" <<'PY'
import pathlib
import sys
import tarfile

import zstandard

archive_path = pathlib.Path(sys.argv[1])
roots = [pathlib.Path(value) for value in sys.argv[2:]]
with archive_path.open("wb") as raw:
    compressor = zstandard.ZstdCompressor(level=5, threads=4)
    with compressor.stream_writer(raw, closefd=False) as compressed:
        with tarfile.open(fileobj=compressed, mode="w|") as archive:
            for root in roots:
                if not root.exists():
                    continue
                for path in sorted(root.rglob("*")):
                    if path.is_file():
                        archive.add(
                            path,
                            arcname=f"{root.name}/{path.relative_to(root)}",
                        )
PY
}

wait_for_release() {
  while [[ ! -e "${SCRATCH}/release" ]]; do
    sleep 5
  done
}

on_error() {
  local -r pipeline_exit_code=$?
  trap - ERR
  set +e
  write_blocked_report "${pipeline_exit_code}"
  if [[ -s "${FULL_ASSETS}/gaussians.ply" ]]; then
    mkdir -p "${RESULTS}/recovery-full-assets"
    cp "${FULL_ASSETS}/gaussians.ply" \
      "${RESULTS}/recovery-full-assets/gaussians.ply"
    cp "${FULL_ASSETS}/camera-path.json" \
      "${RESULTS}/recovery-full-assets/camera-path.json"
  fi
  python3 -m pip install --quiet "zstandard==0.23.0" >/dev/null 2>&1
  package_results
  archive_sha="$(sha256sum "${ARCHIVE}" | awk '{print $1}')"
  archive_bytes="$(stat -c '%s' "${ARCHIVE}")"
  printf 'AMD_COMPETITION_SCENE_SHELL_ARCHIVE={"status":"blocked","stage":"%s","exit_code":%s,"archive":"%s","bytes":%s,"sha256":"%s"}\n' \
    "${stage}" "${pipeline_exit_code}" "${ARCHIVE}" "${archive_bytes}" "${archive_sha}"
  printf 'AMD_COMPETITION_SCENE_SHELL_READY={"status":"blocked","viewer_started":false,"stage":"%s","exit_code":%s}\n' \
    "${stage}" "${pipeline_exit_code}"
  wait_for_release
  exit "${pipeline_exit_code}"
}
trap on_error ERR

announce
input_deadline=$((SECONDS + 1800))
pretrained_inputs_missing() {
  [[ -e "${INPUT}/pretrained-requested" ]] \
    && {
      [[ ! -s "${INPUT}/pretrained-gaussians.ply" ]] \
        || [[ ! -s "${INPUT}/pretrained-camera-path.json" ]] \
        || [[ ! -s "${INPUT}/pretrained-candidate-selection.json" ]]
    }
}
while [[ ! -s "${INPUT}/scene.zip" ]] \
  || [[ ! -s "${INPUT}/source.json" ]] \
  || [[ ! -s "${GSPLAT_WHEEL}" ]] \
  || [[ ! -s "${GSPLAT_WHEEL_SHA}" ]] \
  || [[ ! -s "${PROJECT}/competition/viewer/backend/app.py" ]] \
  || [[ ! -s "${FRONTEND}/index.html" ]] \
  || {
    [[ "${EXPECTED_SCENE_PROFILE}" = "screened-kitchen" ]] \
      && [[ ! -s "${INPUT}/source-center-screening.json" ]]
  } \
  || pretrained_inputs_missing; do
  if (( SECONDS >= input_deadline )); then
    echo "timed out waiting for source archive and project bundle" >&2
    exit 10
  fi
  sleep 2
done

date --iso-8601=seconds >"${RESULTS}/started-at.txt"
nvidia-smi >"${RESULTS}/nvidia-smi.txt" 2>&1

stage="source-integrity"
announce
python3 - "${INPUT}/scene.zip" "${INPUT}/source.json" \
  "${EXPECTED_SCENE_PROFILE}" "${EXPECTED_SCENE_HASH}" \
  >"${RESULTS}/source-verification.json" <<'PY'
import hashlib
import json
import pathlib
import sys

archive = pathlib.Path(sys.argv[1])
source = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
expected_profile = sys.argv[3]
expected_hash = sys.argv[4]
allowed_revisions = {
    "e035bc5efd8dc5b2fa1e704cb2b1086fd9ec2c5c",
}
if source.get("status") != "complete":
    raise SystemExit("local source report is not complete")
if source.get("revision") not in allowed_revisions:
    raise SystemExit("source pin mismatch")
if expected_profile in {"screened-kitchen", "full-kitchen"}:
    if not expected_hash or source.get("scene_hash") != expected_hash:
        raise SystemExit("screened source hash mismatch")
elif source.get("scene") != expected_profile:
    raise SystemExit("source profile mismatch")
digest = hashlib.sha256()
with archive.open("rb") as handle:
    for chunk in iter(lambda: handle.read(32 * 1024 * 1024), b""):
        digest.update(chunk)
actual = {"bytes": archive.stat().st_size, "sha256": digest.hexdigest()}
if actual != {
    "bytes": int(source["archive"]["bytes"]),
    "sha256": source["archive"]["sha256"],
}:
    raise SystemExit(f"streamed archive differs from local report: {actual}")
print(json.dumps({
    "status": "passed",
    "scene": source.get("scene"),
    "scene_hash": source["scene_hash"],
    "revision": source.get("revision"),
    "resolution": source.get("resolution", "960P"),
    "archive": actual,
    "credentials_received_by_cluster": False,
}))
PY

stage="dependencies-and-pinned-sources"
announce
conda create -y -p "${CUDA_TOOLKIT_DIR}" --override-channels -c nvidia \
  "cuda-nvcc=12.1.105" \
  "cuda-cudart=12.1.105" \
  "cuda-cudart-dev=12.1.105" \
  "cuda-cccl=12.1.109" \
  >"${RESULTS}/cuda-toolchain.log" 2>&1
test -x "${CUDA_TOOLKIT_DIR}/bin/nvcc"
test -s "${CUDA_TOOLKIT_DIR}/include/thrust/complex.h"
"${CUDA_TOOLKIT_DIR}/bin/nvcc" --version \
  >>"${RESULTS}/cuda-toolchain.log" 2>&1

python3 -m pip install --no-cache-dir \
  "numpy==1.26.4" \
  "zstandard==0.23.0" \
  "plyfile==1.1" \
  "mujoco==3.10.0" \
  "gymnasium==1.3.0" \
  "safetensors==0.6.2" \
  "dm-control==1.0.43" \
  "pyquaternion==0.9.9" \
  "mujoco-utils==0.0.6" \
  "mojo-mujoco-wrapper==0.1.1" \
  "wget==3.2" \
  "dearpygui==1.11.1" \
  "pyopenxr==1.1.4902" \
  "av==12.3.0" \
  "fastapi==0.115.8" \
  "uvicorn[standard]==0.34.0" \
  "wsproto==1.2.0" \
  "viser==0.2.1" \
  "nerfview==0.0.2" \
  "opencv-python-headless==4.10.0.84" \
  "imageio[ffmpeg]==2.36.0" \
  "scikit-learn==1.5.2" \
  "torchmetrics[image]==1.5.2" \
  "tqdm==4.66.6" \
  "scikit-image==0.24.0" \
  "transformers==4.57.1" \
  "accelerate==1.10.1" \
  "sentencepiece==0.2.1" \
  "tyro==0.9.1" \
  "tensorboard" \
  "tensorly" \
  "matplotlib" \
  >"${RESULTS}/dependencies.log" 2>&1
python3 -m pip install --no-cache-dir --no-deps -e "${PROJECT}" \
  >>"${RESULTS}/dependencies.log" 2>&1
python3 -m pip install --no-cache-dir \
  "git+https://github.com/rmbrualla/pycolmap@cc7ea4b7301720ac29287dbe450952511b32125e" \
  >>"${RESULTS}/dependencies.log" 2>&1

git clone --filter=blob:none "${GSPLAT_URL}" "${GSPLAT_DIR}" \
  >"${RESULTS}/gsplat-setup.log" 2>&1
git -C "${GSPLAT_DIR}" checkout --detach "${GSPLAT_REVISION}" \
  >>"${RESULTS}/gsplat-setup.log" 2>&1
git -C "${GSPLAT_DIR}" submodule update --init --recursive \
  >>"${RESULTS}/gsplat-setup.log" 2>&1
test "$(git -C "${GSPLAT_DIR}" rev-parse HEAD)" = "${GSPLAT_REVISION}"
test -s "${GSPLAT_DIR}/gsplat/cuda/csrc/third_party/glm/glm/glm.hpp"
if [[ -s "${GSPLAT_WHEEL}" ]] && [[ -s "${GSPLAT_WHEEL_SHA}" ]]; then
  expected_wheel_sha="$(awk 'NR==1 {print $1}' "${GSPLAT_WHEEL_SHA}")"
  test "$(sha256sum "${GSPLAT_WHEEL}" | awk '{print $1}')" = "${expected_wheel_sha}"
  python3 -m pip install --no-cache-dir "${GSPLAT_WHEEL}" \
    >>"${RESULTS}/gsplat-setup.log" 2>&1
  printf 'installed_binary_wheel=%s sha256=%s\n' \
    "${GSPLAT_WHEEL}" "${expected_wheel_sha}" \
    >>"${RESULTS}/gsplat-setup.log"
else
  python3 -m pip install --no-cache-dir --no-build-isolation -e "${GSPLAT_DIR}" \
    >>"${RESULTS}/gsplat-setup.log" 2>&1
fi

git clone --filter=blob:none "${DISCOVERSE_URL}" "${DISCOVERSE_DIR}" \
  >"${RESULTS}/discoverse-setup.log" 2>&1
git -C "${DISCOVERSE_DIR}" checkout --detach "${DISCOVERSE_REVISION}" \
  >>"${RESULTS}/discoverse-setup.log" 2>&1
test "$(git -C "${DISCOVERSE_DIR}" rev-parse HEAD)" = "${DISCOVERSE_REVISION}"

mkdir -p "${INPUT}/python"
python3 -m pip download --no-deps --no-binary=:all: \
  "gaussian-renderer==${RENDERER_VERSION}" \
  --dest "${INPUT}/python" >"${RESULTS}/renderer-download.log" 2>&1
renderer_sdist="${INPUT}/python/gaussian_renderer-${RENDERER_VERSION}.tar.gz"
test -s "${renderer_sdist}"
test "$(sha256sum "${renderer_sdist}" | awk '{print $1}')" = "${RENDERER_SHA256}"
python3 -m pip install --no-cache-dir --no-deps "${renderer_sdist}" \
  >"${RESULTS}/renderer-install.log" 2>&1

python3 - "${GSPLAT_DIR}/examples/simple_trainer.py" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = text.replace("from fused_ssim import fused_ssim\n", "")
old = """            ssimloss = 1.0 - fused_ssim(
                colors.permute(0, 3, 1, 2), pixels.permute(0, 3, 1, 2), padding="valid"
            )
"""
new = """            ssimloss = 1.0 - self.ssim(
                colors.permute(0, 3, 1, 2), pixels.permute(0, 3, 1, 2)
            )
"""
if old not in text:
    raise SystemExit("expected fused_ssim block was not found")
path.write_text(text.replace(old, new), encoding="utf-8")
PY

stage="dl3dv-extraction-and-colmap-normalization"
announce
python3 "${PROJECT}/competition/reconstruction/prepare_dl3dv_scene.py" \
  --archive "${INPUT}/scene.zip" \
  --output "${PREPARED}" \
  --report "${RESULTS}/dataset-preparation.json" \
  >"${RESULTS}/dataset-preparation.log" 2>&1
dataset_dir="${PREPARED}/dataset"

PYTHONPATH="${GSPLAT_DIR}/examples" python3 - "${dataset_dir}" <<'PY' \
  >"${RESULTS}/dataset-parser-validation.json"
import json
import sys
from datasets.colmap import Dataset, Parser

parser = Parser(sys.argv[1], factor=1, normalize=True, test_every=8)
train = Dataset(parser, split="train")
held_out = Dataset(parser, split="val")
if len(parser.image_names) < 50 or len(parser.points) < 10000:
    raise SystemExit(
        f"insufficient data: images={len(parser.image_names)} points={len(parser.points)}"
    )
sample = train[0]
if sample["image"].ndim != 3 or sample["camtoworld"].shape != (4, 4):
    raise SystemExit("invalid parsed sample")
print(json.dumps({
    "status": "passed",
    "images": len(parser.image_names),
    "points": len(parser.points),
    "train": len(train),
    "held_out": len(held_out),
    "sample_shape": list(sample["image"].shape),
}))
PY

train_candidate() {
  local strategy="$1"
  local steps="$2"
  local output="$3"
  local log="$4"
  cd "${GSPLAT_DIR}"
  python3 examples/simple_trainer.py "${strategy}" \
    --data-dir "${dataset_dir}" \
    --data-factor 1 \
    --result-dir "${output}" \
    --test-every 8 \
    --max-steps "${steps}" \
    --eval-steps "${steps}" \
    --save-steps "${steps}" \
    --sh-degree 3 \
    --antialiased \
    --lpips-net vgg \
    --disable-viewer \
    >"${log}" 2>&1
}

if [[ -s "${INPUT}/pretrained-gaussians.ply" ]] \
  && [[ -s "${INPUT}/pretrained-camera-path.json" ]] \
  && [[ -s "${INPUT}/pretrained-candidate-selection.json" ]]; then
  stage="verified-pretrained-gaussian-import"
  announce
  cp "${INPUT}/pretrained-gaussians.ply" "${FULL_ASSETS}/gaussians.ply"
  cp "${INPUT}/pretrained-camera-path.json" "${FULL_ASSETS}/camera-path.json"
  cp "${INPUT}/pretrained-candidate-selection.json" \
    "${RESULTS}/candidate-selection.json"
  python3 - "${RESULTS}/candidate-selection.json" \
    "${RESULTS}/candidate-selection.env" <<'PY'
import json
import pathlib
import sys

report = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
selected = report["selected"]
pathlib.Path(sys.argv[2]).write_text(
    f"SELECTED_STRATEGY={selected['strategy']}\n"
    f"SELECTED_STEPS={selected['steps']}\n"
    "SELECTED_DIR=verified-pretrained-standard-ply\n"
    "SELECTED_METRICS=verified-pretrained-candidate-selection\n"
    f"QUALITY_PASSED={'true' if selected['thresholds_passed'] else 'false'}\n",
    encoding="utf-8",
)
PY
  source "${RESULTS}/candidate-selection.env"
  PYTHONPATH="${GSPLAT_DIR}/examples" python3 \
    "${PROJECT}/competition/reconstruction/render_reference_from_ply.py" \
    --dataset "${dataset_dir}" \
    --gsplat "${GSPLAT_DIR}" \
    --ply "${FULL_ASSETS}/gaussians.ply" \
    --output "${FULL_ASSETS}" \
    >"${RESULTS}/gaussian-export.log" 2>&1
else
  stage="gsplat-standard-30000"
  announce
  train_candidate default 30000 "${TRAIN_ROOT}/default-30000" \
    "${RESULTS}/gsplat-default-30000.log"

  stage="gsplat-mcmc-30000"
  announce
  train_candidate mcmc 30000 "${TRAIN_ROOT}/mcmc-30000" \
    "${RESULTS}/gsplat-mcmc-30000.log"

stage="quality-selection"
announce
python3 - "${TRAIN_ROOT}" "${RESULTS}/candidate-selection.json" \
  "${RESULTS}/candidate-selection.env" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
report_path = pathlib.Path(sys.argv[2])
env_path = pathlib.Path(sys.argv[3])
thresholds = {"psnr": 30.0, "ssim": 0.92, "lpips": 0.15}
candidates = []
for strategy in ("default", "mcmc"):
    directory = root / f"{strategy}-30000"
    metrics_path = sorted((directory / "stats").glob("val_step*.json"))[-1]
    metrics = json.loads(metrics_path.read_text())
    passed = (
        metrics["psnr"] >= thresholds["psnr"]
        and metrics["ssim"] >= thresholds["ssim"]
        and metrics["lpips"] <= thresholds["lpips"]
    )
    candidates.append({
        "strategy": strategy,
        "steps": 30000,
        "directory": str(directory),
        "metrics_path": str(metrics_path),
        "metrics": metrics,
        "thresholds_passed": passed,
    })
passing = [item for item in candidates if item["thresholds_passed"]]
selected = min(passing or candidates, key=lambda item: item["metrics"]["lpips"])
report = {
    "schema_version": 1,
    "thresholds": thresholds,
    "candidates": candidates,
    "selected": selected,
    "requires_60000_retrain": not bool(passing),
}
report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
env_path.write_text(
    f"SELECTED_STRATEGY={selected['strategy']}\n"
    f"SELECTED_STEPS={selected['steps']}\n"
    f"SELECTED_DIR={selected['directory']}\n"
    f"SELECTED_METRICS={selected['metrics_path']}\n"
    f"QUALITY_PASSED={'true' if selected['thresholds_passed'] else 'false'}\n",
    encoding="utf-8",
)
PY
source "${RESULTS}/candidate-selection.env"

if [[ "${QUALITY_PASSED}" != "true" ]]; then
  stage="gsplat-selected-60000"
  announce
  train_candidate \
    "${SELECTED_STRATEGY}" 60000 \
    "${TRAIN_ROOT}/${SELECTED_STRATEGY}-60000" \
    "${RESULTS}/gsplat-${SELECTED_STRATEGY}-60000.log"
  python3 - "${RESULTS}/candidate-selection.json" \
    "${RESULTS}/candidate-selection.env" \
    "${TRAIN_ROOT}/${SELECTED_STRATEGY}-60000" <<'PY'
import json
import pathlib
import sys

report_path = pathlib.Path(sys.argv[1])
env_path = pathlib.Path(sys.argv[2])
directory = pathlib.Path(sys.argv[3])
report = json.loads(report_path.read_text())
metrics_path = sorted((directory / "stats").glob("val_step*.json"))[-1]
metrics = json.loads(metrics_path.read_text())
t = report["thresholds"]
passed = (
    metrics["psnr"] >= t["psnr"]
    and metrics["ssim"] >= t["ssim"]
    and metrics["lpips"] <= t["lpips"]
)
selected = {
    "strategy": report["selected"]["strategy"],
    "steps": 60000,
    "directory": str(directory),
    "metrics_path": str(metrics_path),
    "metrics": metrics,
    "thresholds_passed": passed,
}
report["candidates"].append(selected)
report["selected"] = selected
report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
env_path.write_text(
    f"SELECTED_STRATEGY={selected['strategy']}\n"
    f"SELECTED_STEPS={selected['steps']}\n"
    f"SELECTED_DIR={selected['directory']}\n"
    f"SELECTED_METRICS={selected['metrics_path']}\n"
    f"QUALITY_PASSED={'true' if passed else 'false'}\n",
    encoding="utf-8",
)
PY
  source "${RESULTS}/candidate-selection.env"
fi

checkpoint="$(
  find "${SELECTED_DIR}/ckpts" -type f -name 'ckpt_*_rank0.pt' | sort | tail -n 1
)"
test -s "${checkpoint}"

stage="standard-ply-and-camera-export"
announce
PYTHONPATH="${GSPLAT_DIR}/examples" python3 \
  "${PROJECT}/competition/reconstruction/export_discoverse_background.py" \
  --dataset "${dataset_dir}" \
  --gsplat "${GSPLAT_DIR}" \
  --checkpoint "${checkpoint}" \
  --metrics "${SELECTED_METRICS}" \
  --output "${FULL_ASSETS}" \
  --candidate "${SELECTED_STRATEGY}" \
  --steps "${SELECTED_STEPS}" \
  --data-factor 1 \
  --test-every 8 \
  --trajectory-frames 540 \
  >"${RESULTS}/gaussian-export.log" 2>&1
fi

stage="source-clean-shell-layering"
announce
source_screening_args=()
if [[ "${EXPECTED_SCENE_PROFILE}" = "screened-kitchen" ]]; then
  source_screening_args=(
    --source-screening-report
    "${INPUT}/source-center-screening.json"
  )
fi
python3 "${PROJECT}/competition/reconstruction/measure_bigym_workspace.py" \
  --task DishwasherLoadPlates \
  --output "${RESULTS}/workspace-obb.json" \
  >"${RESULTS}/workspace-obb.log" 2>&1
python3 "${PROJECT}/competition/reconstruction/export_scene_shell.py" \
  --input "${FULL_ASSETS}/gaussians.ply" \
  --camera-path "${FULL_ASSETS}/camera-path.json" \
  --output "${SHELL_ASSETS}" \
  --source-report "${INPUT}/source.json" \
  "${source_screening_args[@]}" \
  --workspace-obb "${RESULTS}/workspace-obb.json" \
  --workspace-margin 0.30 \
  --camera-height 1.55 \
  --wall-band 0.65 \
  --center-width 3.0 \
  --center-depth 3.0 \
  --clear-height 2.4 \
  >"${RESULTS}/scene-shell-export.log" 2>&1
cp "${FULL_ASSETS}/camera-path.json" "${SHELL_ASSETS}/camera-path.json"
cp "${FULL_ASSETS}/reference_source.png" "${SHELL_ASSETS}/reference_source.png"
cp "${FULL_ASSETS}/reference_gsplat.png" "${SHELL_ASSETS}/reference_gsplat.png"
if [[ -s "${INPUT}/source-center-screening.json" ]]; then
  cp "${INPUT}/source-center-screening.json" \
    "${SHELL_ASSETS}/source-center-screening.json"
fi
ln -s "gaussians_shell.ply" "${SHELL_ASSETS}/gaussians.ply"

integration_status="skipped_quality_gate"
if [[ "${QUALITY_PASSED}" == "true" ]]; then
  stage="offline-mujoco-native-3dgs-video"
  announce
  python3 "${PROJECT}/competition/reconstruction/render_discoverse_mujoco.py" \
    --assets "${SHELL_ASSETS}" \
    --output "${DEMO}" \
    --width 1920 \
    --height 1080 \
    --fps 30 \
    --seconds 18 \
    --scene-slug dl3dv_commercial_kitchen_shell \
    >"${RESULTS}/offline-render.log" 2>&1
  python3 "${PROJECT}/competition/reconstruction/make_scene_shell_media.py" \
    --video "${DEMO}/dl3dv_commercial_kitchen_shell_mujoco_3dgs.mp4" \
    --output "${DEMO}" \
    --prefix dl3dv_commercial_kitchen_shell \
    >"${RESULTS}/scene-shell-media.log" 2>&1
  stage="bigym-three-camera-300-frame-acceptance"
  announce
  python3 \
    "${PROJECT}/competition/reconstruction/validate_bigym_visual_shell.py" \
    --profile "${SHELL_ASSETS}/scene-shell-profile.json" \
    --output "${BIGYM_DEMO}" \
    --task DishwasherLoadPlates \
    --frames 360 \
    --seed 20260727 \
    >"${RESULTS}/bigym-visual-shell.log" 2>&1
  integration_status="passed"
fi

stage="machine-report-and-package"
announce
python3 - "${INPUT}/source.json" "${RESULTS}" "${SHELL_ASSETS}" "${DEMO}" "${BIGYM_DEMO}" \
  "${GSPLAT_REVISION}" "${DISCOVERSE_REVISION}" "${RENDERER_VERSION}" \
  "${QUALITY_PASSED}" "${integration_status}" "${EXPECTED_SCENE_PROFILE}" <<'PY'
import datetime
import hashlib
import json
import pathlib
import sys

source_path = pathlib.Path(sys.argv[1])
result_dir = pathlib.Path(sys.argv[2])
assets = pathlib.Path(sys.argv[3])
demo = pathlib.Path(sys.argv[4])
bigym_demo = pathlib.Path(sys.argv[5])
source = json.loads(source_path.read_text())
selection = json.loads((result_dir / "candidate-selection.json").read_text())
profile = json.loads((assets / "scene-shell-profile.json").read_text())
quality_passed = sys.argv[9] == "true"
integration_status = sys.argv[10]
expected_profile = sys.argv[11]
full_scene_mode = expected_profile == "full-kitchen"
full_assets = assets.parent / "full-assets"
offline = None
offline_path = demo / "mujoco-discoverse-report.json"
if offline_path.is_file():
    offline = json.loads(offline_path.read_text())
bigym = None
bigym_path = bigym_demo / "bigym-visual-shell-report.json"
if bigym_path.is_file():
    bigym = json.loads(bigym_path.read_text())

def artifact(path, root):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": str(path.relative_to(root)),
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }

files = [
    path
    for root in (full_assets, assets, demo, bigym_demo)
    for path in root.rglob("*")
    if path.is_file() and not path.is_symlink()
]
full_scene_pass = bool(
    full_scene_mode
    and quality_passed
    and (full_assets / "gaussians.ply").is_file()
    and (full_assets / "camera-path.json").is_file()
    and (full_assets / "reference_source.png").is_file()
    and (full_assets / "reference_gsplat.png").is_file()
)
shell_integration_pass = bool(
    quality_passed
    and integration_status == "passed"
    and offline
    and offline["status"] == "passed"
    and bigym
    and (
        bigym.get("technical_status") == "passed"
        or bigym.get("status") == "passed"
    )
    and bigym["frames"] >= 300
    and bigym.get("continuous_simulation_without_reset") is True
    and bigym.get("resets_during_acceptance") == 0
    and bigym.get("physics_parity", {}).get("termination_flags_equal") is True
    and not (
        (bigym.get("task_termination", {}).get("native") or {})
        .get("robot_distance_failure", False)
    )
    and profile.get("source_center_gate", {}).get("status") == "passed"
    and profile["central_exclusion"]["visible_gaussian_violations"] == 0
    and profile["central_exclusion"]["floor_preserved"] is True
    and profile["background_physics"]["mujoco_geom_count"] == 0
)
technical_pass = full_scene_pass if full_scene_mode else shell_integration_pass
report = {
    "schema_version": 1,
    "status": "awaiting_visual_approval"
    if technical_pass
    else "visual_fail",
    "technical_status": "passed" if technical_pass else "failed",
    "approval_status": "pending" if technical_pass else "not_eligible",
    "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "source": source,
    "versions": {
        "gsplat": {"version": "1.4.0", "revision": sys.argv[6]},
        "discoverse": {"revision": sys.argv[7]},
        "gaussian_renderer": {"version": sys.argv[8]},
    },
    "training": selection,
    "full_reconstruction": {
        "requested": full_scene_mode,
        "status": "passed" if full_scene_pass else (
            "not_requested" if not full_scene_mode else "failed"
        ),
        "gaussians": (
            artifact(full_assets / "gaussians.ply", assets.parent)
            if (full_assets / "gaussians.ply").is_file()
            else None
        ),
        "camera_path": (
            artifact(full_assets / "camera-path.json", assets.parent)
            if (full_assets / "camera-path.json").is_file()
            else None
        ),
        "reference_source": (
            artifact(full_assets / "reference_source.png", assets.parent)
            if (full_assets / "reference_source.png").is_file()
            else None
        ),
        "reference_gsplat": (
            artifact(full_assets / "reference_gsplat.png", assets.parent)
            if (full_assets / "reference_gsplat.png").is_file()
            else None
        ),
    },
    "shell": profile,
    "shell_integration_status": (
        "passed" if shell_integration_pass else "diagnostic_only"
    ),
    "offline_mujoco": offline,
    "bigym_three_camera": bigym,
    "viewer": {
        "backend": "FastAPI + MuJoCo + GSRendererMuJoCo",
        "port": 18091,
        "status": "ready_after_server_start" if technical_pass else "not_started",
    },
    "credentials_received_by_cluster": False,
    "artifacts": [
        artifact(path, assets.parent)
        for path in files
    ],
}
(result_dir / "scene-shell-report.json").write_text(
    json.dumps(report, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
PY

if [[ "${SCENE_SHELL_VISUAL_STATUS:-pending}" != "pending" ]]; then
  python3 - "${RESULTS}/scene-shell-report.json" \
    "${SHELL_ASSETS}/scene-shell-profile.json" \
    "${SCENE_SHELL_VISUAL_STATUS}" <<'PY'
import datetime
import json
import pathlib
import sys

report_path = pathlib.Path(sys.argv[1])
profile_path = pathlib.Path(sys.argv[2])
status = sys.argv[3]
reviewed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
report = json.loads(report_path.read_text(encoding="utf-8"))
profile = json.loads(profile_path.read_text(encoding="utf-8"))
technical_status = report.get("technical_status") or report.get("status")
report["technical_status"] = technical_status
report["status"] = "complete" if status == "passed" else "partial"
report["human_visual_review"] = status
report.setdefault("acceptance", {})["human_visual_review"] = status == "passed"
if isinstance(report.get("shell"), dict):
    report["shell"]["status"] = status
profile["status"] = status
profile["human_visual_review"] = {
    "required": True,
    "status": status,
    "reviewed_at": reviewed_at,
    "source": "SCENE_SHELL_VISUAL_STATUS",
}
report_path.write_text(
    json.dumps(report, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
profile_path.write_text(
    json.dumps(profile, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
PY
fi

package_results
archive_sha="$(sha256sum "${ARCHIVE}" | awk '{print $1}')"
archive_bytes="$(stat -c '%s' "${ARCHIVE}")"
report_status="$(
  python3 -c 'import json; print(json.load(open("/scratch/results/scene-shell-report.json"))["status"])'
)"
printf 'AMD_COMPETITION_SCENE_SHELL_ARCHIVE={"status":"%s","archive":"%s","bytes":%s,"sha256":"%s"}\n' \
  "${report_status}" "${ARCHIVE}" "${archive_bytes}" "${archive_sha}"

if [[ "${QUALITY_PASSED}" != "true" ]]; then
  printf 'AMD_COMPETITION_SCENE_SHELL_READY={"status":"visual_fail","viewer_started":false}\n'
  wait_for_release
  exit 2
fi

stage="live-viewer"
announce
OMP_NUM_THREADS=1 \
OPENBLAS_NUM_THREADS=1 \
MKL_NUM_THREADS=1 \
NUMEXPR_NUM_THREADS=1 \
SCENE_SHELL_ASSETS="${SHELL_ASSETS}" \
SCENE_SHELL_FRONTEND="${FRONTEND}" \
python3 -m uvicorn competition.viewer.backend.app:app \
  --host 0.0.0.0 \
  --port 18091 \
  --ws wsproto \
  --workers 1 \
  >"${RESULTS}/viewer.log" 2>&1 &
viewer_pid=$!

viewer_ready=false
for _ in $(seq 1 180); do
  if curl --fail --silent http://127.0.0.1:18091/api/health \
    >"${RESULTS}/viewer-health.json"; then
    viewer_ready=true
    break
  fi
  if ! kill -0 "${viewer_pid}" 2>/dev/null; then
    break
  fi
  sleep 1
done
if [[ "${viewer_ready}" != "true" ]]; then
  echo "viewer failed to become ready" >&2
  exit 20
fi
printf 'AMD_COMPETITION_SCENE_SHELL_READY={"status":"ready","viewer_started":true,"port":18091,"archive_bytes":%s,"archive_sha256":"%s"}\n' \
  "${archive_bytes}" "${archive_sha}"

started_at="${SECONDS}"
ever_connected=false
idle_since="${SECONDS}"
while kill -0 "${viewer_pid}" 2>/dev/null; do
  if [[ -e "${SCRATCH}/release" ]]; then
    break
  fi
  health="$(
    curl --fail --silent http://127.0.0.1:18091/api/health 2>/dev/null || true
  )"
  clients="$(
    python3 -c 'import json,sys; print(json.load(sys.stdin).get("clients", 0))' \
      <<<"${health}" 2>/dev/null || echo 0
  )"
  if (( clients > 0 )); then
    ever_connected=true
    idle_since="${SECONDS}"
  elif [[ "${ever_connected}" == "true" ]] && (( SECONDS - idle_since >= 1800 )); then
    echo "viewer exiting after 30 minutes without a client"
    break
  fi
  if (( SECONDS - started_at >= 14400 )); then
    echo "viewer reached four-hour maximum runtime"
    break
  fi
  sleep 15
done
kill "${viewer_pid}" 2>/dev/null || true
wait "${viewer_pid}" 2>/dev/null || true
