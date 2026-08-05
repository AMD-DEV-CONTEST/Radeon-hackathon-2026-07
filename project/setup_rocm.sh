#!/usr/bin/env bash
# Environment setup for AMD Radeon GPU (ROCm) machine.
# Run this on the GPU instance you get from the hackathon's Radeon access.
set -e

echo "== Installing Python deps =="
pip install --upgrade pip
pip install mujoco numpy imageio imageio-ffmpeg

echo "== Installing PyTorch with ROCm support =="
# Check https://pytorch.org/get-started/locally/ for the ROCm version that
# matches the driver on your allocated instance (commonly ROCm 6.x).
pip install torch --index-url https://download.pytorch.org/whl/rocm6.1

echo "== Verifying GPU is visible to PyTorch =="
python3 -c "import torch; print('CUDA/ROCm available:', torch.cuda.is_available()); print('Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU only')"

echo "== Done. Run the demo with: =="
echo "  cd sim && python3 run_sim.py --duration 15 --compare --video ../docs/demo.mp4"
echo "  cd ../perception && python3 terrain_classifier.py --benchmark"
