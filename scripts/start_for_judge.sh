#!/usr/bin/env bash
# Judge / Demo one-shot launcher (Radeon Cloud). Same path as START_HERE.md + video.
set -euo pipefail
cd "$(dirname "$0")/.."
export PLA_DATA_ROOT="${PLA_DATA_ROOT:-/workspace/persistence/PrivateLocalAgent}"
export HF_HOME="${HF_HOME:-/workspace/persistence/huggingface}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
mkdir -p "$PLA_DATA_ROOT" "$HF_HOME" 2>/dev/null || true

echo "=== PrivateLocalAgent · START (matches video / START_HERE.md) ==="
echo "PR: https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/pull/40"
echo "Video: https://github.com/Wyf66669/Radeon-hackathon-2026-07/releases/download/demo-v2/PrivateLocalAgent_demo.mp4"
echo

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt
pip install -q Pillow rapidocr-onnxruntime || true

python scripts/verify_rocm.py
python scripts/ingest_sample.py
python scripts/demo_judge.py

echo
echo "Web UI (same prompts as video):"
echo "  PLA_ALLOW_PUBLIC=1 python scripts/run_cloudflare_tunnel.py"
