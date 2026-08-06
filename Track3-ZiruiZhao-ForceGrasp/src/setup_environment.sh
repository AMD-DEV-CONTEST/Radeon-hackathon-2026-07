#!/bin/bash
set -e

echo "=== Step 1: Install genesis (main) + lerobot ==="
pip install -q git+https://github.com/Genesis-Embodied-AI/Genesis.git@main \
  lerobot==0.4.4 transformers accelerate safetensors matplotlib Pillow jupyter nbconvert ipykernel num2words 2>&1 | tail -5

echo "=== Step 2: Rebuild skimage with pinned numpy ==="
pip install --force-reinstall --no-cache-dir -q "scikit-image>=0.22" "numpy==2.1.2" 2>&1 | tail -5

echo "=== Step 3: Build torchcodec (CPU-only) ==="
bash "$(dirname "$0")/setup_torchcodec.sh"

echo "=== Step 4: Install system deps ==="
apt-get update -qq && apt-get install -y -qq xvfb ffmpeg > /dev/null 2>&1 || true

echo "=== Step 5: Verify ==="
python -c "import numpy; print(f'numpy: {numpy.__version__}')"
python -c "import lerobot; print(f'lerobot: {lerobot.__version__}')"
python -c "import genesis; print(f'genesis: {genesis.__version__}')"

echo "=== Step 6: Clean old output ==="
rm -rf output/data output/train output/eval output/*.ipynb output/*.png output/*.mp4 output/*.json 2>/dev/null || true

echo "=== Step 7: Run notebook ==="
jupyter nbconvert --to notebook --execute \
  --ExecutePreprocessor.timeout=3600 \
  --ExecutePreprocessor.kernel_name=python3 \
  --allow-errors \
  --output output/workshop_pipeline_executed.ipynb \
  workshop_pipeline.ipynb 2>&1

echo "=== Collecting artifacts ==="
find output -name "*.png" -o -name "*.mp4" -o -name "*.json" 2>/dev/null | head -30 || true
ls -laR output/ 2>/dev/null | head -80 || true
echo "=== DONE ==="
