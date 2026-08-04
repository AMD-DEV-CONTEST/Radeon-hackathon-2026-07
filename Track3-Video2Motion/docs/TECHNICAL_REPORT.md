# Video2Motion — Technical Report

**One ordinary video in, a deployable humanoid control policy out — end to end on AMD ROCm**

AMD AI DevMaster Hackathon 2026 · Track 3, Physical AI

---

## Abstract

A user uploads an ordinary video of a person moving. The system runs pose
estimation, motion retargeting, reinforcement learning and a three-layer
cross-simulator validation, and produces a control policy that can be sent
straight to a Unitree G1 over DDS. There is a web UI for the whole thing; no
code required.

The entire pipeline runs on a **Radeon Pro W7900 (gfx1100) with ROCm 7.2.1**.
This is not a port that swaps a backend flag: the mainstream stacks in this
field — Isaac Lab, Isaac Sim, MuJoCo Warp, unitree_rl_mjlab, and BeyondMimic's
own implementation — are **all CUDA-only**. We had to re-select the stack and
rebuild the missing pieces.

**Headline result**: the trained policy passes all three validation layers.
Layer 3 runs on **Unitree's own simulator, Unitree's own G1 model, over DDS** —
the same code path as real hardware.

| Layer | Physics | Robot model | Inference | Interface | Motion completed | Body position error |
|---|---|---|---|---|---|---|
| Zero-action baseline | — | — | — | — | 44/156 (28.2%) | 0.0772 m |
| **1** | MuJoCo MJX (JAX/GPU) | Playground G1 | brax network | direct memory | **156/156 (100%)** | **0.0269 m** |
| **2** | MuJoCo native C (CPU) | Playground G1 | **pure NumPy** | direct memory | **156/156 (100%)** | **0.0273 m** |
| **3** | MuJoCo native C | **Unitree official G1** | pure NumPy | **DDS** | **156/156 (100%)** | 4–5° joint error |

---

## 1. Problem and product framing

### 1.1 What we are solving

Teaching a humanoid a new motion currently has three barriers:

1. you need a motion-capture rig or an existing mocap dataset;
2. you need someone who knows RL to tune rewards and hyperparameters per motion;
3. after training you still have to survive sim2real, which fails often.

Our goal is to compress this to: **upload a video, wait, get a usable policy.**

### 1.2 A deliberate decision: no single unified policy

The obvious idea is to train one policy that can do every motion. We
**deliberately do not**, because it conflicts with the product: the user
uploads an *arbitrary* video, so the motion cannot be enumerated in the
training set ahead of time.

What we want instead is **one hyperparameter set under which most motions
converge**. Each motion gets its own policy, but **no human tuning per motion**.
These two things are orthogonal and easy to confuse:

| | One policy, many motions | One hyperparameter set, many motions |
|---|---|---|
| Artifact | 1 checkpoint | N checkpoints |
| Adding a motion | retrain everything | independent, no interference |
| Fit for us | ❌ conflicts with "arbitrary video" | ✅ the prerequisite for automation |

BeyondMimic takes the same "per-motion policy, shared hyperparameters" route.
We follow its methodology but the implementation is independent (see §2).

---

## 2. Platform constraints: why the stack had to be rebuilt

### 2.1 Every mainstream option is unavailable on AMD

| Option | Blocker |
|---|---|
| Isaac Lab / Isaac Sim | closed source, CUDA-only |
| MuJoCo Warp | depends on NVIDIA Warp, CUDA-only |
| unitree_rl_mjlab | depends on MuJoCo Warp |
| BeyondMimic (official) | requires Isaac Lab 2.1.0 + Isaac Sim 4.5.0 |
| BeyondMimic (mjlab reproduction) | depends on MuJoCo-Warp |

**The only viable massively-parallel simulation path is MuJoCo MJX (JAX
backend)**, with JAX-ROCm and Brax PPO. That means BeyondMimic's algorithm had
to be **reimplemented on MJX from its source**, matching reward formulas,
weights, stds and termination thresholds term by term.

### 2.2 Two hard limits measured on gfx1100

**(1) XLA graph-size ceiling.** When

```
num_minibatches × num_updates_per_batch > 32
```

XLA segfaults during code generation with no Python-level exception. We ruled
out VRAM (28 MB used of 48 GB), `pmap` itself, and the environment
implementation — it is a compiler limit on the gfx1100 backend. We use `16 × 2`.

**(2) brax is incompatible with JAX 0.11.** brax 0.14.2 calls
`jax.device_put_replicated`, removed in JAX 0.11 with the pmap migration.
NVIDIA users can downgrade JAX; **AMD users cannot** — the JAX version is
pinned by `jax-rocm7-plugin`. A compatibility shim is required, injected
*before* `import brax`.

Both are written up as upstream contributions.

---

## 3. System design

```
  user video (mp4)
       │
       ▼  GVHMR                        62 s for a 3.2 s clip (AMD GPU)
  SMPL-X body motion
       │
       ▼  GMR (CPU / inverse kinematics)
  G1 29-DoF joint trajectory
       │
       ▼  gmr_to_mjx.py + motion_prep.py
  MJX motion file (14 body poses and velocities)
       │
       ▼  Brax PPO on MJX             357 min · 4096 envs · 371M steps
  policy weights
       │
       ▼  pure-NumPy export           251,066 parameters, zero JAX dependency
       │
       ├──▶ Layer 2  native MuJoCo
       └──▶ Layer 3  unitree_mujoco + DDS ── same code path as real hardware
```

### 3.1 Training environment: BeyondMimic's recipe ported to MJX

**Why tracking upper-body joint angles was not enough**

Our first design inherited MuJoCo Playground's G1 Joystick environment, pinned
the velocity command to zero to reuse its standing ability, and added an
upper-body joint-angle tracking reward. The metrics looked great:
"500/500 steps without falling, 19.66° upper-body tracking error". But in the
video the robot staggered and the arms barely moved.

The cause was **two bad success criteria**:

- *"didn't fall"* — standing still scores perfectly;
- *"joint-angle error"* — weakly correlated with visual similarity, and after
  a fall the arms keep moving, so the error stays small anyway.

More fundamentally, **the reward structure made "stand still" optimal**: the
episode only terminated on a fall, so not falling → full episode length →
high return, while tracking was a small fraction of the per-step reward.

**BeyondMimic does something structurally different**

| | First design | BeyondMimic recipe |
|---|---|---|
| Tracking target | 14 upper-body **joint angles** | 3-D **position / orientation / linear & angular velocity of 14 body links** + root anchor |
| Lower body | pose regularisation only | tracked as well |
| **Termination** | only on falling | **as soon as tracking error exceeds a threshold** |
| Reset | always standing pose, frame 0 | **RSI**: full state from a random frame of the reference |
| Reward | leftover joystick terms + 2 custom | 6 tracking + 3 penalty terms, nothing else |

**Rewards, matched term by term** against `tracking_env_cfg.py`
(all of the form `exp(−error/std²)`):

| Term | Weight | std |
|---|---|---|
| `motion_global_anchor_pos` | 0.5 | 0.30 |
| `motion_global_anchor_ori` | 0.5 | 0.40 |
| `motion_body_pos` | 1.0 | 0.30 |
| `motion_body_ori` | 1.0 | 0.40 |
| `motion_body_lin_vel` | 1.0 | 1.00 |
| `motion_body_ang_vel` | 1.0 | 3.14 |
| `action_rate_l2` | −0.1 | — |
| `joint_limit` | −10.0 | — |

Termination: `anchor_z > 0.25 m`, anchor orientation error > 0.8, any of the
four end effectors `z > 0.25 m`, or timeout.

### 3.2 Observation design forced by deployment

Unitree's `LowState` provides exactly four things:

```
motor_state[i].q        29 joint angles
motor_state[i].dq       29 joint velocities
imu_state.quaternion    pelvis orientation
imu_state.gyroscope     pelvis angular rate
```

There is **no torso linear velocity** (the IMU gives orientation and angular
rate only) and **no world position** (the robot has no global localisation).

Two observation terms therefore had to be removed, or the policy would be
untrainable-to-deploy:

| Term | Why removed | Cost |
|---|---|---|
| torso linear velocity | not provided by the IMU | controlled experiment: same policy, same simulator, only zeroing this term dropped survival from 500/500 to 190/500 — a retrain was mandatory |
| `anchor_pos_b` | requires torso world position | one retrain |

Both moved into the critic — an **asymmetric actor-critic**: the value network
may use privileged information during training, the policy may not. BeyondMimic
ships the same idea as `Tracking-Flat-G1-Wo-State-Estimation-v0`.

Final policy observation, **154 dimensions**:

```
ref joint pos+vel 58 | anchor_ori_b 6 | gyro 3 | joint pos 29 | joint vel 29 | last action 29
```

**This decision has to be made before training** — trimming dimensions
afterwards means retraining.

### 3.3 A frame mismatch that must be handled

The policy is trained in the **torso_link** frame (Playground's `gyro_torso` /
`orientation_torso` sensors), but the G1's IMU sits on the **pelvis**, with
three waist joints in between. The moment the waist moves, pelvis orientation
is not torso orientation.

The fix uses only data we already have: put the pelvis orientation and the
measured joint angles into a kinematics-only MuJoCo model, run `mj_forward`,
and read the torso pose out; use `mj_objectVelocity` for the angular rate.
**No extra sensor is required**, so this remains an SDK-only deployment.

Measured accuracy: orientation error **0.0000°**, angular-rate error
0.031 rad/s (~3%).

### 3.4 Deployment

The policy is exported as a pure-NumPy forward pass (**251,066 parameters**,
4-layer MLP with swish and a tanh-squashed mean) with **no JAX dependency**.
The same weights run in native MuJoCo, in unitree_mujoco, and on the robot's
onboard computer.

---

## 4. The three validation layers

A training curve alone does not show a policy is usable. We built three
progressive layers where **each one swaps exactly one thing**, so a failure can
be localised.

| Layer | What it swaps | What passing proves |
|---|---|---|
| 1 | — | training converged (**and nothing more**) |
| 2 | physics engine + inference stack | the policy is standalone numbers, not tied to JAX/MJX |
| 3 | robot model + transport + information limits | the real-hardware code path works |

**"It's all MuJoCo" is not true.** MJX is a *reimplementation* of the physics in
JAX so that thousands of environments can run in parallel on a GPU — solver,
contact handling and integration are different code.

Layer 3 swaps three substantial things:

**(1) Unitree's official G1 model** — different dynamics:

| Parameter | Unitree official | Playground | Difference |
|---|---|---|---|
| Joint damping | 0.05 uniform | 0.2 – 2.0 | **up to 40×** |
| Armature | 0.01 uniform | 0.0036 – 0.0251 | ~3× |
| Total mass | 35.11 kg | 33.34 kg | +5% |
| Actuator | `motor`, `ctrl` is **torque** ±88 N·m | `position`, `ctrl` is **angle** ±2.5 rad | different semantics |
| Collision geometry | whole body | feet only | — |

**(2) DDS transport** — Unitree's `LowState`/`LowCmd`, with real timing.

**(3) Information limits** — only the four sensor fields above.

Full reasoning in.

---

## 5. The hard part: porting BeyondMimic to MJX

The port surfaced **8 bugs**; the full trail is in. Two are worth repeating.

### 5.1 Root cause: Playground's auto-reset does not restore `info`

The first seven were genuine bugs, but after fixing them training **still
degraded monotonically** — across three runs (61M / 61M / 51M steps), the
*untrained* network was the best one.

**The decisive clue came from an ablation:**

| Group | Configuration | `ep_len` trend |
|---|---|---|
| Baseline | penalties on, entropy 1e-3 | 36 → 19.4 |
| A | both penalties off | 36 → 22.4 |
| B | penalties off + zero entropy | 36 → 20.9 |
| C | penalties on + zero entropy | 36 → 22.5 |

**Three very different configurations produced nearly identical curves.** That
means the degradation is independent of the reward composition, so the cause
must be something *all* groups share.

Playground's `BraxAutoResetWrapper` docstring says it outright:

> If `full_reset` is disabled (default):
>   * the environment will reset to a cached first state.
>   * **only data and obs are reset, not the environment info.**

Our reference frame index lives in `info["motion_idx"]`. So after the first
episode ends, **the robot's physical state returns to the start while the
reference index keeps advancing** — permanently desynchronised. Combined with
the `motion_idx >= T−1` termination, every subsequent sample is a 1-step
fragment. PPO was training on garbage from the beginning.

The fix is one boolean:

```python
wrap_env_fn=functools.partial(wrapper.wrap_for_brax_training, full_reset=True)
```

Same code, same hyperparameters, only this value changed:

| step | reward | `ep_len` | body_pos |
|---|---|---|---|
| 0 | 129.39 | 36.0 | 0.0993 m |
| 12M | 223.50 | 56.6 | 0.0842 m |
| 30M | **311.04** | **76.9** | **0.0773 m** |

### 5.2 The motion was physically unreachable

This one is unrelated to reward design, yet on its own it prevents the arms
from moving.

At steady state a position actuator gives `q ≈ ctrl`, and
`ctrl = default_pose + action × action_scale`. brax's `NormalTanhDistribution`
squashes actions into **[−1, 1]**, so the reachable range is exactly
`default_pose ± action_scale`.

Measured peak deviation required by the references:

| Motion | Peak requirement | `action_scale=0.5` provides | Shortfall |
|---|---|---|---|
| Salute | right elbow **1.709 rad (98°)** | 0.5 rad (28.6°) | **3.4×** |
| Tennis | shoulder roll **2.051 rad (118°)** | 0.5 rad | **4.1×** |

For the tennis motion **24% of upper-body targets are unreachable**. No amount
of training fixes that.

BeyondMimic avoids this because rsl_rl uses an unbounded Gaussian with no
action clipping. brax has the tanh, so reachability is our responsibility. The
fix is to make targets relative to the **reference pose**:

```python
motor_targets = ref_joint_pos[t] + action * action_scale
```

The policy then only outputs a *correction*, and reachability holds by
construction.

### 5.3 How to validate a reward function

Set the state exactly to a frame of the reference. **All six tracking rewards
must read 1.0000.** Any deviation means a frame, reference-point or unit
convention is still wrong — and in such an environment no policy can score.

This check should be run the same day the reward function is written; it is far
cheaper than reading curves afterwards. It caught two convention errors for us:
`cvel`'s linear component is measured at `subtree_com`, not the body origin
(1.0 m/s error at the wrists), and a free joint's `qvel[3:6]` is the **body
frame** angular rate, not the world frame (velocity rewards underflowed to
exactly zero).

---

## 6. Two findings from layer 3

### 6.1 unitree_mujoco computes PD inside the DDS callback

`unitree_sdk2py_bridge.py` computes the torque inside `LowCmdHandler` (a DDS
callback, ~50 Hz) and writes it into `mj_data.ctrl`. Between two commands that
torque is held **constant** for 20 ms.

| Context | PD loop rate |
|---|---|
| Training (position actuator) | MuJoCo recomputes every substep → **500 Hz** |
| Real robot (motor driver firmware) | **1–2 kHz** |
| unitree_mujoco bridge | **50 Hz zero-order hold** |

Same policy, same model, only this changed:

| PD loop | Survival (max 500) |
|---|---|
| 50 Hz ZOH, kd = 2 / 5 / 10 | 18 / 24 / 18 ❌ |
| 200 Hz substep loop | **500** ✅ |

**More damping does not help** — the problem is sample rate, not damping.
Moving the PD into the simulation loop fixes it immediately. This is a
simulator artifact; a real motor driver does not behave this way. Submitted as
a PR to `unitreerobotics/unitree_mujoco`.

### 6.2 The initial pose must be the motion's first frame

Our first layer-3 run fell at step 31. It was not the policy: unitree_mujoco
starts from a generic standing keyframe that differs from the motion's first
frame by **0.624 rad (36°)**, with a 2.9 cm height difference. The policy's RSI
training perturbation is only ±0.1 rad, so it began in a state it had never
seen.

Starting from the reference's first frame gives 156/156 immediately. This is
also what a real deployment does — the robot is moved into the starting pose
before the policy takes over.

> Before blaming the environment we validated our own new torso forward
> kinematics (orientation error 0.0000°) to rule out the new code first.

---

## 7. Performance

| Stage | Time | Device |
|---|---|---|
| GVHMR preprocessing (YOLO + ViTPose + HMR2) | 62.1 s | AMD GPU |
| GVHMR inference | 0.58 s | AMD GPU |
| GMR retargeting | ~1 min | CPU / IK |
| Format conversion + body pose/velocity derivation | < 1 s | CPU |
| **Reinforcement learning** | **357.5 min** (371M steps) | AMD GPU |
| Weight export | < 1 s | CPU |
| Three-layer validation | ~3 min | AMD GPU |

Training throughput: **17,326 env-steps/s** (4096 parallel envs, one W7900).

**Convergence**: 100% motion completion is reached at roughly **112M steps
(2 hours)**; the remaining time buys smoothness — error drops from 0.0466 m to
0.0269 m.

---

## 8. Web interface

A four-step Gradio wizard; no code required:

1. **Extract motion** — name the project; every downstream file inherits it
2. **Retarget to G1** — produces a kinematic replay video
3. **Train** — user-chosen budget (no upper limit), four live curves, stoppable
   mid-run, configurable checkpoint interval, all checkpoints downloadable
4. **Simulate** — reference and policy rendered side by side

The backend wraps three **mutually incompatible** Python environments behind
one interface:

| venv | Key dependencies | Must not contain |
|---|---|---|
| `gvhmr_env` | PyTorch 2.9.1+rocm, pytorch3d | jax |
| `GMR/gmr` | retargeting dependencies | — |
| `mjx` | JAX 0.11, MuJoCo, MJX, brax | torch |

They cannot coexist in one interpreter, so every stage runs as a subprocess and
they exchange data through files. This constraint also dictates the Docker
layering.

---

## 9. Upstream contributions

| # | Project | Contribution |
|---|---|---|
| 1 | `unitreerobotics/unitree_mujoco` | Move PD out of the DDS callback into the simulation loop (code + quantified data) |
| 2 | `unitreerobotics/unitree_mujoco` | Headless recording variant (EGL offscreen, no X11) |
| 3 | `google-deepmind/mujoco_playground` | Document/warn that auto-reset does not restore `info` |
| 4 | `google-deepmind/mujoco_playground` | `impl="jax"` necessity on AMD; better error message |
| 5 | `google/brax` | Compatibility for `device_put_replicated` removed in JAX 0.11 |
| 6 | ROCm ecosystem | Reproduction and workaround for the gfx1100 XLA graph-size limit |
| 7 | `zju3dv/GVHMR` | Full AMD/ROCm adaptation path; warning about filename-keyed cache reuse |

---

## 10. Limitations and next steps

**Limitations**

- Small motion library; the "one hyperparameter set covers most motions" claim
  needs more motions to support it.
- Lower-body tracking is in the reward, but motions requiring centre-of-mass
  travel (jumping, walking) are unvalidated.
- Six hours per motion is still long for an interactive product.
- The web UI does not survive a disconnect during a long training run (the
  training process itself keeps going and checkpoints keep being written, but
  the log stream breaks).

**Next steps**

- Expand the motion library (e.g. LAFAN1) and quantify hyperparameter coverage.
- Pretrained base + per-motion fine-tuning, to cut 6 hours to ~20 minutes.
- Domain randomisation and communication-delay modelling to harden for hardware.
- Docker packaging. **Note**: GVHMR depends on SMPL/SMPL-X, which are
  registration-gated and whose licence forbids redistribution — they cannot be
  baked into a public image; users must download them themselves.

**On real hardware**: contest FAQ Q66/Q69 states all work must be done in the
cloud and real-robot results do not count towards scoring. All of our layer-3
validation runs in the cloud on `unitree_mujoco`. `deploy_track.py` shares the
same DDS interface and the same NumPy weights as a real deployment — only the
network interface name changes — but that remains personal learning, not a
contest deliverable.

---

## Appendix: document index

| Document | Contents |
|---|---|
| [`../README.md`](../README.md) | Overview, setup, usage, code attribution |
| [`ALGORITHM.md`](ALGORITHM.md) | How the method evolved; differences from BeyondMimic |
| [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) | Every failure encountered, including the three that fail silently |
| [`../docker/DOCKER.md`](../docker/DOCKER.md) | Image build; why no prebuilt image is published |
| [`../scripts/`](../scripts/) | Setup, verification and end-to-end pipeline scripts |
