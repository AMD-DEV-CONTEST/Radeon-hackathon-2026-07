#!/usr/bin/env bash
# One-shot fix on Radeon Cloud so `from src...` works even from notebooks/.
set -euo pipefail
ROOT="${1:-/workspace/Radeon-hackathon-2026-07}"
cd "$ROOT"
git fetch origin track2-private-local-agent
git checkout -f origin/track2-private-local-agent -- notebooks/visual_no_tunnel.ipynb pyproject.toml src/app/notebook_visual.py || true
git pull origin track2-private-local-agent || true
ln -sfn "$ROOT/src" "$ROOT/notebooks/src"
python -m pip install -q -e "$ROOT"
echo "OK: notebooks/src -> $ROOT/src"
echo "Now: close visual_no_tunnel.ipynb, reopen it, Kernel→Restart, run the ONLY code cell."
