#!/usr/bin/env bash
# Bootstrap PrivateLocalAgent on Radeon Cloud Notebook (ROCm)
set -euo pipefail

cd "$(dirname "$0")/.."
echo "[1/5] Python: $(python3 --version 2>/dev/null || python --version)"

PY=python3
command -v python3 >/dev/null 2>&1 || PY=python

$PY -m pip install -U pip
$PY -m pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "[warn] Created .env — set RADEON_API_KEY if using API backend."
fi

echo "[2/5] Verify GPU / ROCm"
$PY scripts/verify_rocm.py || true

echo "[3/5] Switch config to local_transformers if GPU is visible"
$PY - <<'PY'
import torch, pathlib, re
cfg = pathlib.Path("configs/default.yaml")
text = cfg.read_text(encoding="utf-8")
if torch.cuda.is_available():
    text = re.sub(r'backend:\s*".*?"', 'backend: "local_transformers"', text, count=1)
    cfg.write_text(text, encoding="utf-8")
    print("GPU detected → llm.backend = local_transformers")
else:
    print("No GPU → keep openai_compatible backend")
PY

echo "[4/5] Ingest sample docs"
$PY scripts/ingest_sample.py

echo "[5/5] Launch Gradio on 0.0.0.0:7860"
$PY app.py
