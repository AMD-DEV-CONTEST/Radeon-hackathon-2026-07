#!/bin/bash

set -e 

echo "=== 1. INSTALL SYSTEM DEPENDENCIES ==="
apt-get update
apt-get install -y build-essential cmake libgomp1 libstdc++6 pkg-config \
    libcairo2-dev libpango1.0-dev libgdk-pixbuf-2.0-dev libffi-dev \
    shared-mime-info ffmpeg texlive texlive-latex-extra \
    texlive-fonts-extra texlive-latex-recommended
rm -rf /var/lib/apt/lists/*

echo "=== 2. INSTALL PYTHON DEPENDENCIES ==="
pip install --no-cache-dir --break-system-packages torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/rocm6.2
CMAKE_ARGS="-DGGML_HIP=on" pip install --no-cache-dir --break-system-packages llama-cpp-python==0.3.33

pip install --no-cache-dir --break-system-packages -r requirements.txt

echo "=== 3. CONFIGURATION MENU ==="
export COQUI_TOS_AGREED=1

echo "=== 4. START SERVICES ==="

cleanup() {
    echo "Stopping services..."
    kill $API_PID $FRONTEND_PID 2>/dev/null
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

export HF_ENDPOINT=https://hf-mirror.com

python init.py

echo "Starting API on port 8000..."
uvicorn backend.api:app --host 0.0.0.0 --port 8000 &
API_PID=$!

sleep 3

echo "Starting Gradio interface on port 7860..."
python frontend/app.py &
FRONTEND_PID=$!

wait -n $API_PID $FRONTEND_PID