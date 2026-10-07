# Dockerfile — Franka Multi-Fruit Sorting via SmolVLA on AMD ROCm
# Track 3 Submission — AMD Radeon Hackathon 2026

FROM rocm/pytorch:latest

# Set environment variables for headless rendering
ENV MPLBACKEND=Agg \
    TOKENIZERS_PARALLELISM=false \
    HF_HUB_OFFLINE=0 \
    PYTHONUNBUFFERED=1

WORKDIR /workspace

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    wget \
    curl \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker layer caching
COPY submission/requirements.txt /workspace/requirements.txt
RUN pip install --no-cache-dir -r /workspace/requirements.txt

# Install Playwright browsers (for remote execution utilities)
RUN python -m playwright install chromium --with-deps

# Clone the starter repository (provides build_scene, grasp_demo, paths modules)
RUN git clone https://github.com/wangxunx/franka_fruit_pick_demo.git /workspace/franka_fruit_pick_demo

# Copy project source code (configs live under submission/configs/)
COPY submission/ /workspace/submission/

# Set Python path to include starter repo modules and submission configs
ENV PYTHONPATH=/workspace:/workspace/submission:/workspace/franka_fruit_pick_demo:/workspace/franka_fruit_pick_demo/franka_fruit_pick:$PYTHONPATH

# Default entrypoint
CMD ["bash"]

# Usage examples:
# 1. Build scene and run scripted demo:
#    python /workspace/submission/src/scene/sort_demo.py --save-frames
# 2. Collect dataset:
#    python /workspace/submission/src/data/record_sort_dataset.py --episodes 5 --fps 30 --img-wh 224 224
# 3. Train SmolVLA:
#    python /workspace/submission/src/train/run_smolvla_train.py
# 4. Closed-loop evaluation:
#    python /workspace/submission/src/eval/eval_sort_smolvla.py --checkpoint 002000 --episodes 1
