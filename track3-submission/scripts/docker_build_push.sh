#!/usr/bin/env bash
# Track 3 submission image — build + push (run on an AMD ROCm Linux host, amd64).
#
# Usage:
#   ./scripts/docker_build_push.sh ghcr.io/<your-github-account>/track3-soccer:amd
#   ./scripts/docker_build_push.sh <your-dockerhub-account>/track3-soccer:amd
#
# Prereqs:
#   - AMD ROCm Linux host (amd64) with Docker + BuildKit
#   - `docker login` already done for your target registry
#   - ~40 GB free disk (base ROCm image unpacks to ~38 GB)
set -euo pipefail

REGISTRY_TAG="${1:?usage: $0 <registry>/track3-soccer:amd}"
LOCAL_TAG="track3-soccer:amd"

echo "==> [1/3] docker build (local tag: ${LOCAL_TAG})"
docker build -t "${LOCAL_TAG}" -f amd-physical-ai-soccer/Dockerfile amd-physical-ai-soccer

echo "==> [2/3] sanity: image inspect"
docker image inspect "${LOCAL_TAG}" >/dev/null

echo "==> [3/3] tag + push -> ${REGISTRY_TAG}"
docker tag "${LOCAL_TAG}" "${REGISTRY_TAG}"
docker push "${REGISTRY_TAG}"

echo "DONE. Published image: ${REGISTRY_TAG}"
echo "Fill this URL into PR_DESCRIPTION.md (Docker TODO section)."
