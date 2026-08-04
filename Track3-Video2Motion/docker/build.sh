#!/usr/bin/env bash
# Build and push. Run this where a real Docker daemon is available —
# a non-privileged container cannot build it (unshare: operation not permitted).
set -euo pipefail

REGISTRY=${REGISTRY:-crpi-38f48gingim9fqua.cn-hongkong.personal.cr.aliyuncs.com/owen_125/amd}
TAG=${TAG:-1.0}
CTX=${CTX:-$(cd "$(dirname "$0")/.." && pwd)}

echo "context : $CTX"
echo "image   : $REGISTRY:$TAG"
echo

DOCKER_BUILDKIT=1 docker build \
  --progress=plain \
  -t "$REGISTRY:$TAG" \
  -f "$CTX/docker/Dockerfile" \
  "$CTX"

echo
echo "built. size:"
docker images "$REGISTRY:$TAG" --format '  {{.Size}}'
echo
echo "push with:"
echo "  docker login --username=<user> ${REGISTRY%%/*}"
echo "  docker push $REGISTRY:$TAG"
