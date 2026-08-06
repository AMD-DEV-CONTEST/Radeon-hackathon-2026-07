#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT="${1:-${PROJECT_ROOT}/submission/AI-Photographer-Agent-track2-release.tar.gz}"
STAGING_ROOT="$(mktemp -d)"
PACKAGE_ROOT="${STAGING_ROOT}/AI-Photographer-Agent"
trap 'rm -rf "${STAGING_ROOT}"' EXIT

mkdir -p \
  "${PACKAGE_ROOT}/assets" \
  "${PACKAGE_ROOT}/demo" \
  "${PACKAGE_ROOT}/docs" \
  "${PACKAGE_ROOT}/models" \
  "${PACKAGE_ROOT}/scripts" \
  "${PACKAGE_ROOT}/src/agent" \
  "${PACKAGE_ROOT}/src/tools" \
  "${PACKAGE_ROOT}/src/vision" \
  "${PACKAGE_ROOT}/submission/evidence" \
  "${PACKAGE_ROOT}/submission/final" \
  "${PACKAGE_ROOT}/tests" \
  "${PACKAGE_ROOT}/web"

cp \
  "${PROJECT_ROOT}/.gitignore" \
  "${PROJECT_ROOT}/README.md" \
  "${PROJECT_ROOT}/requirements.txt" \
  "${PACKAGE_ROOT}/"
cp -R "${PROJECT_ROOT}/assets/fonts" "${PACKAGE_ROOT}/assets/"
cp "${PROJECT_ROOT}/models/.gitkeep" "${PACKAGE_ROOT}/models/"
cp "${PROJECT_ROOT}/demo/.gitkeep" "${PACKAGE_ROOT}/demo/"

for document in \
  architecture.md \
  demo_script.md \
  environment_report.md \
  photography_plan.schema.json \
  submission.md \
  test_report.md \
  track2_compliance.md
do
  cp "${PROJECT_ROOT}/docs/${document}" "${PACKAGE_ROOT}/docs/"
done

for script in \
  benchmark_agent.py \
  check_environment.py \
  download_person_segmenter.py \
  finalize_release_cards.py \
  package_submission.sh \
  release_candidate_evidence.py \
  run_web.sh
do
  cp "${PROJECT_ROOT}/scripts/${script}" "${PACKAGE_ROOT}/scripts/"
done

cp \
  "${PROJECT_ROOT}/src/__init__.py" \
  "${PROJECT_ROOT}/src/main.py" \
  "${PROJECT_ROOT}/src/web.py" \
  "${PACKAGE_ROOT}/src/"
find "${PROJECT_ROOT}/src/agent" -maxdepth 1 -type f -name "*.py" \
  -exec cp {} "${PACKAGE_ROOT}/src/agent/" \;
find "${PROJECT_ROOT}/src/tools" -maxdepth 1 -type f -name "*.py" \
  -exec cp {} "${PACKAGE_ROOT}/src/tools/" \;
find "${PROJECT_ROOT}/src/vision" -maxdepth 1 -type f -name "*.py" \
  -exec cp {} "${PACKAGE_ROOT}/src/vision/" \;

cp "${PROJECT_ROOT}/tests/__init__.py" "${PACKAGE_ROOT}/tests/"
for test_file in \
  test_benchmark_utils.py \
  test_core.py \
  test_field_plan.py \
  test_http.py \
  test_image_orientation.py \
  test_person_segmenter.py \
  test_pose_card.py \
  test_process_lock.py \
  test_tool_permissions.py \
  test_vlm_utils.py \
  test_web.py
do
  cp "${PROJECT_ROOT}/tests/${test_file}" "${PACKAGE_ROOT}/tests/"
done

cp "${PROJECT_ROOT}/web/demo.html" "${PACKAGE_ROOT}/web/"
cp \
  "${PROJECT_ROOT}/submission/evidence/DEMO_CASES.md" \
  "${PROJECT_ROOT}/submission/evidence/SAMPLE_SOURCES.md" \
  "${PROJECT_ROOT}/submission/evidence/RELEASE_CANDIDATE_REPORT.md" \
  "${PACKAGE_ROOT}/submission/evidence/"
cp -R \
  "${PROJECT_ROOT}/submission/evidence/samples" \
  "${PACKAGE_ROOT}/submission/evidence/"
cp -R "${PROJECT_ROOT}/submission/final/." "${PACKAGE_ROOT}/submission/final/"

find "${PACKAGE_ROOT}" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "${PACKAGE_ROOT}" -type f \( \
  -name "*.pyc" -o \
  -name ".DS_Store" -o \
  -name "*.pre_*" -o \
  -name "*.bak" \
\) -delete

if find "${PACKAGE_ROOT}" -type f \( \
  -name "*.safetensors" -o \
  -name "*.pt" -o \
  -name "*.pth" -o \
  -name "*.ckpt" -o \
  -name "*.onnx" \
\) | grep -q .; then
  echo "Refusing to package model weights." >&2
  exit 1
fi
if find "${PACKAGE_ROOT}" -type f | grep -E "IMG_8091|src/generation|pre_fix" >/dev/null; then
  echo "Refusing to package private or obsolete experiment files." >&2
  exit 1
fi

(
  cd "${PACKAGE_ROOT}"
  find . -type f ! -name MANIFEST.sha256 -print0 \
    | sort -z \
    | xargs -0 sha256sum > MANIFEST.sha256
)

mkdir -p "$(dirname "${OUTPUT}")"
COPYFILE_DISABLE=1 tar --no-xattrs -C "${STAGING_ROOT}" -czf "${OUTPUT}" \
  "AI-Photographer-Agent"
printf '%s\n' "Submission package: ${OUTPUT}"
