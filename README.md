# Radeon-VLA-SO101

**AMD ROCm Accelerated Vision-Language-Action Robot Manipulation Demo**
*AMD Radeon Hackathon 2026 — Track 3 (Physical AI)*

An end-to-end Vision-Language-Action (VLA) system: a natural-language instruction
plus an RGB observation and the robot's joint state drive a **SmolVLA** policy that
predicts an action chunk, which is executed by an **SO-101** arm in the **Genesis**
simulator — trained and profiled on an **AMD Radeon (ROCm)** GPU.

```
        Instruction ("Pick the red cube and place it into the basket")
              │
              ▼
        Text Encoder ─┐
                      │
   RGB Camera ──►  VLA Policy (SmolVLA)  ◄── Robot State (6-D joints)
                      │
                      ▼
              Action Chunk (6-D joint targets)
                      │
                      ▼
             SO-101 Controller ─► Genesis ─► Environment Feedback
```

> Built on the same verified AMD stack as the sibling `franka_fruit_pick` demo
> (Genesis + LeRobot 0.6.0 + SmolVLA + ROCm 7.2.1), re-skinned to the **SO-101**
> arm and a **colored-cube pick-and-place** task, with the VLA/env/benchmark
> abstractions this track asks for.

---

## 1. Problem

Traditional robot manipulation is **task-specific**: every new task means new
hand-engineered perception + motion code, and collecting real demonstrations is
slow and expensive. A pipeline tuned to "pick the banana" does not transfer to
"pick the red cube" without re-programming.

## 2. Solution

**Vision-Language-Action models** enable *language-conditioned* manipulation: one
policy takes an image + a free-form instruction + the robot state and emits
actions. Swapping the task is swapping the sentence — "pick the **red** cube" vs
"pick the **blue** cube" — with no code change. This project fine-tunes **SmolVLA**
(a 450M VLA) on synthetic SO-101 demonstrations and runs it closed-loop.

## 3. Architecture

| Layer | Component | File |
|---|---|---|
| **Instruction + Vision + State** | Observation (`{image, wrist_image, state, instruction}`) | `simulation/genesis_env.py` |
| **VLA** | `VLAAgent` interface + `SmolVLAAgent` (ACT/OpenVLA pluggable) | `vla/agent.py` |
| **Action** | 6-D joint-target chunk via `predict()` | `vla/inference.py` |
| **Controller** | `env.step(action)` position-controls the SO-101 | `simulation/genesis_env.py` |
| **Simulator** | Genesis rigid-body scene (SO-101 + cubes + basket + 2 cameras) | `simulation/genesis_env.py` |

The VLA interface is deliberately uniform:

```python
class VLAAgent:
    def predict(self, image, instruction, robot_state, *, wrist_image=None):
        """return: (T, 6) action chunk of joint targets"""
```

`SmolVLAAgent` is the default; `ACTAgent` reuses the same loader; `OpenVLAAgent`
is a stubbed extension point.

## 4. AMD Acceleration

- **Hardware:** AMD Radeon GPU (developed/verified target: Radeon AI PRO R9700,
  gfx1201 / RDNA4).
- **Software:** ROCm 7.2.1 + the prebuilt ROCm torch/vision/audio/triton wheels
  from `repo.radeon.com`. On ROCm the device string is still `"cuda"` (the ROCm
  torch build maps CUDA APIs onto HIP), so no code changes are needed.

`benchmark/rocm_perf.py` profiles SmolVLA inference on CPU vs the AMD GPU and
writes `benchmark/results.json`:

| Device | Latency | FPS | GPU Mem |
|---|---|---|---|
| CPU | *(measured on your machine)* | | — |
| AMD GPU | *(measured on your machine)* | | *(reported)* |

Run it to fill this in — the harness records mean/p50/p95 latency, FPS and
`torch.cuda.max_memory_allocated` (HIP allocations), plus the GPU→CPU speedup.

## 5. Demo Video

`demo/demo.mp4` shows one closed-loop rollout: the instruction, the camera view,
the VLA's predicted actions, and the SO-101 completing the pick-and-place. See
`demo/README.md` for how to generate it.

---

## AMD ROCm setup

Requires an AMD ROCm machine (Ubuntu 24.04 / Python 3.12 recommended, matching the
ROCm cp312 wheels). Install the **ROCm torch stack first**, then the rest:

```bash
cd radeon-vla-so101

# 1) ROCm 7.2.1 torch stack (prebuilt wheels).
wget https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/torch-2.9.1%2Brocm7.2.1.lw.gitff65f5bc-cp312-cp312-linux_x86_64.whl
wget https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/torchvision-0.24.0%2Brocm7.2.1.gitb919bd0c-cp312-cp312-linux_x86_64.whl
wget https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/torchaudio-2.9.0%2Brocm7.2.1.gite3c6ee2b-cp312-cp312-linux_x86_64.whl
wget https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/triton-3.5.1%2Brocm7.2.1.gita272dfa8-cp312-cp312-linux_x86_64.whl
pip install torch-2.9.1+rocm7.2.1*.whl torchvision-0.24.0+rocm7.2.1*.whl \
            torchaudio-2.9.0+rocm7.2.1*.whl triton-3.5.1+rocm7.2.1*.whl

# 2) Everything else (Genesis, LeRobot[training,smolvla], etc.).
pip install -r requirements.txt

# 3) Verify torch is a ROCm build.
python -c "import torch; print('hip', torch.version.hip); assert torch.version.hip"
```

> The sibling `../docker/Dockerfile` reproduces this exact environment and works
> for this sub-project too (mount the repo, `pip install -r radeon-vla-so101/requirements.txt`).

## Pipeline (Step 1 → Step 6)

```bash
# Step 1 — fetch the SO-101 model + smoke-test the Genesis scene.
python scripts/setup_so101_assets.py
python simulation/genesis_env.py --save-frame          # writes world_cam.png

# Step 2-3 — verify the VLA inference loop wiring (no GPU/sim needed).
python vla/inference.py --self-check

# Step 4 — generate synthetic demos, fine-tune SmolVLA, then run closed-loop.
python scripts/record_dataset.py --episodes 100 --repo-id so101/cube_pick
python dataset/lerobot_loader.py --repo-id so101/cube_pick \
    --dataset-root datasets/cube_pick --validate
python training/finetune.py smolvla --repo-id so101/cube_pick \
    --dataset-root datasets/cube_pick --steps 20000
python vla/inference.py \
    --checkpoint outputs/train/smolvla_cube_pick/checkpoints/last/pretrained_model \
    --repo-id so101/cube_pick --dataset-root datasets/cube_pick --episodes 10

# Step 5 — ROCm benchmark (CPU vs AMD GPU).
python benchmark/rocm_perf.py \
    --checkpoint outputs/train/smolvla_cube_pick/checkpoints/last/pretrained_model \
    --repo-id so101/cube_pick --dataset-root datasets/cube_pick --devices cpu cuda

# Step 6 — record the demo video.
python scripts/run_demo.py \
    --checkpoint outputs/train/smolvla_cube_pick/checkpoints/last/pretrained_model \
    --repo-id so101/cube_pick --dataset-root datasets/cube_pick --episodes 3 --save-video
```

## Repository layout

```
radeon-vla-so101/
├── README.md
├── requirements.txt
├── configs/task.yaml            # central task/scene/train/eval config
├── vla/
│   ├── agent.py                 # VLAAgent interface + SmolVLA/ACT/OpenVLA backends
│   └── inference.py             # load agent + closed-loop episode + --self-check
├── simulation/
│   ├── so101.py                 # SO-101 joints/gains/home/gripper/cameras
│   ├── genesis_env.py           # SO101PickPlaceEnv: reset()/step()/observe()
│   └── scripted_pick.py         # scripted top-down pick-place (demo generator)
├── dataset/lerobot_loader.py    # load / validate LeRobot datasets
├── training/finetune.py         # SmolVLA fine-tune (lerobot-train wrapper)
├── benchmark/rocm_perf.py       # CPU vs AMD GPU inference benchmark → results.json
├── scripts/
│   ├── setup_so101_assets.py    # fetch SO-101 URDF/MJCF/meshes
│   ├── record_dataset.py        # scripted SO-101 pick-place → LeRobot dataset
│   └── run_demo.py              # end-to-end demo → mp4
├── assets/robots/so101/         # fetched model (gitignored)
├── datasets/                    # recorded datasets (gitignored)
└── demo/                        # demo.mp4 (gitignored)
```

## Notes, scope & verification status

**What is done and statically verified (on the dev machine, macOS, no GPU):**
- All modules compile; the VLA inference loop (`vla/inference.py --self-check`) and
  the benchmark harness (`benchmark/rocm_perf.py --dry-run`) run green with no
  torch / lerobot / Genesis installed.
- Code targets the Genesis 1.1.x + LeRobot 0.6.0 APIs verified in the sibling
  `franka_fruit_pick` demo (same dataset creation, policy load, `predict_action`,
  and `lerobot-train` flags).

**What must be run/verified on the AMD Radeon (ROCm) machine:**
- `setup_so101_assets.py` (network fetch of the SO-101 model).
- The Genesis sim rollout, SmolVLA fine-tune, closed-loop eval, and the ROCm
  benchmark — none can run without a ROCm GPU + Genesis + LeRobot.
- **SO-101 numeric calibration:** PD gains, torque limits, home pose, gripper
  open/close values and grasp heights in `simulation/so101.py` /
  `simulation/scripted_pick.py` are conservative defaults marked `TODO` — tune
  them against the loaded model so the scripted pick reliably succeeds before
  recording a dataset.

**Scope decisions (per the project brief):**
- No from-scratch VLA training — SmolVLA is fine-tuned from `lerobot/smolvla_base`.
- No complex motion planner — a scripted top-down grasp + Genesis IK generates the
  demonstrations; the VLA output drives the arm directly.
- Colored cubes are Genesis `Box` primitives (color == label) — reliably graspable
  and dependency-free.
- Zero-shot pretrained SmolVLA will **not** succeed in this custom scene (sim/domain
  gap), so the pipeline records synthetic demos and fine-tunes before eval.

## Credits

- **SO-101 model** — [TheRobotStudio/SO-ARM100](https://github.com/TheRobotStudio/SO-ARM100)
  (`Simulation/SO101`); MuJoCo Menagerie `trs_so_arm100` as a fallback.
- **Genesis** — [Genesis-Embodied-AI](https://github.com/Genesis-Embodied-AI/Genesis).
- **SmolVLA + LeRobot** — [huggingface/lerobot](https://github.com/huggingface/lerobot).
- Structure/approach adapted from the sibling `franka_fruit_pick` demo and the AMD
  [Robot_synthetic_data_generation_workshop](https://github.com/PhysicalAI-AIM/Robot_synthetic_data_generation_workshop).
