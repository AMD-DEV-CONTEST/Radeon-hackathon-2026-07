#!/usr/bin/env bash
# Wait for Env-A generation to finish, then move dataset into the project tree.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC_CACHE="${HF_LEROBOT_HOME:-/workspace/cache/huggingface/lerobot}/local/franka-kitchen-fruit-place-120ep"
DEST_DIR="$ROOT/datasets/franka-kitchen-fruit-place-120ep"
LOG="$ROOT/output/gen_env_a_120ep.log"
PID_FILE="$ROOT/output/gen_env_a_120ep.pid"
LINK_CACHE_PARENT="$(dirname "$SRC_CACHE")"

echo "[relocate] waiting for generator / completion marker..."
echo "[relocate] src=$SRC_CACHE"
echo "[relocate] dest=$DEST_DIR"

# Wait until the python generator exits AND log shows success_saved.
while true; do
  if pgrep -f "python.*gen_pick_place.py.*franka-kitchen-fruit-place-120ep" >/dev/null 2>&1; then
    LAST="$(grep '\[gen\] attempt' "$LOG" 2>/dev/null | tail -1 || true)"
    echo "[relocate] still running: ${LAST:-no attempt line yet}"
    sleep 60
    continue
  fi
  if grep -q 'success_saved: 120/' "$LOG" 2>/dev/null; then
    echo "[relocate] generation complete"
    break
  fi
  if grep -q 'success_saved:' "$LOG" 2>/dev/null; then
    echo "[relocate] generator exited but did not reach 120 successes:"
    grep 'success_saved:' "$LOG" | tail -1
    exit 1
  fi
  echo "[relocate] generator not running and no completion marker; abort"
  exit 1
done

if [[ ! -d "$SRC_CACHE" ]]; then
  echo "[relocate] missing source dataset: $SRC_CACHE"
  exit 1
fi

mkdir -p "$ROOT/datasets"
if [[ -e "$DEST_DIR" || -L "$DEST_DIR" ]]; then
  echo "[relocate] destination already exists: $DEST_DIR"
  exit 1
fi

echo "[relocate] moving dataset into project..."
mv "$SRC_CACHE" "$DEST_DIR"

# Keep LeRobot cache path working via symlink back to the project copy.
mkdir -p "$LINK_CACHE_PARENT"
ln -sfn "$DEST_DIR" "$SRC_CACHE"

# Convenience symlink with short name
ln -sfn "$DEST_DIR" "$ROOT/datasets/env_a_train"

# Copy summaries next to dataset
cp -f "$ROOT/output/data/env_a_pick_place/gen_summary.json" "$DEST_DIR/" 2>/dev/null || true
cp -f "$ROOT/output/data/env_a_pick_place/episode_labels.json" "$DEST_DIR/" 2>/dev/null || true

python3 - <<'PY'
import json
from pathlib import Path
root = Path("/workspace/latency_aware_vla")
dest = root / "datasets" / "franka-kitchen-fruit-place-120ep"
info = json.loads((dest / "meta" / "info.json").read_text())
manifest = {
    "repo_id": "local/franka-kitchen-fruit-place-120ep",
    "project_path": str(dest),
    "lerobot_cache_symlink": "/workspace/cache/huggingface/lerobot/local/franka-kitchen-fruit-place-120ep",
    "total_episodes": info.get("total_episodes"),
    "total_frames": info.get("total_frames"),
    "fps": info.get("fps"),
    "note": "Dataset lives in-repo for submission; HF_LEROBOT_HOME cache points here via symlink.",
}
(root / "artifacts" / "dataset_location.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps(manifest, indent=2))
PY

echo "[relocate] done"
echo "[relocate] project dataset: $DEST_DIR"
echo "[relocate] cache symlink:   $SRC_CACHE -> $DEST_DIR"
