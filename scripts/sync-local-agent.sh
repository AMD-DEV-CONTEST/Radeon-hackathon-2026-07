#!/usr/bin/env bash
# Sync Local Agent release files into botversex-local-agent (friends clone this repo).
#
# Usage:
#   LOCAL_AGENT_DIR=/path/to/botversex-local-agent bash scripts/sync-local-agent.sh
#   bash scripts/sync-local-agent.sh   # defaults to .tmp/botversex-local-agent
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${LOCAL_AGENT_DIR:-$ROOT/.tmp/botversex-local-agent}"

if [ ! -d "$DEST" ]; then
  echo "ERROR: Local Agent directory not found: $DEST"
  echo "Clone it first: git clone https://github.com/metahubaifeel/botversex-local-agent.git"
  exit 1
fi

echo "[sync-local-agent] ROOT=$ROOT"
echo "[sync-local-agent] DEST=$DEST"

# HTTPS entrypoint + cryptography dep (mixed-content fix for cloud Setup page)
cp "$ROOT/apps/realtime/run_api.py" "$DEST/run_api.py"
cp "$ROOT/apps/realtime/requirements.txt" "$DEST/requirements.txt"

# Reachy proxy + serial auto-detect
cp "$ROOT/apps/realtime/api/reachy_proxy.py" "$DEST/api/reachy_proxy.py"

# M27: B601-RS API + runtime
if [ -f "$ROOT/apps/realtime/api/b601.py" ]; then
  cp "$ROOT/apps/realtime/api/b601.py" "$DEST/api/b601.py"
  echo "[sync-local-agent] api/b601.py"
fi
if [ -d "$ROOT/apps/realtime/runtimes/b601_rs" ]; then
  mkdir -p "$DEST/runtimes/b601_rs"
  cp "$ROOT/apps/realtime/runtimes/b601_rs/__init__.py" "$DEST/runtimes/b601_rs/__init__.py"
  echo "[sync-local-agent] runtimes/b601_rs/"
fi
if [ -d "$ROOT/apps/realtime/static/urdf/b601_rs" ]; then
  mkdir -p "$DEST/static/urdf/b601_rs"
  cp -r "$ROOT/apps/realtime/static/urdf/b601_rs/"* "$DEST/static/urdf/b601_rs/" 2>/dev/null || true
fi

# Merge b601_rs into destination robots.json if present
python3 - <<'PY' "$ROOT/apps/realtime/config/robots.json" "$DEST/config/robots.json"
import json
import sys
from pathlib import Path

src_path, dst_path = Path(sys.argv[1]), Path(sys.argv[2])
src = json.loads(src_path.read_text(encoding="utf-8"))
dst = json.loads(dst_path.read_text(encoding="utf-8"))

b601_src = next((r for r in src["robots"] if r["runtime_id"] == "b601_rs"), None)
if b601_src:
    dst["robots"] = [r for r in dst["robots"] if r["runtime_id"] != "b601_rs"]
    dst["robots"].append(b601_src)
    dst_path.write_text(json.dumps(dst, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("[sync-local-agent] robots.json + b601_rs")
PY

# Reachy serial: auto (preserve other robot entries and sdk_path in destination).
python3 - <<'PY' "$ROOT/apps/realtime/config/robots.json" "$DEST/config/robots.json"
import json
import sys
from pathlib import Path

src_path, dst_path = Path(sys.argv[1]), Path(sys.argv[2])
src = json.loads(src_path.read_text(encoding="utf-8"))
dst = json.loads(dst_path.read_text(encoding="utf-8"))

reachy_src = next(r for r in src["robots"] if r["runtime_id"] == "reachy_mini")
reachy_dst = next(r for r in dst["robots"] if r["runtime_id"] == "reachy_mini")
reachy_dst["transport"] = reachy_src["transport"]
reachy_dst["service"]["command"] = reachy_src["service"]["command"]

dst_path.write_text(json.dumps(dst, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("[sync-local-agent] reachy_mini transport.serial -> auto")
PY

# Ensure certs/ is gitignored (per-machine SSL, auto-generated on first run)
if ! grep -q '^certs/' "$DEST/.gitignore" 2>/dev/null; then
  printf '\n# Auto-generated SSL certificates (per-machine)\ncerts/\n' >> "$DEST/.gitignore"
  echo "[sync-local-agent] appended certs/ to .gitignore"
fi

echo "[sync-local-agent] Done. Commit and push in $DEST when ready."
