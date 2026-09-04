#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

packages=(openssh-server iproute2 jq rsync tmux)
missing_packages=()

for package in "${packages[@]}"; do
  if ! dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q "ok installed"; then
    missing_packages+=("$package")
  fi
done

if ((${#missing_packages[@]})); then
  apt-get update -qq
  apt-get install -y -qq "${missing_packages[@]}"
fi

install -d -m 755 /run/sshd
install -d -m 700 /root/.ssh

if [[ ! -s /root/.ssh/authorized_keys ]]; then
  echo "No injected SSH public key found at /root/.ssh/authorized_keys." >&2
  exit 1
fi

install -d -m 755 /etc/ssh/sshd_config.d
install -m 600 /dev/stdin /etc/ssh/sshd_config.d/99-policyseal.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
EOF

install -m 644 /dev/stdin /etc/profile.d/policyseal.sh <<'EOF'
export PATH="/opt/venv/bin:${PATH}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export HF_HOME="${HF_HOME:-/workspace/.cache/huggingface}"
export HUGGINGFACE_HUB_CACHE="${HUGGINGFACE_HUB_CACHE:-${HF_HOME}/hub}"
export MODELSCOPE_CACHE="${MODELSCOPE_CACHE:-/workspace/.cache/modelscope}"
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-/workspace/.cache/pip}"
export FASTEMBED_CACHE_PATH="${FASTEMBED_CACHE_PATH:-/workspace/.cache/fastembed}"
export PNPM_HOME="${PNPM_HOME:-/workspace/.cache/pnpm/bin}"
export PNPM_STORE_DIR="${PNPM_STORE_DIR:-/workspace/.cache/pnpm/store}"
export COREPACK_HOME="${COREPACK_HOME:-/workspace/.cache/corepack}"
export POLICYSEAL_NODE_HOME="${POLICYSEAL_NODE_HOME:-/workspace/.cache/tools/node-v22.23.2-linux-x64}"
export POLICYSEAL_UV_HOME="${POLICYSEAL_UV_HOME:-/workspace/.cache/tools/uv-0.11.32}"
export PATH="${POLICYSEAL_NODE_HOME}/bin:${POLICYSEAL_UV_HOME}/bin:${PNPM_HOME}:${PATH}"
EOF

install -d -m 755 \
  /workspace/.cache/huggingface \
  /workspace/.cache/modelscope \
  /workspace/.cache/pip \
  /workspace/.cache/fastembed \
  /workspace/.cache/corepack \
  /workspace/.cache/pnpm/bin \
  /workspace/.cache/pnpm/store \
  /workspace/.cache/tools \
  /workspace/models

/usr/sbin/sshd -t

if listener_pid="$(pgrep -o -x sshd)"; then
  kill -HUP "$listener_pid"
else
  /usr/sbin/sshd
fi

echo "PolicySeal SSH bootstrap complete."
