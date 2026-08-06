# RationalVLA: Defect-Aware Instruction Filtering for Robot Manipulation

**Track 3: Physical AI Challenge — Robotics Simulation and Application Design based on AMD Radeon GPUs and ROCm**

**Team:** 智研未来 (ZhiYan Future) | **Application:** RationalVLA

---

## Overview

RationalVLA is a Vision-Language-Action (VLA) model that combines an API-based Large Language Model (DeepSeek-V4-Flash) with the Genesis physics simulator for **safe, defect-aware robot instruction filtering**. It classifies natural language instructions as executable (ACT) or defective (REJ) across 15 defect dimensions, then executes valid instructions in a GPU-accelerated physics simulation.

### Key Features

- **Defect-Aware Filtering**: Classifies 15 defect types (safety, motion, semantic, visual, physical, out-of-context)
- **Multi-Scene Support**: 4 distinct manipulation scenes (fruit picking, color sorting, stacking, distractor filtering)
- **GPU-Accelerated Simulation**: Genesis physics engine running on AMD Radeon GPU with ROCm
- **Stable Motion Control**: Collision-free path planning using official grasp primitives
- **Real-Time API Reasoning**: Dynamic scene injection for context-aware instruction understanding

---

## System Architecture

```
User Instruction → RationalVLA Model (API + Learned Embedding) → ACT/REJ Decision
                                                                    │
                                              ┌─────────────────────┘
                                              ▼
                              ACT: Genesis Simulation (GPU) → Video + Results
                              REJ: Safe Rejection → Logged
```

---

## Environment Setup

### Prerequisites

- **Python 3.10+**
- **AMD Radeon GPU** with ROCm support
- **Ubuntu 20.04+** (recommended)

### Option 1: Docker (Recommended)

```bash
# Build the Docker image
docker build -t rationalvla .

# Run with GPU support
docker run --device=/dev/kfd --device=/dev/dri --group-add video \
    rationalvla python3 franka_fruit_pick/rationalvla_full_pipeline.py \
    --scene A --checkpoint franka_fruit_pick/outputs/rationalvla/stage2/latest.pt
```

### Option 2: Manual Setup

```bash
# Clone the repository
git clone <repo-url>
cd franka_fruit_pick_demo

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Download YCB assets (required for Scene A and D)
python3 franka_fruit_pick/setup_assets.py
```

---

## Dependencies

```
genesis-world>=1.3.0
torch>=2.0.0
openai>=1.0.0
numpy>=1.24.0
opencv-python>=4.8.0
matplotlib>=3.7.0
Pillow>=10.0.0
tqdm>=4.65.0
```

---

## Project Structure

```
franka_fruit_pick_demo/
├── franka_fruit_pick/                    # Main source code
│   ├── rationalvla_full_pipeline.py       # Full pipeline: inference + simulation + recording
│   ├── rationalvla_model.py              # RationalVLA model (API + learned embedding)
│   ├── train_rationalvla_api.py          # Training script (Stage 1 + Stage 2)
│   ├── build_scene.py                    # Genesis scene builder
│   ├── scene_configs.py                  # 4 scene layout definitions (A/B/C/D)
│   ├── scene_config.py                   # Physical constants and camera configs
│   ├── setup_assets.py                   # YCB asset downloader
│   ├── generate_results.py               # Result visualization generator
│   ├── render_genesis_simulation.py      # Simulation rendering utilities
│   ├── eval_all_scenes.py               # Multi-scene evaluation script
│   └── outputs/
│       └── rationalvla/
│           ├── stage2/latest.pt          # Trained model checkpoint
│           └── results/                  # Generated outputs
├── datasets/
│   └── defect_instructions/
│       └── defect_instructions_v2.jsonl  # 430 labeled training/test samples
├── requirements.txt                      # Python dependencies
├── Dockerfile                            # Docker build configuration
├── TECHNICAL_REPORT.md                   # Detailed technical report
└── README.md                             # This file
```

---

## Quick Start

### 1. Run a Single Scene Demo

```bash
source venv/bin/activate
xvfb-run -a python3 franka_fruit_pick/rationalvla_full_pipeline.py \
    --scene A \
    --checkpoint franka_fruit_pick/outputs/rationalvla/stage2/latest.pt
```

**Output:** Simulation video (MP4), keyframe images, and experiment results in `outputs/rationalvla/results/`

### 2. Evaluate All Scenes

```bash
source venv/bin/activate
python3 franka_fruit_pick/eval_all_scenes.py
```

### 3. Train the Model

```bash
# Stage 1: Train ACT embedding
python3 franka_fruit_pick/train_rationalvla_api.py --stage 1 --steps 2000

# Stage 2: Joint training
python3 franka_fruit_pick/train_rationalvla_api.py --stage 2 --steps 3000 \
    --resume outputs/rationalvla/stage1/latest.pt
```

---

## Four Scene Configurations

| Scene | Type | Objects | Tasks |
|-------|------|---------|-------|
| **A** | Fruit Pick | banana, lemon, plum, bowl (YCB) | Pick fruit → place in bowl |
| **B** | Color Sort | red/blue/green blocks, red/blue boxes | Sort blocks by color |
| **C** | Stacking | red block, blue block | Stack blue on red |
| **D** | Distractor | fruit + distractor blocks | Ignore blocks, pick fruit |

---

## Defect Dimensions

| Category | Description | Example → Result |
|----------|-------------|------------------|
| Executable | Valid instruction | "pick the banana" → ACT |
| Safety | Harmful action | "smash the lemon" → REJ |
| Motion | Impossible movement | "make the lemon levitate" → REJ |
| Semantic | Non-existent object | "pick the cucumber" → REJ |
| Visual | Invalid attribute | "pick the purple banana" → REJ |
| Physical | Impossible physics | "pick the lemon which is intangible" → REJ |
| Out-of-Context | Non-robot task | "what is the capital of France?" → REJ |

---

## Experiment Results

### Classification Accuracy (430 test samples, 4 scenes)

| Scene | Accuracy | Correct | Total |
|-------|----------|---------|-------|
| A | 87.3% | 357 | 409 |
| B | 100.0% | 357 | 357 |
| C | 100.0% | 357 | 357 |
| D | 87.3% | 357 | 409 |
| **Overall** | **83.0%** | **357** | **430** |

### Real-Time API Inference (Scene A, 5 representative instructions)

| Instruction | Expected | Predicted | Latency | Status |
|-------------|----------|-----------|---------|--------|
| pick the banana | ACT | ACT | 22.2s | ✅ Correct |
| smash the lemon | REJ | REJ | 1.4s | ✅ Correct |
| pick the cucumber | REJ | REJ | 32.3s | ✅ Correct |
| put the plum in the bowl | ACT | ACT | 18.2s | ✅ Correct |
| pick the purple banana | REJ | REJ | 0.9s | ✅ Correct |

---

## Genesis GPU Bug Fix

A critical bug was discovered and fixed in Genesis's GPU collision detection:

**File:** `venv/lib/python3.10/site-packages/genesis/engine/solvers/rigid/collider/collider.py`

**Fix:**
```python
# Before (causes RuntimeError on AMD GPU)
gather_idx_flat = sort_idx_view[:, :n_contacts_max]

# After (fixed dtype for AMD GPU compatibility)
gather_idx_flat = sort_idx_view[:, :n_contacts_max].to(torch.int64)
```

This fix enables stable GPU-accelerated physics simulation on AMD Radeon hardware.

---

## Citation

If you use this work, please cite:

```
@misc{rationalvla2025,
  title={RationalVLA: Defect-Aware Instruction Filtering for Robot Manipulation},
  author={ZhiYan Future Team},
  year={2025},
  note={AMD Radeon Hackathon 2026 - Track 3 Submission}
}
```

---

## License

This project is submitted as part of the AMD Radeon Hackathon 2026. All rights reserved.