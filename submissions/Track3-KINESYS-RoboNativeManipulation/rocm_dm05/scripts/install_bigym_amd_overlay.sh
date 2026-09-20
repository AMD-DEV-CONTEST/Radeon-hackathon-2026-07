#!/usr/bin/env bash
set -euo pipefail

: "${BIGYM_3DGS_ROOT:?Set BIGYM_3DGS_ROOT to the pinned 3DGS repository}"
: "${BIGYM_ROOT:?Set BIGYM_ROOT to the BiGym checkout destination}"
: "${VENV:?Set VENV to the ROCm Python environment}"

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BIGYM_UPSTREAM=${BIGYM_UPSTREAM:-https://github.com/NeuracoreAI/bigym.git}
BIGYM_BASE_COMMIT=14beb30318ad14c5d6723175c2ee2281129792af
UPSTREAM_PATCH="$BIGYM_3DGS_ROOT/patches/bigym-3dgs-shell-and-collector.patch"

if [[ ! -d "$BIGYM_ROOT/.git" ]]; then
  mkdir -p "$(dirname "$BIGYM_ROOT")"
  git clone "$BIGYM_UPSTREAM" "$BIGYM_ROOT"
fi

if [[ "$(git -C "$BIGYM_ROOT" rev-parse HEAD)" != "$BIGYM_BASE_COMMIT" ]]; then
  test -z "$(git -C "$BIGYM_ROOT" status --porcelain)" || {
    echo "Refusing to switch a dirty BiGym checkout: $BIGYM_ROOT" >&2
    exit 2
  }
  git -C "$BIGYM_ROOT" fetch origin "$BIGYM_BASE_COMMIT"
  git -C "$BIGYM_ROOT" checkout --detach "$BIGYM_BASE_COMMIT"
fi

if git -C "$BIGYM_ROOT" apply --check "$UPSTREAM_PATCH" 2>/dev/null; then
  git -C "$BIGYM_ROOT" apply "$UPSTREAM_PATCH"
elif git -C "$BIGYM_ROOT" apply --reverse --check "$UPSTREAM_PATCH" 2>/dev/null; then
  echo "BiGym 3DGS interface patch is already applied"
else
  echo "BiGym checkout does not match the pinned 3DGS interface patch" >&2
  exit 2
fi

# The pinned interface patch imports these modules but does not ship them.
install -m 0644 "$PROJECT_ROOT/overlays/bigym/bigym/utils/visual_shell.py" \
  "$BIGYM_ROOT/bigym/utils/visual_shell.py"
install -m 0644 "$PROJECT_ROOT/overlays/bigym/bigym/utils/visual_shell_assets.py" \
  "$BIGYM_ROOT/bigym/utils/visual_shell_assets.py"
mkdir -p "$BIGYM_ROOT/d/replay_generation"
install -m 0644 "$BIGYM_3DGS_ROOT/scripts/replay_plan.py" \
  "$BIGYM_ROOT/d/replay_generation/replay_plan.py"
install -m 0644 "$BIGYM_3DGS_ROOT/scripts/verify_replay_plan.py" \
  "$BIGYM_ROOT/d/replay_generation/verify_replay_plan.py"

"$VENV/bin/python" -m pip install --no-deps -e "$BIGYM_ROOT"
