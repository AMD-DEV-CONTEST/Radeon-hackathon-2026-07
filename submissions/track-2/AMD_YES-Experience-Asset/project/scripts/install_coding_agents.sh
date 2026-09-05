#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/workspace/amd-track2-agent}"
TOOLS_DIR="${TOOLS_DIR:-$ROOT/tools}"
NODE_VERSION="${NODE_VERSION:-22.17.1}"
GH_VERSION="${GH_VERSION:-2.96.0}"
NPM_PREFIX="${NPM_PREFIX:-$TOOLS_DIR/npm-global}"

if [[ "$ROOT" != /workspace/* ]]; then
  echo "ERROR: coding-agent tools must be installed under persistent /workspace."
  exit 1
fi

for command in curl tar; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "ERROR: required command is missing: $command"
    exit 1
  fi
done

case "$(uname -m)" in
  x86_64)
    node_arch="x64"
    gh_arch="amd64"
    ;;
  aarch64 | arm64)
    node_arch="arm64"
    gh_arch="arm64"
    ;;
  *)
    echo "ERROR: unsupported CPU architecture: $(uname -m)"
    exit 1
    ;;
esac

mkdir -p "$TOOLS_DIR" "$NPM_PREFIX"

node_dir="$TOOLS_DIR/node-v${NODE_VERSION}-linux-${node_arch}"
archive="node-v${NODE_VERSION}-linux-${node_arch}.tar.xz"
base_url="https://nodejs.org/dist/v${NODE_VERSION}"

if [[ ! -x "$node_dir/bin/node" ]]; then
  temp_dir="$(mktemp -d)"
  trap 'rm -rf "$temp_dir"' EXIT

  echo "Downloading Node.js v${NODE_VERSION} from nodejs.org..."
  curl -fsSLo "$temp_dir/$archive" "$base_url/$archive"
  curl -fsSLo "$temp_dir/SHASUMS256.txt" "$base_url/SHASUMS256.txt"

  expected="$(
    awk -v file="$archive" '$2 == file {print $1}' "$temp_dir/SHASUMS256.txt"
  )"
  if [[ -z "$expected" ]]; then
    echo "ERROR: checksum for $archive was not found."
    exit 1
  fi

  if command -v sha256sum >/dev/null 2>&1; then
    actual="$(sha256sum "$temp_dir/$archive" | awk '{print $1}')"
  else
    actual="$(shasum -a 256 "$temp_dir/$archive" | awk '{print $1}')"
  fi

  if [[ "$actual" != "$expected" ]]; then
    echo "ERROR: Node.js checksum mismatch."
    exit 1
  fi

  tar -xJf "$temp_dir/$archive" -C "$TOOLS_DIR"
fi

ln -sfn "$node_dir" "$TOOLS_DIR/node-current"

gh_dir="$TOOLS_DIR/gh_${GH_VERSION}_linux_${gh_arch}"
gh_archive="gh_${GH_VERSION}_linux_${gh_arch}.tar.gz"
gh_base_url="https://github.com/cli/cli/releases/download/v${GH_VERSION}"

if [[ ! -x "$gh_dir/bin/gh" ]] && ! command -v gh >/dev/null 2>&1; then
  temp_dir="$(mktemp -d)"
  trap 'rm -rf "$temp_dir"' EXIT

  echo "Downloading GitHub CLI v${GH_VERSION} from github.com..."
  if curl -fsSLo "$temp_dir/$gh_archive" "$gh_base_url/$gh_archive" && \
    curl -fsSLo "$temp_dir/gh_checksums.txt" \
      "$gh_base_url/gh_${GH_VERSION}_checksums.txt"; then

    expected="$(
      awk -v file="$gh_archive" '$2 == file {print $1}' \
        "$temp_dir/gh_checksums.txt"
    )"
    if [[ -z "$expected" ]]; then
      echo "ERROR: checksum for $gh_archive was not found."
      exit 1
    fi

    if command -v sha256sum >/dev/null 2>&1; then
      actual="$(sha256sum "$temp_dir/$gh_archive" | awk '{print $1}')"
    else
      actual="$(shasum -a 256 "$temp_dir/$gh_archive" | awk '{print $1}')"
    fi

    if [[ "$actual" != "$expected" ]]; then
      echo "ERROR: GitHub CLI checksum mismatch."
      exit 1
    fi

    tar -xzf "$temp_dir/$gh_archive" -C "$TOOLS_DIR"
  elif [[ "$(id -u)" == "0" ]] && command -v apt-get >/dev/null 2>&1; then
    echo "GitHub Release TLS failed; installing distro-signed gh package."
    DEBIAN_FRONTEND=noninteractive apt-get install -y gh
  else
    echo "ERROR: GitHub CLI download failed and no safe package fallback exists."
    exit 1
  fi
fi

if [[ -x "$gh_dir/bin/gh" ]]; then
  ln -sfn "$gh_dir" "$TOOLS_DIR/gh-current"
fi
export PATH="$TOOLS_DIR/gh-current/bin:$TOOLS_DIR/node-current/bin:$NPM_PREFIX/bin:$HOME/.local/bin:$PATH"

echo "Installing the official Codex CLI into persistent storage..."
npm install --global --prefix "$NPM_PREFIX" @openai/codex

if [[ "${INSTALL_CLAUDE:-1}" == "1" ]]; then
  echo "Installing the official Claude Code native client..."
  installer="$(mktemp)"
  trap 'rm -f "$installer"' EXIT
  curl -fsSL https://claude.ai/install.sh -o "$installer"
  if head -c 256 "$installer" | grep -qiE '<!doctype html|<html'; then
    echo "Claude native installer returned HTML; using the official npm package."
    npm install --global --prefix "$NPM_PREFIX" @anthropic-ai/claude-code
  elif ! bash "$installer"; then
    echo "Claude native installer failed; using the official npm package."
    npm install --global --prefix "$NPM_PREFIX" @anthropic-ai/claude-code
  fi
fi

echo
echo "Installed versions:"
node --version
npm --version
gh --version | sed -n '1p'
codex --version
if command -v claude >/dev/null 2>&1; then
  claude --version
else
  echo "WARN: Claude Code was not found on PATH; check $HOME/.local/bin."
fi

echo
echo "No account login was performed and no credential was written to the repository."
echo "For each new shell: source $ROOT/repo/scripts/activate_remote_env.sh"
echo "Codex headless login: codex login --device-auth"
echo "Claude Code login: claude"
echo "GitHub temporary web login: gh auth login --web --git-protocol https"
