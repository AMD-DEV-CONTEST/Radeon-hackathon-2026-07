# Technical Report: Humanoid Robot Soccer Policy Training on AMD Radeon GPU

## Track 3 — Physical AI Challenge: Robotics Simulation and Application Design based on AMD Radeon GPUs and ROCm

**Team**: [Team Name]
**Application Name**: Hierarchical Soccer Policy with Reward-Guided Kicking on AMD ROCm
**Submission Date**: August 2026

---

## 0. Submission Result (2026-08-06)

**Final deliverable: single-robot REAL KICK → GOAL** (nothing scripted).

The final film `acceptance/final_video/track3_final_20260806.mp4` (4:14, 1920×1080@30,
6-part structure with Chinese subtitles) demonstrates the full physical kick action chain:

```
walk to ball → wind-up → forward leg swing → FOOT CONTACTS BALL → ball pushed → GOAL
```

Canonical run (reproduced 4×, all scored, 0 falls):

| Metric | Value |
|--------|-------|
| Foot-ball contact step | `contact@116` (leg swing phase) |
| Goal step | `scored@144` (ball crosses goal line x=7.0) |
| Peak ball speed | **4.33 m/s** (pure physics momentum — `clip_actions=100.0`, no scripted ball velocity) |
| Falls | 0 (260 steps) |
| Render | 288 frames · 1920×1080 · 30fps · multi-camera (wide/close/follow/goal) |
| Reproducibility | 4 independent runs: contact 116–117 / scored 144–147 / 2.69–4.33 m/s |

AMD GPU/ROCm evidence captured live: `rocm-smi` (gfx1100, 96 CUs), `amd-smi`,
`torch 2.9.1+gitff65f5b`, `torch.version.hip = 7.2.53211`, GPU utilization reached 100%
during camera rendering. Reproduce with `scripts/render_kick_final.py` + `kick_params.json`.

The distributed multi-robot match system (§7) is a supporting experiment; the single-robot
real-kick path is the guaranteed submission.

---

## 1. Project Overview

### 1.1 Objective

Train humanoid robot soccer policies (balance, chase, shoot) using the Genesis physics
engine and ROCm PyTorch on AMD Radeon GPUs, then validate via distributed multi-robot matches
in Genesis — entirely on AMD hardware, with no NVIDIA dependencies.

Booster Robotics' official RL training frameworks (Booster Gym / Booster Train) depend on
NVIDIA Isaac Gym and Isaac Lab, which require CUDA. This project builds an alternative
training pipeline that runs **entirely on AMD Radeon GPUs**, proving that competitive
humanoid robot policies can be trained without NVIDIA hardware.

### 1.2 Key Contributions

1. **First AMD-GPU humanoid soccer training pipeline** — Genesis + ROCm PyTorch + rsl_rl
   as a complete Isaac Gym alternative, achieving 4,618 steps/s on AMD Radeon (51 GB VRAM)
2. **Reward function engineering for kicking behavior** — Identified and fixed the
   "ball contact punishment" bug (approach_ball hard-clamped → tanh soft clamp), added
   approach_angle and directed_contact rewards to shape contact direction, achieving
   1,358 goals in 500 iterations (830% improvement over v7)
3. **Hierarchical policy architecture** — Frozen t1_walk.pt (720→21) for locomotion +
   trainable high-level PPO (19→3) for soccer behavior, with curriculum-based action
   clip scheduling
4. **Floating-base dynamics fix** — 5 critical bugs in Genesis URDF loading, state
   reading, and termination logic identified and fixed
5. **Distributed multi-robot architecture** — Socket-coordinated multi-process system
   for multiple robots on a single AMD GPU, verified with ONNX inference.

### 1.3 Technical Stack

| Component | Technology | Role |
|-----------|-----------|-----|
| Physics simulation | Genesis 1.3.1 | GPU-accelerated, AMD Radeon compatible |
| Deep learning | PyTorch 2.9.1 (ROCm 7.2) | AMD GPU compute via HIP |
| RL algorithm | rsl_rl 5.4.2 (PPO) | On-policy RL training |
| Robot platform | Booster T1 (humanoid, 31 DoF) | 23-motor, 21-policy-joint |
| Multi-robot match validation | Genesis distributed | multi-robot soccer simulation |
| Cloud GPU | Anrui Cloud AMD GPU (51 GB VRAM) | JupyterLab + VNC |

---

## 2. System Architecture

### 2.1 Overall Pipeline

```
┌─────────────────────────────────────────────────────────┐
│                    Training Pipeline                      │
│                                                           │
│  ┌──────────────┐    ┌───────────────┐                   │
│  │  High-Level   │    │  Low-Level    │                   │
│  │  PPO Policy   │───▶│  Frozen Walk  │──▶ PD Control    │
│  │  (19→3 dims)  │    │  (720→21)     │    (50 Hz)        │
│  │  vx,vy,wz     │    │  t1_walk.pt   │                   │
│  └──────┬───────┘    └───────────────┘                   │
│         │                                                │
│  ┌──────▼──────────────────────────────────────────┐     │
│  │  Genesis Physics Engine (AMD Radeon GPU)         │     │
│  │  Floating-base T1 humanoid + soccer ball          │     │
│  └─────────────────────────────────────────────────┘     │
│                                                           │
│  Reward: approach_ball(tanh) + approach_angle(3)          │
│          + directed_contact(5) + ball_to_goal(8)           │
│          + ball_progress(10) + goal_scored(30)             │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│                Validation Pipeline                        │
│                                                           │
│  Trained .pt  ──▶  ONNX export  ──▶  Distributed matches  │
│  checkpoint                        Match (6 robots)       │
│                                    on AMD Radeon GPU      │
└──────────────────────────────────────────────────────────┘
```

### 2.2 Hierarchical Policy Design

| Level | Observation | Action | Frequency | Model |
|-------|------------|--------|-----------|-------|
| High-level | 19-dim (ball pos/vel, goal dir, proprioception) | 3-dim (vx, vy, wz) | 10 Hz | Trainable PPO |
| Low-level | 720-dim (10-frame proprioception history) | 21-dim (joint targets) | 50 Hz | Frozen t1_walk.pt |

The high-level policy observes ball position, velocity, and goal direction in body frame.
It outputs velocity commands (vx, vy, wz) that are injected into the frozen walking
model's observation. This design solves a fundamental problem: the original flat policy
(720-dim obs) had no ball information but was rewarded for approaching the ball.

### 2.3 19-dim Observation Space

| Index | Component | Dims | Description |
|-------|-----------|------|-------------|
| 0-2 | filtered_lin_vel | 3 | Robot velocity in body frame |
| 3-5 | filtered_ang_vel | 3 | Robot angular velocity in body frame |
| 6-7 | projected_gravity | 2 | Orientation indicator (xy) |
| 8-9 | ball_rel_body | 2 | Ball position relative to robot, body frame |
| 10-11 | ball_vel_body | 2 | Ball velocity in body frame |
| 12 | dist_to_ball | 1 | Euclidean distance to ball |
| 13-14 | goal_dir | 2 | Goal direction in body frame (normalized) |
| 15 | goal_dist | 1 | Distance to goal |
| 16-18 | last_hl_actions | 3 | Last velocity command [vx, vy, wz] |

---

## 3. Data Pipeline
### 3.1 Data Generation

This project does **not use external datasets**. All training data is generated on-the-fly
by the Genesis physics simulation:

| Data | Source | Purpose |
|------|--------|---------|
| `t1_walk.pt` | [booster_deploy](https://github.com/BoosterRobotics/booster_deploy) | Frozen low-level walking policy (720→21) |
| T1 URDF model | [booster_assets](https://github.com/BoosterRobotics/booster_assets) | Robot physics model for Genesis |
| Soccer field | `soccer_env_v4.py` | 14m × 9m RoboCup soccer field |
| Reward function | `reward.py` | Curriculum: balance → chase → shoot |
| Training configs | `configs/hierarchical_agent.yaml` | PPO hyperparameters, reward weights |

### 3.2 Training Data Flow

```
[Environment Setup]
  ├── Install ROCm PyTorch (pip install torch --index-url .../rocm6.2)
  ├── Install Genesis (pip install genesis-world)
  ├── Clone booster_deploy + booster_assets (provides t1_walk.pt + URDF)
  └── Clone project repository

[Data Generation → Training → Validation]
  Genesis physics (AMD Radeon GPU)
    ↓ real-time simulation data (24.6M steps)
  rsl_rl PPO training (2048 parallel environments)
    ↓ trained checkpoint (model_499.pt)
  ONNX export (raw MLP weight extraction, 182 KB)
    ↓ deployment-ready model
  Distributed multi-robot match validation (6 Genesis processes)
    ↓ match trajectory logs (JSON)
  Performance analysis + video rendering
```

---

## 4. Reward Function Design

### 4.1 The Ball Contact Problem

The original reward function had a critical flaw: `r_approach_ball` used a hard clamp
(`torch.clamp(prev_dist - dist, min=0.0)`). This meant:

- Robot approaches ball → distance decreases → **positive reward** ✓
- Robot contacts ball, ball bounces away → distance increases → **reward = 0** (clamped)

The robot learned to camp at 0.25m and never touch the ball. Two additional problems
compounded this:

1. **No approach angle reward** — the robot was rewarded for reaching the ball regardless
   of which direction it approached from. If it approached from the goal side, contact
   pushed the ball the wrong way.
2. **Weak ball_to_goal signal** — weight was only 3.0 vs approach_ball's 10.0, so
   "push ball toward goal" was a weaker signal than "walk toward ball."

### 4.2 Reward Function Fixes (v8)

| Change | Before | After | Rationale |
|--------|--------|-------|-----------|
| `approach_ball` | `torch.clamp(Δ, min=0.0)` | `torch.tanh(Δ)` | Soft clamp preserves weak gradient on bad contact |
| `approach_angle` (new) | — | weight: 3.0 | Reward approaching ball from goal-opposite side |
| `directed_contact` (new) | — | weight: 5.0 | Bonus for foot-near-ball WHILE ball moves toward goal |
| `ball_to_goal` | 3.0 | 8.0 | Make "push ball toward goal" signal comparable to "chase ball" |
| `hl_clip_lin` | 0.8 m/s | 1.2 m/s | Unlock higher walking speed for stronger ball contact |

### 4.3 Complete Reward Function (v8)

| Reward Term | Weight | Description |
|-------------|--------|-------------|
| upright | 0.5 | Torso upright indicator |
| alive | 0.0 | Removed (caused local optimum) |
| orientation | -1.0 | Penalize tilted orientation |
| approach_ball | 10.0 | Distance decrease to ball (tanh soft-clamped) |
| approach_angle | 3.0 | Dot product of ball direction and goal direction |
| ball_control | 2.0 | Close to ball (exp kernel) |
| ball_progress | 10.0 | Potential-based: ball-to-goal distance reduction |
| ball_contact | 1.0 | Foot within 0.15m of ball |
| directed_contact | 5.0 | Foot near ball AND ball moving toward goal |
| ball_to_goal | 8.0 | Ball velocity component toward goal |
| goal_scored | 30.0 | Ball crosses goal line (episode resets) |
| fall_penalty | -5.0 | Robot fallen |
| recovery_bonus | 3.0 | Robot recovered from fallen state |
| action_rate | -1.0 | Penalize jerky command changes |
| energy_penalty | -0.01 | Action squared sum |
| lin_vel_z | -0.5 | Penalize vertical oscillation |
| ang_vel_xy | -0.1 | Penalize roll/pitch rotation |

### 4.4 Approach Angle Reward

```python
def r_approach_angle(ball_rel_body, goal_dir_body):
    ball_dir = ball_rel_body / (norm(ball_rel_body) + 1e-6)
    return dot(ball_dir, goal_dir_body)
```

When the robot is between the ball and its own goal (approaching from behind the ball),
this returns +1. When it's in front of the ball (goal side), it returns -1. This shapes
the approach trajectory so that contact naturally pushes the ball toward the goal.

### 4.5 Directed Contact Reward

```python
def r_directed_contact(min_foot_dist, ball_vel_to_goal, contact_radius=0.20):
    in_contact = (min_foot_dist < contact_radius).float()
    good_direction = clamp(ball_vel_to_goal, min=0.0)
    return in_contact * good_direction
```

This only fires when both conditions are met: foot within contact radius AND ball has
positive velocity toward goal. The robot gets rewarded for *how* it touches, not just
*that* it touches.

---

## 5. Training Results

### 5.1 Training Configuration

| Parameter | Value |
|-----------|-------|
| RL algorithm | PPO (rsl_rl 5.4.2) |
| Parallel environments | 2,048 |
| Actor network | [256, 128, 64] (ELU) |
| Critic network | [256, 128, 64] (ELU) |
| Learning rate | 1e-3 (adaptive) |
| Entropy coefficient | 0.003 |
| Max iterations | 500 |
| Save interval | 50 |
| HL decimation | 5 (10 Hz high-level, 50 Hz low-level) |
| HL clip | lin=1.2 m/s, ang=1.2 rad/s |

### 5.2 v8 Training Results (500 Iterations)

| Metric | Start | End | Peak | Change |
|--------|-------|-----|------|--------|
| Mean reward | -24.44 | +93.07 | **+105.61** | ▲130 |
| Episode length | 76 | 220 | 235 | ▲144 |
| Action std | 1.0 | 0.08 | — | ✓ Stable |
| Goals total | 0 | **1,358** | — | First-time scoring |
| Goals per 1k steps | 0.49 | 0.17 | 0.49 | Active scoring |
| Mean dist to ball | 3.07m | 1.13m | — | 63% reduction |
| Falls | — | 0 | — | Zero falls |

### 5.3 v7 vs v8 Comparison

| Metric | v7 (old reward) | v8 (new reward) | Improvement |
|--------|----------------|-----------------|-------------|
| Peak reward | +21.69 | +105.61 | ▲387% |
| Total goals | 146 | 1,358 | ▲830% |
| Steps/s | ~847 | 4,618 | ▲446% |
| Total steps | 14.7M | 24.6M | ▲67% |
| Episode length | 225 | 220 | Comparable |
| Action std | 0.07 | 0.08 | Healthy exploration |

### 5.4 Reward Function Impact

The reward function changes had the most dramatic impact on goal-scoring behavior:

```
v7 (hard clamp, no angle/contact shaping):
  approach_ball: clamp(Δ, min=0) → robot camps at 0.25m, never touches ball
  ball_to_goal: weight 3.0 → too weak to overcome camping local optimum
  Result: 146 goals in 500 iterations (mostly lucky bounces)

v8 (tanh clamp + angle + directed contact):
  approach_ball: tanh(Δ) → weak negative gradient on bad contact
  approach_angle: dot(ball_dir, goal_dir) → robot learns to approach from behind
  directed_contact: in_contact × ball_vel_to_goal → rewards good kicks
  ball_to_goal: weight 8.0 → strong enough to dominate contact behavior
  Result: 1,358 goals in 500 iterations (9.3× improvement)
```

---

## 6. AMD Radeon GPU / ROCm Performance

### 6.1 Training Throughput

| Metric | Value |
|--------|-------|
| GPU | AMD Radeon Graphics (51.2 GB VRAM) |
| ROCm version | 7.2 |
| PyTorch | 2.9.1+gitff65f5b (ROCm build) |
| Peak throughput | **4,618 steps/s** |
| Average throughput | 4,305 steps/s |
| Total training steps | 24,576,000 |
| Training duration | 1h 35min |
| Iteration time | 11.5s avg |

### 6.2 GPU Utilization (612 samples, 10s interval)

| Metric | Min | Avg | Max |
|--------|-----|-----|-----|
| GPU utilization | 0% | 86% | 100% |
| VRAM used | 4,734 MB | 19,915 MB | 23,738 MB |
| VRAM total | 51,523 MB | 51,523 MB | 51,523 MB |
| Edge temperature | 27°C | 40°C | 52°C |
| Power draw | 12 W | 98 W | 191 W |

### 6.3 VRAM Breakdown

| Component | VRAM Usage |
|-----------|-----------|
| Genesis physics (2048 envs) | ~4.7 GB |
| PyTorch + rsl_rl training | ~2 GB |
| vLLM (Track 2, coexisting) | ~18 GB |
| Total peak | 23.7 GB / 51.5 GB (46%) |

### 6.4 Parallel Multi-Track GPU Sharing

Track 2 (Agentic AI vLLM serving) and Track 3 (RL training) ran simultaneously on the
same AMD Radeon GPU, demonstrating efficient GPU sharing:

```
AMD Radeon GPU (51.2 GB VRAM)
├── Track 3: Genesis + ROCm PyTorch training (~5 GB VRAM, 98% GPU util)
├── Track 2: vLLM inference server (~18 GB VRAM, 35% memory util)
└── Total: 46% VRAM usage, both tracks running concurrently
```

---

## 7. Distributed Multi-Robot Match Validation

### 7.1 Genesis ROCm Multi-Entity Crash

Genesis on AMD ROCm crashes with `hipErrorLaunchFailure` when two or more humanoid robots
with floating bases are loaded in the same scene (VRAM usage only 0.9 GB / 51.5 GB — not a
memory issue). This is a platform-level bug in Genesis + ROCm multi-articulated-body
collision handling.

### 7.2 Distributed Multi-Process Architecture

Each robot runs in its own Genesis process (proven stable with 1 robot). A socket-based
coordinator synchronizes state between processes at 50 Hz:

```
┌──────────────────────────────────────────────────┐
│           Match Coordinator (socket)              │
│  - 50Hz sync loop                                 │
│  - Broadcasts ball + robot positions to all       │
│  - Pairwise collision detection + push-back       │
│  - Structured JSON match log                       │
└──┬──────┬──────┬──────┬──────┬──────┬────────────┘
   │      │      │      │      │      │
   ▼      ▼      ▼      ▼      ▼      ▼
┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐
│RL   ││RL   ││RL   ││Rule││Rule││Rule│
│Att  ││Def  ││Keep ││Att ││Def ││Keep │
└─────┘└─────┘└─────┘└─────┘└─────┘└─────┘
  GPU     GPU    GPU    GPU    GPU    GPU
 (shared AMD Radeon, 6 processes)
```

### 7.3 Match Results

| Metric | Value |
|--------|-------|
| Match duration | 25.0s |
| Total steps logged | 1,240 |
| Robots | 6 (3 RL + 3 rule-based) |
| Collisions | 7 (in first 6.3s) |
| Ball displacement | 4.77m max (active play) |
| Zero GPU crashes | ✓ |

### 7.4 RL vs Rule-Based Behavior

Team A (RL) robots showed autonomous ball-chasing behavior:
- RL attacker reached ball distance of 0.43m (verified in match playback)
- RL robots maintained balance (pitch < 7° throughout)
- Ball was actively displaced during match playback (20m total displacement)

Team B (rule-based) robots showed simpler chase behavior:
- Rule attacker reached ball distance of 0.13m
- Less coordinated movement across the field

---

## 8. ONNX Model Export

### 8.1 Export Method

The ONNX model was exported via raw MLP weight extraction from the rsl_rl checkpoint:

```python
# Extract actor weights from checkpoint
ckpt = torch.load('model_499.pt')
sd = ckpt['actor_state_dict']

# Build standalone MLP (weights inlined)
mlp = nn.Sequential(
    nn.Linear(19, 256), nn.ELU(),
    nn.Linear(256, 128), nn.ELU(),
    nn.Linear(128, 64), nn.ELU(),
    nn.Linear(64, 3),
)
mlp.load_state_dict({k: sd[v] for k, v in mapping.items()})

# Export with weights inlined (not external .data file)
torch.onnx.export(mlp, dummy_obs, 'chase_v8_policy.onnx', opset_version=17)
```

### 8.2 ONNX Model Properties

| Property | Value |
|----------|-------|
| File | `models/chase_v8_policy.onnx` |
| Input | `obs` [batch, 19] |
| Output | `action` [batch, 3] (vx, vy, wz) |
| Opset | 17 |
| Parameters | 46,467 (19→256→128→64→3) |
| File size | 182 KB (weights inlined) |
| Architecture | Linear→ELU→Linear→ELU→Linear→ELU→Linear |

---

## 9. Floating-Base Dynamics Fix

### 9.1 Problem

The original Genesis simulation had the robot's floating base (6-DoF) locked — the
robot's trunk position never changed under gravity, making all prior training results
invalid. Five root-cause bugs were identified:

### 9.2 Five Bug Fixes

| # | Bug | Root Cause | Fix |
|---|-----|-----------|-----|
| 1 | Floating base lock | URDF `world_joint` commented out + `merge_fixed_links=True` | Uncomment + `merge_fixed_links=False` |
| 2 | 1-step termination | `base_euler` in degrees, `term_pitch` in radians (0.52° vs 30°) | Use degree values directly |
| 3 | Obs history misalignment | `_build_low_level_obs` updated history before physics step | Read `obs_buf` only, update after step |
| 4 | Conservative local optimum | `approach_ball=1` → standing still gives +34 reward | Curriculum + `approach_ball=10` |
| 5 | Action std explosion | `entropy_coef=0.01` → std=5.78, noise dominates | `entropy_coef=0.003` → std=0.07 |

---

## 10. Reproducibility

### 10.1 Environment Setup

```bash
# 1. Install ROCm PyTorch
pip install torch --index-url https://download.pytorch.org/whl/rocm6.2

# 2. Install dependencies
pip install genesis-world rsl_rl tensordict tensorboard imageio imageio-ffmpeg
pip install 'numpy<2.0' pyyaml scipy

# 3. Clone booster repos (provides t1_walk.pt + URDF)
cd /workspace
git clone https://github.com/BoosterRobotics/booster_deploy.git
git clone https://github.com/BoosterRobotics/booster_assets.git
cd booster_assets && pip install -e .

# 4. Clone project
git clone <submission-repo-url>  # filled in at submission time
```

### 10.2 Training

```bash
# Full training (2048 envs, 500 iterations, ~1.5 hours)
python train_hierarchical.py --max_iterations 500 --num_envs 2048

# Quick test (256 envs, 100 iterations, ~5 minutes)
python train_hierarchical.py --num_envs 256 --max_iterations 100
```

### 10.3 Validation

```bash
# Render single-robot demo
python archive/render_hierarchical.py --steps 300

# Export ONNX
python export_onnx_mlp.py --model runs/.../model_499.pt --output models/chase_v8_policy.onnx

```

---

## 11. Known Limitations

1. **Close-range ball control**: When the ball is within ~2m, the velocity-command
   interface cannot express fine motor adjustments needed for ball possession. A residual
   joint-level policy would be needed for dribbling and precise shooting.

2. **Genesis ROCm multi-entity crash**: Genesis on AMD ROCm crashes with
   `hipErrorLaunchFailure` when two or more robot URDF entities are loaded in the same
   scene. The distributed multi-process architecture works around this but adds
   communication overhead.

3. **Match rendering**: The distributed match produces JSON trajectory data, not
   real-time 3D video. A 2D top-down animation renderer (`render_match.py`) visualizes
   the match from trajectory logs.

---

## 12. Team Members

| Member | Role | Contribution |
|--------|------|-------------|
| [Member 1] | Team Lead | Training pipeline, RL policy design, reward engineering |
| [Member 2] | Simulation Engineer | Genesis environment, floating-base fix |
| [Member 3] | Deployment Engineer | ONNX export, multi-robot system, benchmark collection |

---

## 13. RoboCup 2026 Background

RoboCup 2026 (June 30 – July 6, Incheon, South Korea) marked the first large-scale
humanoid robot soccer match. Most participating teams' RL training relies on NVIDIA CUDA
(Isaac Gym/Lab). This project is the first to train humanoid soccer policies on AMD Radeon
GPUs, providing a viable path for non-NVIDIA users.

---

## 14. Conclusion

This project demonstrates the first complete humanoid robot soccer training pipeline on
AMD Radeon GPUs using Genesis + ROCm PyTorch. The reward function engineering was the
key breakthrough: by replacing the hard clamp with tanh soft clamp and adding
approach_angle + directed_contact rewards, the robot learned to approach the ball from
the correct direction and make contact that pushes the ball toward the goal, achieving
1,358 goals in 500 iterations (830% improvement over the previous best).

The distributed multi-process architecture extends the pipeline to multiple robots on a
single AMD GPU, with multi-robot coordination as future work. All engineering deliverables —
benchmark data, ONNX deployment model, demo videos, and reproducible code — are archived
on GitHub.

---

## 15. 2026-08-06 Final Update (Submission Day)

### 15.1 Single-Robot Real Kick → Goal (Canonical Run, 2026-08-06)

Canonical run of `scripts/render_kick_final.py` (`kick_params.json`):

| Metric | Value |
|--------|-------|
| Foot-ball contact step | `contact@116` (forward leg swing) |
| Goal step | `scored@144` (ball crosses goal line) |
| Peak ball speed | **4.33 m/s** (physics momentum, `clip_actions=100.0`) |
| Falls | 0 (260 steps) |
| Render | 288 frames · 1920×1080 · 30fps · multi-camera |
| Reproducibility | 4 independent runs, all scored, 0 falls |

Raw evidence: `kick_final/result.json`, time-stamped run log, `kick_final/kick_final.mp4`.

### 15.2 Field Render Fix (Blue-Ground Resolved)

Root cause: semi-transparent robot links (19/25 at 0.3 alpha) × `plane_reflection=True`
reflection pass made the near-camera ground render blue after physics steps. Fix:
`plane_reflection: True → False` (pure rendering option; V1/V2 same-color check confirmed
no visual impact on the field). Verified: full multi-robot env one-frame green ratio **0.541** (acceptance > 0.40);
re-rendered rule-walk video — **100/100 frames green (0.542–0.546)**, 4 kicks, ball
displacement 12.75m.

### 15.3 Final Film

`acceptance/final_video/track3_final_20260806.mp4` — 87.7 s, 1920×1080@30fps, H.264,
6-part structure, English slides + English subtitles + Microsoft neural TTS narration;
content spot-check: real kick action, no black frames, no falls.

### 15.4 Submission Note

The single-robot real-kick line is the primary submission path; multi-robot neural-walk
stability remains a documented known limitation (§11). Full task/lane records in `SPEC.md`.
