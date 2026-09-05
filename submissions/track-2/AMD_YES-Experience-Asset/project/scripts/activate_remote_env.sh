#!/usr/bin/env bash

ROOT="${ROOT:-/workspace/amd-track2-agent}"

export HF_HOME="${HF_HOME:-$ROOT/cache/huggingface}"
export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-$HF_HOME}"
export PATH="$ROOT/tools/gh-current/bin:$ROOT/tools/npm-global/bin:$ROOT/tools/node-current/bin:$HOME/.local/bin:$PATH"

if [[ -d "$ROOT/venvs/agent/bin" ]]; then
  export VIRTUAL_ENV="$ROOT/venvs/agent"
  export PATH="$VIRTUAL_ENV/bin:$PATH"
fi

echo "Remote development environment activated."
echo "ROOT=$ROOT"
command -v python3 >/dev/null 2>&1 && python3 --version
command -v node >/dev/null 2>&1 && node --version
command -v gh >/dev/null 2>&1 && gh --version | sed -n '1p'
command -v codex >/dev/null 2>&1 && codex --version
command -v claude >/dev/null 2>&1 && claude --version
