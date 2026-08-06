#!/bin/bash
# Build the pre-baked workshop Docker image.
#
# Usage:
#   bash docker/build.sh                          # default: ROCm 7.2 base
#   bash docker/build.sh my-registry/workshop:v1   # custom tag
#   BASE_IMAGE=rocm/pytorch:rocm6.4.3_ubuntu24.04_py3.12_pytorch_release_2.6.0 \
#     bash docker/build.sh workshop-mi300:latest   # ROCm 6.4.3 base for MI300
set -e

IMAGE_TAG="${1:-workshop-genesis:latest}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE="${BASE_IMAGE:-rocm/pytorch:rocm7.2_ubuntu24.04_py3.12_pytorch_release_2.9.1}"

echo "[build] Base image : ${BASE}"
echo "[build] Output tag : ${IMAGE_TAG}"
echo "[build] Context    : ${REPO_ROOT}"

docker build \
    --build-arg BASE_IMAGE="${BASE}" \
    -f "${REPO_ROOT}/docker/Dockerfile.workshop" \
    -t "${IMAGE_TAG}" \
    "${REPO_ROOT}"

echo ""
echo "[build] Done. Image: ${IMAGE_TAG}"
echo ""
echo "Run with:"
echo "  docker run --rm -it \\"
echo "    --device=/dev/kfd --device=/dev/dri --group-add video --ipc=host \\"
echo "    --network=host \\"
echo "    -v \$(pwd):/workspace/workshop \\"
echo "    -v /tmp/workshop_output:/output \\"
echo "    -w /workspace/workshop \\"
echo "    ${IMAGE_TAG} bash"
