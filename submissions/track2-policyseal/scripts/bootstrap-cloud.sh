#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

if [[ ! -x /opt/venv/bin/python ]]; then
  echo "Expected Radeon runtime at /opt/venv/bin/python." >&2
  exit 1
fi

export UV_CACHE_DIR="${UV_CACHE_DIR:-/workspace/.cache/uv}"
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-.venv}"
export PNPM_HOME="${PNPM_HOME:-/workspace/.cache/pnpm/bin}"
export PNPM_STORE_DIR="${PNPM_STORE_DIR:-/workspace/.cache/pnpm/store}"
export FASTEMBED_CACHE_PATH="${FASTEMBED_CACHE_PATH:-/workspace/.cache/fastembed}"
export COREPACK_HOME="${COREPACK_HOME:-/workspace/.cache/corepack}"
export UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-600}"

pypi_index="${POLICYSEAL_PYPI_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
npm_registry="${POLICYSEAL_NPM_REGISTRY:-https://registry.npmmirror.com}"

node_version="22.23.2"
node_archive="node-v${node_version}-linux-x64.tar.xz"
node_sha256="d60acfe00a2932254bb0ad20e01b0d74397a0875595de719654b214f4b03f307"
node_home="${POLICYSEAL_NODE_HOME:-/workspace/.cache/tools/node-v${node_version}-linux-x64}"
node_download="/workspace/.cache/downloads/${node_archive}"
uv_home="${POLICYSEAL_UV_HOME:-/workspace/.cache/tools/uv-0.11.32}"

mkdir -p \
  "$(dirname -- "$node_download")" \
  "$(dirname -- "$node_home")" \
  "$PNPM_HOME" \
  "$PNPM_STORE_DIR" \
  "$FASTEMBED_CACHE_PATH" \
  "$COREPACK_HOME" \
  /workspace/.cache/huggingface \
  /workspace/.cache/modelscope \
  /workspace/.cache/pip \
  var/radeon
if [[ ! -x "$node_home/bin/node" ]]; then
  curl --fail --location --retry 3 \
    "https://nodejs.org/dist/v${node_version}/${node_archive}" \
    --output "$node_download"
  printf '%s  %s\n' "$node_sha256" "$node_download" | sha256sum --check --status
  tar --extract --xz --file "$node_download" --directory "$(dirname -- "$node_home")"
fi

if [[ ! -x "$uv_home/bin/uv" ]]; then
  python3 -m venv "$uv_home"
  "$uv_home/bin/python" -m pip install \
    --disable-pip-version-check \
    --index-url "$pypi_index" \
    "uv==0.11.32"
fi

export PATH="${node_home}/bin:${uv_home}/bin:${PNPM_HOME}:${PATH}"

if [[ ! -x .venv/bin/python ]]; then
  uv venv --python /opt/venv/bin/python .venv
fi

lock_sha256="$(sha256sum uv.lock | cut -d' ' -f1)"
locked_requirements="${UV_CACHE_DIR}/policyseal-${lock_sha256}-dev-requirements.txt"
uv export \
  --quiet \
  --frozen \
  --extra dev \
  --no-emit-project \
  --format requirements-txt \
  --output-file "$locked_requirements"
uv pip install \
  --python .venv/bin/python \
  --index-url "$pypi_index" \
  --requirement "$locked_requirements"
uv sync --offline --extra dev --frozen --python /opt/venv/bin/python
corepack enable --install-directory "$node_home/bin"
corepack prepare pnpm@11.9.0 --activate
pnpm config set registry "$npm_registry"
pnpm config set store-dir "$PNPM_STORE_DIR"
pnpm install --frozen-lockfile

.venv/bin/python -c "import policyseal"
/opt/venv/bin/python -c "import torch; assert torch.cuda.is_available()"
node -e 'if (process.versions.node !== "22.23.2") process.exit(1)'
pnpm --version | grep -Eq '^11\.'
uv --version | grep -Eq '^uv 0\.11\.32( |$)'

echo "PolicySeal cloud development environment is ready."
