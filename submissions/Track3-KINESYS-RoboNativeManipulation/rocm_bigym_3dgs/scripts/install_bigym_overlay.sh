#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BIGYM_DIR=${BIGYM_DIR:-${AMD_BIGYM_ROOT:-/workspace/amd-bigym-3dgs}/src/bigym}
VENV=${VENV:-${AMD_BIGYM_ROOT:-/workspace/amd-bigym-3dgs}/.venv}
BIGYM_UPSTREAM=${BIGYM_UPSTREAM:-https://github.com/NeuracoreAI/bigym.git}
BIGYM_BASE_COMMIT=14beb30318ad14c5d6723175c2ee2281129792af

if test ! -d "$BIGYM_DIR/.git"; then
  mkdir -p "$(dirname "$BIGYM_DIR")"
  git clone "$BIGYM_UPSTREAM" "$BIGYM_DIR"
fi

test -z "$(git -C "$BIGYM_DIR" status --porcelain)" || {
  printf 'Refusing to patch a dirty BiGym checkout: %s\n' "$BIGYM_DIR" >&2
  exit 2
}

git -C "$BIGYM_DIR" fetch origin "$BIGYM_BASE_COMMIT"
git -C "$BIGYM_DIR" checkout --detach "$BIGYM_BASE_COMMIT"
git -C "$BIGYM_DIR" apply --check "$REPO_ROOT/patches/bigym-3dgs-shell-and-collector.patch"
git -C "$BIGYM_DIR" apply "$REPO_ROOT/patches/bigym-3dgs-shell-and-collector.patch"
install -m 0644 "$REPO_ROOT/scripts/replay_plan.py" "$BIGYM_DIR/d/replay_generation/replay_plan.py"
install -m 0644 "$REPO_ROOT/scripts/verify_replay_plan.py" "$BIGYM_DIR/d/replay_generation/verify_replay_plan.py"

if test ! -x "$VENV/bin/python"; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -e "$BIGYM_DIR"
printf 'BiGym overlay installed at %s\n' "$BIGYM_DIR"
