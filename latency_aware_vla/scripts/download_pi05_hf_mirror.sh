#!/usr/bin/env bash
# Download lerobot/pi05_base via hf-mirror (huggingface.co often unreachable).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST_DIR="${1:-/workspace/models/pi05_base}"
LOG="$ROOT/output/download_pi05_curl.log"
mkdir -p "$DEST_DIR" "$ROOT/output" "$ROOT/artifacts/formal/pi05_smoke"

export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

echo "[download] dest=$DEST_DIR endpoint=$HF_ENDPOINT"
# metadata / config (best-effort; weights are the critical file)
for f in config.json README.md policy_preprocessor.json policy_postprocessor.json; do
  if [[ ! -s "$DEST_DIR/$f" ]]; then
    curl -fsSL -o "$DEST_DIR/$f" "$HF_ENDPOINT/lerobot/pi05_base/resolve/main/$f" || true
  fi
done

DEST="$DEST_DIR/model.safetensors"
EXPECTED=14467165872
echo "[$(date -Is)] start curl download" | tee "$LOG"
curl -L --fail --retry 30 --retry-delay 5 --retry-all-errors \
  -C - \
  --connect-timeout 30 \
  --speed-time 120 --speed-limit 5000 \
  -o "$DEST" \
  "$HF_ENDPOINT/lerobot/pi05_base/resolve/main/model.safetensors" \
  |& tee -a "$LOG"

SZ=$(stat -c%s "$DEST" 2>/dev/null || echo 0)
python3 - <<PY
import json
from pathlib import Path
sz=int("$SZ")
ok = sz >= 14000000000
report={
  "status": "ok" if ok else "incomplete",
  "path": "$DEST_DIR",
  "model_safetensors_bytes": sz,
  "expected_bytes": $EXPECTED,
  "endpoint": "$HF_ENDPOINT",
}
Path("$ROOT/artifacts/formal/pi05_smoke/download_report.json").write_text(json.dumps(report, indent=2)+"\n")
print(report)
if not ok:
    raise SystemExit(1)
PY
echo "[download] done"
