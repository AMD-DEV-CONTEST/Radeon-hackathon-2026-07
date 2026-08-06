[English](README.md) | [中文](README-cn.md)

# Franka-Pick-AMD: Franka Robot Grasping Project Based on AMD ROCm

## 1. Project Introduction

### Problem Definition

The core problem of robot policy learning is: **making the model learn to map from "visual observation + language task" to "robot action"**.

Collecting data with real robotic arms faces four major problems:

1. **Expensive equipment**: Research-grade robotic arms like Franka are costly
2. **Slow collection**: A single real grasp takes from several seconds to tens of seconds
3. **Collision safety risks**: Wrong actions may damage hardware
4. **Experiments hard to reproduce**: Lighting, friction, and initial positions are difficult to reproduce precisely

### Solution

This project uses the **Genesis simulator** to replace real robotic arms for data collection and evaluation:

- **Data Generation**: The IK (Inverse Kinematics) expert controller in Genesis automatically generates grasp demonstration data, requiring no human teaching
- **Model Training**: Fine-tune on the pretrained **SmolVLA** (Vision-Language-Action) model, freezing the visual encoder and training only the expert layers and state projection layers
- **Closed-loop Evaluation**: Put the fine-tuned model back into Genesis, autonomously controlling Franka to complete grasping based only on visual observations

### Core Metrics

| Metric | Value |
| - | - |
| Robot | Franka Panda, 7 arm joints + 2 gripper (9D action space) |
| Observation | Top-view + wrist camera images + 9D joint state + language task |
| Data Frequency | 30 FPS |
| Trajectory Length | 135 frames (~4.5 seconds) |
| Model Parameters | ~450M total (~100M trainable, ~350M frozen) |
| Closed-loop Success Rate | 85% (1000 episodes training, 8000 steps) |

### Technology Stack

The entire project is divided into 6 layers from bottom to top:

```
┌─────────────────────────────────────────────────────────┐
│  Layer 6: SmolVLA                                        │
│           Vision + Language + Robot State → Robot Action │
├─────────────────────────────────────────────────────────┤
│  Layer 5: LeRobot + Transformers + Accelerate            │
│           Dataset management, policy interface,          │
│           model config, weight loading                   │
├─────────────────────────────────────────────────────────┤
│  Layer 4: Genesis + Taichi                               │
│           Robot simulation, collision detection,         │
│           IK solving, camera rendering                   │
├─────────────────────────────────────────────────────────┤
│  Layer 3: PyTorch + AOTriton                             │
│           Tensor computation, autodiff, model training,  │
│           Attention acceleration                         │
├─────────────────────────────────────────────────────────┤
│  Layer 2: ROCm + HIP + Mesa                              │
│           AMD GPU compute and graphics rendering platform│
├─────────────────────────────────────────────────────────┤
│  Layer 1: AMD GPU + amdgpu driver                        │
│           Actually performs computation and rendering    │
└─────────────────────────────────────────────────────────┘
```

**Core dependency chain**: Genesis generates simulation data → LeRobot saves in standard format → SmolVLA reads and trains → during evaluation, the model is put back into Genesis for closed-loop inference.

---

## 2. Development Process

### Key Decisions

**Why choose SmolVLA instead of training from scratch?**

- SmolVLA has been pretrained on massive vision-language data, with basic scene understanding and language following capabilities
- This project only needs to fine-tune layers related to robot action prediction (expert + state projection), significantly reducing data and compute requirements
- Trainable parameters are only ~22%, allowing single-GPU training on AMD GPU

**Why use simulation data instead of real data?**

- Simulation can generate diverse scenes infinitely, automatically randomizing block positions to avoid uniform data distribution
- The IK controller acts as an "all-knowing" expert, generating precise, noise-free annotated actions
- Zero collision risk, the same task can be run repeatedly, ensuring experiment reproducibility

### Challenges and Solutions

| Challenge | Solution |
| - | - |
| Insufficient model generalization, grasp success rate below 80% | Fine-tuned learning rate parameters (added warmup, adjusted decay strategy), increased batch size and training steps |

### Future Improvements

- Use models with stronger generalization ability such as **Pi0.5** to replace SmolVLA
- Add multi-scene, multi-object training data to improve cross-scene transfer capability
- Introduce data augmentation (lighting variations, background perturbations) to improve visual robustness
- Attempt Sim-to-Real transfer from simulation to real world

---

## 3. Code Source Description

### Base Project

This project is organized and further developed based on [PhysicalAI-AIM / Robot Synthetic Data Generation Workshop](https://github.com/PhysicalAI-AIM/Robot_synthetic_data_generation_workshop).

### Open Source Dependencies

| Project | Purpose | Link |
| - | - | - |
| LeRobot (Hugging Face) | Robot learning data format and training framework | https://github.com/huggingface/lerobot |
| Genesis Embodied AI | Robot simulation environment | https://genesis-embodied-ai.github.io/ |
| SmolVLA | Vision-Language-Action model | https://huggingface.co/blog/smolvla |
| AMD ROCm | AMD GPU accelerated computing platform | https://rocm.docs.amd.com/ |

### Modifications and Original Work

| Part | Description |
| - | - |
| **Directory restructure** | Reorganized the flat project structure into a layered structure of `src/` (core code), `data/` (data generation scripts), `configs/` (scene configs) |
| **Training parameter expansion** | Added `--lr`, `--lr-warmup-steps`, `--lr-decay-steps`, `--lr-decay-end`, `--vlm-backbone` and other parameters for more flexible training tuning |
| **Complete bilingual documentation** | Added comprehensive documentation covering environment setup, model preparation, parameter descriptions, and experimental results |

---

## 4. Team Division

| Member | Role |
| - | - |
| **star** | Model fine-tuning, code maintenance, result analysis |
| **Be_Yourself** | Environment configuration, model training, documentation |
| **coC.3** | Environment configuration, model training, demo video production |

Collaboration approach: Team members collaborate on code via Git. star is responsible for core code modifications and model tuning, Be_Yourself and coC.3 are responsible for environment setup, training execution, and result validation. The three members jointly complete documentation and presentation materials.

---

## 5. Installation and Running

### 5.1 Requirements

| Component | Version / Requirement |
| - | - |
| Operating System | Ubuntu 22.04 |
| GPU | AMD GPU |

### 5.2 Installation Steps

#### 1) Install Python Dependencies

```bash
python -m pip install \
torch==2.11.0 \
torchvision==0.26.0 \
torchaudio==2.11.0 \
triton==3.6.0 \
--index-url https://download.pytorch.org/whl/rocm7.2

pip install -r requirements.txt
```

#### 2) Install Genesis

Genesis is responsible for robot simulation, IK solving, and camera rendering. Install from the GitHub `main` branch:

```bash
cd /workspace
git clone --depth 1 https://github.com/Genesis-Embodied-AI/Genesis.git Genesis
python -m pip install /workspace/Genesis
```

#### 3) Install FFmpeg and TorchCodec

LeRobot encodes camera frames into videos for storage, requiring video codec support:

```bash
# Install FFmpeg
apt-get update
apt-get install -y ffmpeg libavcodec-dev libavformat-dev libavutil-dev \
  libavdevice-dev libavfilter-dev libswscale-dev libswresample-dev

# Install TorchCodec
bash setup_torchcodec.sh
```

#### 4) Verify Installation

```bash
python - <<'PY'
import torch; assert torch.cuda.is_available(), "ROCm not available"
import genesis; print("Genesis OK")
import lerobot; print("LeRobot OK")
import torchcodec; print("TorchCodec OK")
import transformers, accelerate, safetensors; print("All deps OK")
PY
```

### 5.3 Model Preparation

This project requires two pretrained models, downloaded via Hugging Face:

```bash
pip install huggingface_hub

# SmolVLA policy model
huggingface-cli download lerobot/smolvla_base \
  --local-dir /workspace/models/smolvla_base

# SmolVLM2 vision-language backbone
huggingface-cli download HuggingFaceTB/SmolVLM2-500M-Video-Instruct \
  --local-dir /workspace/models/SmolVLM2-500M-Video-Instruct
```

Model directory structure:

```
/workspace/models/
├── smolvla_base/
│   ├── config.json
│   ├── model.safetensors
│   ├── preprocessor_config.json
│   └── processor_config.json
└── SmolVLM2-500M-Video-Instruct/
    ├── config.json
    ├── model.safetensors
    ├── preprocessor_config.json
    └── processor_config.json
```

If Hugging Face is not accessible, download on another machine and copy to the corresponding directory.

#### Offline Mode

```bash
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
```

### 5.4 Workflow

Complete workflow: **Generate Data → Train → Evaluate**

```
Genesis generates expert trajectories
        ↓ (saved as LeRobot format)
LeRobot dataset
        ↓ (SmolVLA reads and trains)
Fine-tuned SmolVLA policy
        ↓ (put back into Genesis for evaluation)
Closed-loop grasp success rate
```

---

#### 5.4.1 Generate Expert Grasping Data

First download scene assets:

```bash
bash data/download_kitchen_assets.sh
```

Run data generation:

```bash
python data/generate_expert_data.py \
  --scene rustic_kitchen \
  --anchor floor_origin \
  --camera-layout up_wrist \
  --n-episodes 1000 \
  --repo-id local/franka-pick \
  --seed 42
```

**Parameter Description**:

| Parameter | Default | Description |
| - | - | - |
| `--repo-id` | `local/kitchen-pick` | LeRobot dataset name, `local/` prefix means saving to local cache |
| `--scene` | `rustic_kitchen` | Scene name (must be consistent with training and evaluation) |
| `--anchor` | `floor_origin` | Scene anchor, determines Franka base position and orientation |
| `--camera-layout` | `up_side` | Camera layout: `up_wrist` = top-view + wrist, `up_side` = top-view + side |
| `--n-episodes` | `10` | Number of complete grasp trajectories to generate |
| `--seed` | `42` | Random seed, ensures experiment reproducibility |
| `--fps` | `30` | Data collection frame rate |
| `--task` | `Pick up the cube.` | Language task description |
| `--add-goal` | `False` | Whether to append cube (x,y) coordinates to observation.state |
| `--add-phase` | `False` | Whether to append normalized time t/T to observation.state |
| `--no-videos` | `False` | Whether to store as PNG instead of video |

**Generation Process**: Each trajectory is 135 frames (~4.5 seconds), the expert controller sequentially performs approach → descend → close gripper → lift. Each frame records top-view/wrist camera images, joint state, expert target action, and language task.

Typical output:
```
[gen] ep 1/1 [OK]  lift=0.1448m  sustain=39
```

---

#### 5.4.2 Training

```bash
python src/train.py \
  --dataset-id local/franka-pick \
  --pretrained /workspace/models/smolvla_base \
  --vlm-backbone /workspace/models/SmolVLM2-500M-Video-Instruct \
  --n-steps 10000 \
  --lr-decay-end 2.5e-6 \
  --lr-decay-steps 6000 \
  --batch-size 32 \
  --num-workers 4 \
  --save-every 0 \
  --log-every 20 \
  --seed 42 \
  --output-dir ./output \
  --run-name smolvla_franka_pick
```

**Parameter Description**:

| Parameter | Default | Description |
| - | - | - |
| `--dataset-id` | `local/so101-genesis-pick` | LeRobot dataset ID (consistent with `--repo-id` from data generation) |
| `--pretrained` | `lerobot/smolvla_base` | SmolVLA pretrained model directory or HF model id |
| `--vlm-backbone` | `HuggingFaceTB/SmolVLM2-500M-Video-Instruct` | VLM vision-language backbone model path |
| `--n-steps` | `2000` | Total training steps |
| `--batch-size` | `8` | Batch size per step |
| `--lr` | `None` | Peak learning rate (`None` uses default `1e-4`) |
| `--lr-warmup-steps` | `200` | Linear learning rate warmup steps (`0` = disabled) |
| `--lr-decay-steps` | `2000` | Cosine decay steps |
| `--lr-decay-end` | `1e-5` | Minimum LR after decay |
| `--num-workers` | `2` | DataLoader process count (`0` to avoid video decoder crashes) |
| `--save-every` | `500` | Save checkpoint every N steps (`0` = final only) |
| `--log-every` | `50` | Print log every N steps |
| `--seed` | `None` | Random seed (`None` = non-deterministic) |
| `--output-dir` | `./output` | Output root directory |
| `--run-name` | `smolvla_pick` | Experiment name, model saved under `output/train/<run-name>/` |

**Training Output**:

```
output/train/smolvla_franka_pick/
├── final/                  # Final model (ready for evaluation)
├── train_summary.json      # Training summary (params, Loss, VRAM, time)
└── train_metrics.json      # Per-step metrics (step/loss/grad_norm/lr/step_time)
```

---

#### 5.4.3 Closed-loop Evaluation

Put the trained model back into Genesis, autonomously controlling Franka to grasp the block based only on visual observations:

```bash
python src/eval.py \
  --checkpoint output/train/smolvla_franka_pick/final \
  --dataset-id local/franka-pick \
  --vlm-backbone /workspace/models/SmolVLM2-500M-Video-Instruct \
  --scene rustic_kitchen \
  --anchor floor_origin \
  --camera-layout up_wrist \
  --action-horizon 20 \
  --n-episodes 100 \
  --seed 99 \
  --record-video \
  --run-name smolvla_franka_pick
```

**Parameter Description**:

| Parameter | Default | Description |
| - | - | - |
| `--policy-type` | `smolvla` | Policy type: `bc` / `act` / `smolvla` |
| `--checkpoint` | Required | Trained checkpoint directory |
| `--dataset-id` | `local/kitchen-pick` | Dataset ID, used to read normalization statistics |
| `--task` | `Pick up the red cube.` | Language task description |
| `--vlm-backbone` | `HuggingFaceTB/SmolVLM2-500M-Video-Instruct` | VLM backbone model path |
| `--scene` | `rustic_kitchen` | Scene name (must match training) |
| `--anchor` | `floor_origin` | Scene anchor |
| `--camera-layout` | `up_side` | Camera layout: `up_wrist` / `up_side` |
| `--n-episodes` | `10` | Number of evaluation episodes |
| `--max-steps` | `150` | Maximum simulation steps per episode |
| `--action-horizon` | `1` | Action steps executed per inference |
| `--max-delta-rad` | `0.15` | Maximum action change between adjacent frames (radians) |
| `--seed` | `42` | Random seed (determines cube initial position sequence) |
| `--success-lift-m` | `0.02` | Minimum lift height for success (meters) |
| `--success-sustain` | `8` | Minimum sustained frames for success |
| `--success-final-m` | `0.01` | Minimum final height for success (meters) |
| `--record-video` | `False` | Whether to record evaluation videos |
| `--output-dir` | `./output` | Output root directory |
| `--run-name` | `kitchen_eval` | Evaluation name, results saved under `output/eval/<run-name>/` |

**Evaluation Output**:

```
output/eval/smolvla_franka_pick/
├── eval_summary.json      # Evaluation summary (success rate, per-episode details)
└── videos/
    ├── ep000_success_up.mp4
    ├── ep000_success_side.mp4
    ├── ep001_fail_up.mp4
    └── ep001_fail_side.mp4
```

| File | Description |
| - | - |
| `eval_summary.json` | Total episodes, success count, success rate, scene info, per-episode detailed results (block position, lift height, sustained frames, etc.) |
| `videos/` | Evaluation video directory (requires `--record-video`) |

Video file naming: `ep{index}_{success|fail}_{up|side}.mp4`. Comparing success and failure videos allows intuitive analysis of common error patterns (missing the block, incorrect gripper closing timing, slipping after lifting, etc.).

---

### 5.5 Reference Results

The following are reference results for 1000 episodes trained for 8000 steps, evaluated 100 times:

| Phase | Metric | Value |
| - | - | - |
| Data Generation | Frames per trajectory | 135 |
| Data Generation | Data frequency | 30 FPS |
| Training | Training steps | 8000 |
| Training | Batch Size | 32 |
| Training | Initial Loss | 2.8322 |
| Training | Final Loss | 0.0116 |
| Training | Training time | ~5032s |
| Training | Peak VRAM | ~5.8 GB |
| Evaluation | Closed-loop success rate | 80/100 = 80% |
