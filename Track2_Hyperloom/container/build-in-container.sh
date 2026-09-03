#!/bin/bash
# Rocky container workflow: vendor the EXACT verified qat714 env (conda-pack), build the
# workbench image, then BUILD the llama.cpp fork inside it. BENCH stays on host (README).
#
# Reproducible + hostable: the pinned SDK (7.14.0a20260611) is a dated nightly that has
# rotated off TheRock's pip index, so we vendor the installed env itself. Pack once → the
# image builds forever, hermetically, and reproduces the VERIFIED numbers.
#
# Storage discipline: rpool (/home) is ~98% full and hosts the Docker overlay, so ALL
# container storage + the env tarball go on aipool (123G free). podman uses --root on aipool.
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/home/jmonk/rocky-hackathon}"
HOST_ENV_NAME="${HOST_ENV_NAME:-qat714}"
CONDA="${CONDA:-/home/jmonk/miniconda3/bin/conda-pack}"
LLAMA_REPO="${LLAMA_REPO:-/home/jmonk/src/mainline-llama.cpp-mxfp8}"
IMAGE="${IMAGE:-rocky-workbench:rocm7.14a20260611}"
ENGINE="${ENGINE:-podman}"
AIPOOL="${AIPOOL:-/aipool/rocky-build}"
PODMAN_ROOT="${PODMAN_ROOT:-$AIPOOL/podman-root}"
TARBALL="$REPO_ROOT/container/qat714.tar.gz"   # in build context (symlinked to aipool copy)

# podman with storage on aipool (never rpool). docker would need daemon data-root reconfig.
pman() { "$ENGINE" --root "$PODMAN_ROOT" "$@"; }

cmd="${1:-help}"

pack_env() {
  # Vendor the verified host env into the build context. Real tarball lives on aipool;
  # a symlink puts it in-context without copying GBs onto rpool.
  mkdir -p "$AIPOOL"
  echo ">> conda-pack $HOST_ENV_NAME -> $AIPOOL/qat714.tar.gz (ignoring editable pkgs)"
  "$CONDA" -n "$HOST_ENV_NAME" --ignore-editable-packages --force \
    -o "$AIPOOL/qat714.tar.gz" --format tar.gz --n-threads 8
  ln -sf "$AIPOOL/qat714.tar.gz" "$TARBALL"
  ls -lh "$AIPOOL/qat714.tar.gz" | awk '{print $5,$9}'
}

build_image() {
  [ -e "$TARBALL" ] || { echo "!! run '$0 pack' first (no $TARBALL)"; exit 1; }
  echo ">> building $IMAGE ($ENGINE, storage on $PODMAN_ROOT)"
  ( cd "$REPO_ROOT" && pman build --format docker -f container/Containerfile -t "$IMAGE" . )
}

build_llama() {
  # Compile the roc9 fork INSIDE the container. No GPU passthrough (compile-only) → cannot
  # touch GPU0/GPU1, safe alongside a host bench. Output lands on the host repo via bind mount.
  echo ">> building llama.cpp fork in container (compile-only, GPU-safe)"
  pman run --rm -v "$LLAMA_REPO":/work:rw "$IMAGE" '
    source /opt/qat714/bin/activate; source /etc/profile.d/rocm.sh
    cmake -S /work -B /work/build-roc9-container -G Ninja \
      -DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1201 -DCMAKE_BUILD_TYPE=Release
    cmake --build /work/build-roc9-container -j "$(nproc)"
    echo "built -> host:$LLAMA_REPO/build-roc9-container"
  '
}

verify_devices() {
  # Passthrough-bench guard ONLY. Confirms device 0 == compute card (04:00.0).
  pman run --rm --device=/dev/kfd --device=/dev/dri --group-add video \
    --security-opt seccomp=unconfined "$IMAGE" \
    'source /opt/qat714/bin/activate; rocminfo | grep -iE "Marketing|BDF|Node"'
  echo ">> Confirm device 0 BDF == 04:00.0 BEFORE any HIP_VISIBLE_DEVICES=0 bench in-container."
}

publish() {
  : "${REGISTRY:?set REGISTRY=<host>/<ns> to push}"
  pman tag "$IMAGE" "$REGISTRY/$IMAGE"
  pman push "$REGISTRY/$IMAGE"
  echo ">> pushed $REGISTRY/$IMAGE — record the digest for detect()->image pinning."
}

case "$cmd" in
  pack)     pack_env ;;
  image)    build_image ;;
  llama)    build_llama ;;
  verify)   verify_devices ;;
  publish)  publish ;;
  all)      pack_env; build_image; build_llama ;;
  *) cat <<EOF
Rocky container workflow (storage on aipool; rpool is ~98% full):
  $0 pack     # conda-pack the verified qat714 env -> aipool + context symlink (do FIRST)
  $0 image    # build rocky-workbench image (podman --root on aipool)
  $0 llama    # compile the llama.cpp fork inside the container (compile-only, GPU-safe)
  $0 verify   # (passthrough only) confirm rocminfo device 0 == 04:00.0 before bench
  $0 publish  # REGISTRY=<host>/<ns> $0 publish   (tag + push for hosted reuse)
  $0 all      # pack + image + llama

DEFAULT DISCIPLINE: build in container, BENCH on host (ensure_bench_ready + llama-bench),
where GPU0/GPU1 enumeration + perf-level sysfs are known-good. Do not run the image build
while a host bench is measuring t/s (CPU/IO contention perturbs the numbers).
EOF
  ;;
esac
