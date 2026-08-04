# Video2Motion

**One ordinary video in, a deployable humanoid control policy out — end to end on AMD ROCm**

[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![ROCm](https://img.shields.io/badge/ROCm-7.2.1-red)](https://rocm.docs.amd.com/)
[![GPU](https://img.shields.io/badge/GPU-Radeon%20Pro%20W7900-ED1C24)](https://www.amd.com/)
[![JAX](https://img.shields.io/badge/JAX-0.11%20(rocm)-orange)](https://github.com/jax-ml/jax)

AMD AI DevMaster Hackathon 2026 · Track 3, Physical AI

| Document | |
|---|---|
| [Technical report](docs/TECHNICAL_REPORT.md) | architecture, results, AMD GPU utilisation |
| [Algorithm design](docs/ALGORITHM.md) | how the method evolved; differences from BeyondMimic |
| [Reproduction](#5-installation-and-usage) | step-by-step setup and verification |
| [Docker](docker/DOCKER.md) | image build, and why we do not ship a prebuilt one |
| [Chinese docs](docs/zh/) | supplementary material (中文) |

---

## 1. Overview

### The problem

Teaching a humanoid a new motion currently requires a motion-capture rig, an RL
engineer to tune rewards per motion, and a sim2real process that fails often.
We compress this to: **upload a video, wait, get a usable policy** — through a
web UI, with no code.

```
  user video (mp4)
       │
       ▼  GVHMR                        62 s for a 3.2 s clip     AMD GPU
  SMPL-X body motion
       │
       ▼  GMR                          inverse kinematics        CPU
  G1 29-DoF joint trajectory
       │
       ▼  Brax PPO on MuJoCo MJX       357 min · 4096 envs       AMD GPU
  control policy
       │
       ▼  pure-NumPy export            251,066 params, no JAX
       │
       └──▶ DDS ──▶ unitree_mujoco / real Unitree G1
```

### Why this is not a trivial port

Every mainstream stack in this field is **CUDA-only**: Isaac Lab, Isaac Sim,
MuJoCo Warp, unitree_rl_mjlab, and BeyondMimic's own implementation (plus its
mjlab reproduction). The only viable massively-parallel path on AMD is
**MuJoCo MJX with JAX-ROCm**, which meant reimplementing the tracking algorithm
from source rather than swapping a backend flag.

### The key result

The trained policy passes three progressive validation layers. Layer 3 runs on
**Unitree's own simulator, Unitree's own G1 model, over DDS** — the same code
path as real hardware.

| Layer | Physics | Robot model | Inference | Interface | Motion completed | Body position error |
|---|---|---|---|---|---|---|
| Zero-action baseline | — | — | — | — | 44/156 (28.2%) | 0.0772 m |
| **1** | MuJoCo MJX (JAX/GPU) | Playground G1 | brax network | direct memory | **156/156 (100%)** | **0.0269 m** |
| **2** | MuJoCo native C (CPU) | Playground G1 | **pure NumPy** | direct memory | **156/156 (100%)** | **0.0273 m** |
| **3** | MuJoCo native C | **Unitree official G1** | pure NumPy | **DDS** | **156/156 (100%)** | 4–5° joint error |

Each layer swaps exactly one group of components, so a failure can be
localised. "It is all MuJoCo" is not accurate — MJX is a *reimplementation* of
the physics in JAX, and layer 3 additionally changes the robot model (joint
damping differs by up to **40×**), the transport, and what information the
policy is allowed to see. See
[`三层验证为什么这么设计.md`](docs/zh/三层验证为什么这么设计.md).

### Performance

| Stage | Time | Device |
|---|---|---|
| GVHMR preprocessing (YOLO + ViTPose + HMR2) | 62.1 s | AMD GPU |
| GVHMR inference | 0.58 s | AMD GPU |
| GMR retargeting | ~1 min | CPU / IK |
| **Reinforcement learning** | **357.5 min** (371M steps) | AMD GPU |
| Weight export | < 1 s | CPU |
| Three-layer validation | ~3 min | AMD GPU |

Training throughput **17,326 env-steps/s** (4096 parallel envs, one W7900).
100% motion completion is reached at about **112M steps (2 hours)**; the rest
buys smoothness.

### Data

There is no training dataset in the usual sense — **the input is a single video
the user records**, and the reference motion is derived from it at runtime.

| Artifact | Source | Size |
|---|---|---|
| Input video | recorded by the user (this demo: a 3.17 s, 1280×720, 30 fps salute) | 1.9 MB |
| Reference motion | derived at runtime by GVHMR → GMR → `motion_prep.py`; 157 frames at 50 fps, 14 tracked body links | 1.2 MB |
| Training samples | generated online by the simulator; 371M environment steps for this policy | — |
| Pretrained weights used | GVHMR (HMR2, ViTPose, YOLO) and SMPL/SMPL-X body models, all from upstream | ~8 GB |

SMPL and SMPL-X are registration-gated and cannot be redistributed; see §5.4.

### Stack

| Layer | Component |
|---|---|
| Hardware | AMD Radeon Pro W7900 (gfx1100, 48 GB) |
| Compute | ROCm 7.2.1 · JAX 0.11 (jax-rocm7-plugin) · PyTorch 2.9.1+rocm |
| Simulation | MuJoCo MJX · MuJoCo Playground |
| RL | Brax PPO, asymmetric actor-critic |
| Video → human | GVHMR (SMPL-X) |
| Retargeting | GMR (General Motion Retargeting) |
| Deployment | unitree_sdk2_python · unitree_mujoco · CycloneDDS |
| Web UI | Gradio |

---

## 2. Development process

### 2.1 Key decisions

**One hyperparameter set, not one unified policy.** The user uploads an
*arbitrary* video, so the motion cannot be enumerated in advance. We want each
motion to get its own policy but with **no per-motion human tuning**. These are
orthogonal axes and easy to conflate.

**Rebuild on MJX rather than wait for CUDA parity.** MJX was the only backend
that could run thousands of parallel environments on this hardware.

**Design the observation around deployment before training.** Unitree's
`LowState` provides only joint angles/velocities and pelvis IMU — no torso
linear velocity, no world position. Both were removed from the policy
observation and moved into the critic (asymmetric actor-critic). Doing this
after training would mean retraining.

**Validate in three layers, one variable each.** This is what let us localise a
bug in Unitree's own bridge instead of blaming our policy.

### 2.2 What was hard

**The metrics lied.** Our first design scored "500/500 steps without falling,
19.66° tracking error" while the robot staggered and barely moved its arms.
Both criteria are bad: *not falling* is achieved by standing still, and
*joint-angle error* correlates poorly with visual similarity. The reward
structure made standing still optimal, because the episode only ended on a
fall.

**Two independent bugs masked each other.** Even with a corrected reward, the
arms could not physically reach: brax's tanh bounds actions to [−1, 1], so a
position actuator can only reach `default_pose ± action_scale`. The tennis
reference needed **2.051 rad (118°)** where 0.5 rad was available — **24% of
upper-body targets were unreachable**. Fixing either bug alone shows no
improvement.

**The real root cause was one boolean in a wrapper.** After fixing seven
genuine bugs, training still degraded monotonically — the *untrained* network
was the best one. The decisive clue was an ablation where three very different
configurations (penalties off / entropy off / both off) produced nearly
identical curves, which means the cause is something they all share.
Playground's `BraxAutoResetWrapper` documents that on auto-reset **only `data`
and `obs` are restored, not `info`** — and our reference frame index lives in
`info`. Every episode after the first was trained on desynchronised garbage.
`full_reset=True` fixed it.

**A 50 Hz zero-order hold in Unitree's bridge.** `unitree_sdk2py_bridge.py`
computes the PD law inside the DDS callback, so the torque is held constant for
20 ms. Training uses 500 Hz (MuJoCo recomputes every substep) and real motor
drivers run at 1–2 kHz. With a stiff PD this is unstable by construction:
18 steps to failure, and **raising `kd` does not help** (2/5/10 → 18/24/18).
Moving the PD into the simulation loop gives 500/500.

Full trails: [`BeyondMimic移植记录.md`](docs/zh/BeyondMimic移植记录.md).

### 2.3 Platform findings (AMD-specific)

| Finding | Detail |
|---|---|
| **XLA graph-size ceiling on gfx1100** | `num_minibatches × num_updates_per_batch ≤ 32`; exceeding it segfaults during codegen with no Python-level error |
| **MuJoCo Playground defaults to CUDA-only Warp** | must set `cfg.impl = "jax"`; the error (`IndexError`) gives no hint |
| **brax incompatible with JAX 0.11** | `jax.device_put_replicated` removed; AMD users cannot downgrade JAX (pinned by the ROCm plugin) |
| **ROCm torch wheels pin a local triton build** | all four local wheels must be installed together |

### 2.4 If we continued

- Expand the motion library and quantify hyperparameter coverage.
- Pretrained base + per-motion fine-tuning, to cut 6 hours to ~20 minutes.
- Domain randomisation and communication-delay modelling for hardware.
- Resumable long training runs in the web UI.

---

## 3. Code attribution

### Open-source projects used

| Project | Licence | Purpose | Our modifications |
|---|---|---|---|
| [MuJoCo Playground](https://github.com/google-deepmind/mujoco_playground) | Apache-2.0 | G1 model and env base | subclass `G1Env`; force `impl="jax"`; `full_reset=True` on the training wrapper |
| [Brax](https://github.com/google/brax) | Apache-2.0 | PPO | `device_put_replicated` compatibility shim |
| [MuJoCo / MJX](https://github.com/google-deepmind/mujoco) | Apache-2.0 | physics | unmodified |
| [GVHMR](https://github.com/zju3dv/GVHMR) | see upstream | video → SMPL-X | ROCm dependency adaptation; clear stale cache before each run |
| [GMR](https://github.com/YanjieZe/GMR) | MIT | retargeting | unmodified code; environment adaptation only |
| [unitree_mujoco](https://github.com/unitreerobotics/unitree_mujoco) | BSD-3 | layer-3 simulator | **PD moved out of the DDS callback**; headless recording variant; standing keyframe solved by contact bisection; start from the motion's first frame |
| [unitree_sdk2_python](https://github.com/unitreerobotics/unitree_sdk2_python) | BSD-3 | DDS | unmodified |
| [mujoco_menagerie](https://github.com/google-deepmind/mujoco_menagerie) | Apache-2.0 | G1 model | unmodified |
| [BeyondMimic](https://github.com/HybridRobotics/whole_body_tracking) | see upstream | **algorithm reference** | not used as code (CUDA-only); MDP reimplemented on MJX from source |

### Written by us

| File | Contents |
|---|---|
| `g1_track.py` | Tracking environment: BeyondMimic's MDP ported to MJX; deployment-aware 154-D observation |
| `train_track.py` | Training entry point, JAX 0.11 shim, checkpointing |
| `motion_prep.py` | Derives body poses and velocities from joint trajectories (forward kinematics + finite differences) |
| `gmr_to_mjx.py` | Format conversion: joint reorder, quaternion order, resampling, ground alignment |
| `layer2_numpy.py` | Layer 2: pure-NumPy inference in the native MuJoCo C engine |
| `deploy_track.py` | Layer 3: DDS controller, SDK-only observations, torso frame propagation |
| `eval_track.py` | Layer 1 evaluation and side-by-side rendering |
| `replay_check.py` | Kinematic replay self-check |
| `webapp/app.py`, `webapp/pipeline.py` | Gradio UI and the cross-venv backend |
| `diag_*.py` | Root-cause tools: perfect-tracker check, observation diff, PD rate, reachability, torso FK |
| `third_party_patches/` | Patched unitree_mujoco bridge and headless recorder |

### Upstream contributions

| # | Project | Contribution |
|---|---|---|
| 1 | `unitreerobotics/unitree_mujoco` | Move PD out of the DDS callback (code + quantified data) |
| 2 | `unitreerobotics/unitree_mujoco` | Headless recording variant (EGL, no X11) |
| 3 | `google-deepmind/mujoco_playground` | Document/warn that auto-reset does not restore `info` |
| 4 | `google-deepmind/mujoco_playground` | `impl="jax"` necessity on AMD; better error message |
| 5 | `google/brax` | JAX 0.11 `device_put_replicated` compatibility |
| 6 | ROCm ecosystem | gfx1100 XLA graph-size limit: reproduction and workaround |
| 7 | `zju3dv/GVHMR` | AMD/ROCm adaptation path; filename-keyed cache warning |

Details in [`上游贡献素材.md`](docs/zh/上游贡献素材.md).

---

## 4. Team

> Fill in before submission.

| Member | Responsibilities |
|---|---|
| (name) | Environment adaptation, RL training, sim2sim deployment |
| (name) | Video pipeline, motion retargeting |
| (name) | Evaluation, documentation, demo video |

**Collaboration**: (e.g. GitHub PR review / daily sync / module split)

---

## 5. Installation and usage

Verified on the exact configuration below. Every version here is what the
project actually runs on, not a guess.

| Requirement | Value |
|---|---|
| GPU | AMD Radeon Pro W7900 (gfx1100, 48 GB) — any RDNA3 with ROCm support should work |
| OS | Ubuntu 22.04 / 24.04 |
| ROCm | **7.2.1** |
| Python | **3.12.3** |
| Disk | ~40 GB (three venvs ≈ 15 GB, model checkpoints ≈ 8 GB) |
| RAM | 32 GB+ (pytorch3d compilation is memory hungry) |

> A Dockerfile is provided in [`docker/`](docker/) as an alternative, but we do
> **not** ship a prebuilt image: GVHMR depends on SMPL/SMPL-X, whose licence
> forbids redistribution. See [`docker/README.md`](README.md).

### 5.1 Why three separate virtual environments

They **cannot** coexist in one interpreter — installing them together breaks
both sides:

| venv | Key packages | Must NOT contain |
|---|---|---|
| `mjx` | JAX 0.11.0 (rocm), mujoco 3.11.0, mujoco-mjx, brax 0.14.2, gradio | `torch` |
| `gvhmr` | torch 2.9.1+rocm7.2.1, pytorch3d 0.7.9, numpy **1.26.4** | `jax` |
| `gmr` | mujoco 3.11.0, smplx, numpy 2.5.1 | — |

Note `numpy` differs across venvs (2.5.1 vs 1.26.4); this alone makes a single
environment impossible. The web backend therefore runs every stage as a
subprocess and passes data through files.

### 5.2 System packages

```bash
sudo apt update && sudo apt install -y \
    python3.12 python3.12-venv python3.12-dev \
    git wget curl build-essential cmake ninja-build \
    ffmpeg xvfb libegl1 libgl1 libglfw3 libosmesa6 libeigen3-dev libyaml-dev
```

`xvfb` is needed by GMR's retargeting script; `ffmpeg` by every render step.

### 5.3 venv 1 — `mjx` (training, simulation, web UI)

**Install JAX-ROCm first and verify before doing anything else.** If this
prints `cpu`, nothing downstream will work and you will waste hours.

```bash
python3.12 -m venv ~/venvs/mjx && source ~/venvs/mjx/bin/activate
pip install --upgrade pip
pip install --upgrade "jax[rocm7-local]"

python -c "import jax; print(jax.default_backend(), jax.devices())"
# REQUIRED output:  gpu [RocmDevice(id=0)]
```

```bash
pip install "mujoco==3.11.0" "mujoco-mjx==3.11.0" "brax==0.14.2" \
            mujoco_playground gradio matplotlib imageio pygame
```

`pygame` is not optional — unitree_mujoco's bridge imports it unconditionally
even with the joystick disabled.

### 5.4 venv 2 — `gvhmr` (video → SMPL-X)

```bash
python3.12 -m venv ~/venvs/gvhmr && source ~/venvs/gvhmr/bin/activate
pip install --upgrade pip "setuptools<81"
```

`setuptools>=81` removed `pkg_resources`, which lightning still imports.

**The four ROCm torch wheels must be installed in one command.** They pin a
matching local `pytorch-triton-rocm` build, so installing them separately fails
with `No matching distribution found for triton==...+rocm...`:

```bash
pip install --index-url https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/ \
    torch torchvision torchaudio pytorch-triton-rocm
```

```bash
git clone https://github.com/zju3dv/GVHMR ~/GVHMR && cd ~/GVHMR
pip install -r requirements.txt
pip install "numpy<2" yacs pycolmap wis3d "ultralytics>=8.4"
```

- `wis3d` and `pycolmap` are **not** optional — `cv2_utils.py` imports them at
  module level.
- `ultralytics` must be ≥ 8.4: version 8.2.42 breaks with torch ≥ 2.6 because
  `weights_only=True` became the default and blocks the YOLO checkpoint load.

**pytorch3d must be built from source, with `MAX_JOBS` set:**

```bash
git clone https://github.com/facebookresearch/pytorch3d ~/pytorch3d
MAX_JOBS=8 FORCE_CUDA=0 pip install --no-build-isolation -e ~/pytorch3d
```

An unbounded build spawns 30+ `cc1plus` processes; on our machine it starved
the system badly enough that `sshd` could no longer fork and the SSH session
died with `kex_exchange_identification: Connection closed`.

If `chumpy` fails to install (`No module named 'pip'`), install it alone and
patch it — it aborts the whole batch otherwise:

```bash
pip install --no-build-isolation chumpy
CH=$(python -c "import chumpy,os;print(os.path.dirname(chumpy.__file__))")
sed -i 's/inspect.getargspec/inspect.getfullargspec/g' $CH/ch.py
sed -i '/from numpy import bool, int, float, complex, object, unicode, str, nan, inf/d' $CH/__init__.py
```

**Model checkpoints** — follow GVHMR's README to place them under
`~/GVHMR/inputs/checkpoints/`:

| Directory | Size | Note |
|---|---|---|
| `body_models/` | ~1.0 GB | **SMPL + SMPL-X — registration required, cannot be redistributed** |
| `hmr2/` | 2.6 GB | |
| `vitpose/` | 2.4 GB | |
| `yolo/` | 131 MB | |
| `dpvo/` | 14 MB | |
| `gvhmr/` | 156 MB | |

SMPL and SMPL-X must be obtained from their official sites after registering.
This is an upstream licence constraint, not something we can bundle.

### 5.5 venv 3 — `gmr` (retargeting)

```bash
python3.12 -m venv ~/venvs/gmr && source ~/venvs/gmr/bin/activate
pip install --upgrade pip "setuptools<81"
git clone https://github.com/YanjieZe/GMR ~/GMR && cd ~/GMR
pip install -e .
```

### 5.6 Optional — layer-3 deployment (unitree_mujoco over DDS)

Only needed to reproduce layer 3. CycloneDDS must be built from source first;
the Python binding alone is not enough.

```bash
git clone -b releases/0.10.x https://github.com/eclipse-cyclonedds/cyclonedds ~/cyclonedds
cmake -S ~/cyclonedds -B ~/cyclonedds/build \
      -DCMAKE_INSTALL_PREFIX=~/cyclonedds_install -DBUILD_EXAMPLES=OFF
cmake --build ~/cyclonedds/build --target install -j$(nproc)
export CYCLONEDDS_HOME=~/cyclonedds_install
export LD_LIBRARY_PATH=$CYCLONEDDS_HOME/lib:$LD_LIBRARY_PATH

source ~/venvs/mjx/bin/activate
pip install cyclonedds==0.10.2
git clone https://github.com/unitreerobotics/unitree_sdk2_python ~/unitree_sdk2_python
pip install -e ~/unitree_sdk2_python --no-deps
git clone https://github.com/unitreerobotics/unitree_mujoco ~/unitree_mujoco
```

**Apply our patches — layer 3 fails silently without them:**

```bash
cp code/third_party_patches/unitree_sdk2py_bridge.py      ~/unitree_mujoco/simulate_python/
cp code/third_party_patches/unitree_mujoco.py             ~/unitree_mujoco/simulate_python/
cp code/third_party_patches/unitree_mujoco_headless.py    ~/unitree_mujoco/simulate_python/
```

`lo` is not multicast-capable, so DDS needs an explicit unicast config, used by
**both** the simulator and the controller:

```bash
cp docker/cyclonedds_lo.xml ~/cyclonedds_lo.xml
export CYCLONEDDS_URI=file://$HOME/cyclonedds_lo.xml
```

### 5.7 Environment variables

```bash
export MUJOCO_GL=egl                        # offscreen rendering
export XLA_PYTHON_CLIENT_PREALLOCATE=false  # or JAX grabs all VRAM at import
export MPLBACKEND=Agg                       # GVHMR needs a headless matplotlib
```

### 5.8 Run the web UI

```bash
source ~/venvs/mjx/bin/activate
python webapp/app.py            # http://0.0.0.0:7860
```

Edit the paths at the top of `webapp/pipeline.py` (`BASE`, `GVHMR`, `GMR`,
`PY_*`) to match your layout.

Four steps in the browser: extract motion → retarget → train → simulate. Every
step can reuse earlier artifacts and offers a download.

### 5.9 Run from the command line

```bash
# 1) video -> SMPL-X                                   (gvhmr venv)
cd ~/GVHMR && MPLBACKEND=Agg python tools/demo/demo.py \
    --video <video.mp4> --static_cam

# 2) SMPL-X -> G1 joints                               (gmr venv)
cd ~/GMR && xvfb-run -a python scripts/gvhmr_to_robot.py \
    --gvhmr_pred_file ~/GVHMR/outputs/demo/<name>/hmr4d_results.pt \
    --robot unitree_g1 --save_path motions/<name>.pkl

# 3) convert + derive body poses/velocities            (mjx venv)
SCENE=$(python -c "from mujoco_playground._src.locomotion.g1 import g1_constants as c; print(c.FEET_ONLY_FLAT_TERRAIN_XML)")
MUJOCO_GL=osmesa python gmr_to_mjx.py --gmr_pkl motions/<name>.pkl \
    --mjx_xml $SCENE --out motions_mjx/<name>.npz
python motion_prep.py --inp motions_mjx/<name>.npz --out motions_bm/<name>.npz

# 4) train  (~6 h for 371M steps on one W7900)
python train_track.py --motion motions_bm/<name>.npz --run_name <name> \
    --num_envs 4096 --num_timesteps 371000000 --num_evals 73 --keep_checkpoints

# 5) layer 1 — MJX, side-by-side video
MUJOCO_GL=egl python eval_track.py --params output/train/<name>/params_best \
    --motion motions_bm/<name>.npz --video out_l1.mp4

# 6) layer 2 — native MuJoCo + pure NumPy
MUJOCO_GL=egl python layer2_numpy.py --params output/train/<name>/params_best \
    --motion motions_bm/<name>.npz --out out_l2.mp4

# 7) layer 3 — unitree_mujoco over DDS (needs §5.6)
cd ~/unitree_mujoco/simulate_python
MUJOCO_GL=egl python unitree_mujoco_headless.py \
    --init_motion motions_bm/<name>.npz --out out_l3.mp4 --seconds <T*0.02> &
sleep 8
cd - && python deploy_track.py --policy deploy/track_<name>.npz \
    --motion motions_bm/<name>.npz --steps <T> --domain_id 1 --interface lo
```

### 5.10 Hyperparameters (shared by all motions, never tuned per motion)

```python
num_envs=4096, unroll_length=20, batch_size=256,
num_minibatches=16, num_updates_per_batch=2,   # gfx1100 limit: product <= 32
learning_rate=3e-4, entropy_cost=1e-3,
discounting=0.99, gae_lambda=0.95, clipping_epsilon=0.2,
normalize_observations=True, deterministic_eval=True,
sim_dt=0.002, ctrl_dt=0.02, action_scale=0.5,
network=(512, 256, 128) for both policy and value
```

### 5.11 Verification checklist

Run these in order; each one catches a different class of failure.

| # | Check | Command | Expected |
|---|---|---|---|
| 1 | JAX sees the GPU | `python -c "import jax;print(jax.default_backend())"` | `gpu` |
| 2 | venvs are isolated | `~/venvs/mjx/bin/python -c "import torch"` | `ModuleNotFoundError` |
| 3 | | `~/venvs/gvhmr/bin/python -c "import jax"` | `ModuleNotFoundError` |
| 4 | **Reward function is correct** | `python diag_perfect.py motions_bm/<name>.npz` | all six tracking rewards read **1.0000** |
| 5 | Motion is reachable | `python diag_reach.py` | peak deviation reported per joint |
| 6 | Training converges | watch `ep_len` and `body_pos` | `ep_len` rises, `body_pos` falls |
| 7 | Layer 1 / 2 | `eval_track.py` / `layer2_numpy.py` | 100% motion completed |
| 8 | Layer 3 | `deploy_track.py` | survives the full motion |

**Check 4 is the important one.** It sets the state exactly to a reference
frame, where a perfect tracker must score 1.0000 on every term. Anything else
means a frame, reference-point or unit convention is still wrong — and no
policy can score in such an environment. Run it the day you touch the reward.

### 5.12 The three pitfalls that fail silently

These produce **no error message**. Handle them up front.

| Pitfall | Symptom | Fix |
|---|---|---|
| **Playground auto-reset does not restore `info`** | training gets worse; the untrained network is best | `wrap_for_brax_training(..., full_reset=True)` |
| **GVHMR reuses cache keyed on filename** | a same-named video silently returns the previous result | `rm -rf outputs/demo/<name>` first; the only tell is `Time elapsed: 0.03s` |
| **unitree_mujoco computes PD in the DDS callback** | fine in native MuJoCo, falls at ~47 steps over DDS | apply the patch in §5.6 |

The full operational checklist is in
[`踩坑清单-Docker打包必读.md`](docs/zh/踩坑清单-Docker打包必读.md).

## 6. Notes

**Real hardware**: contest FAQ Q66/Q69 states all work must be done in the
cloud and real-robot results do not count towards scoring. All layer-3
validation runs in the cloud on `unitree_mujoco`. `deploy_track.py` shares the
same DDS interface and NumPy weights as a real deployment — only the network
interface name changes.

**SMPL/SMPL-X licensing**: GVHMR depends on SMPL and SMPL-X body models, which
are registration-gated and whose licence forbids redistribution. They cannot be
baked into a public Docker image; users must obtain them themselves.

## 7. Licence

Apache-2.0 (see [`LICENSE`](LICENSE)). Third-party components retain their
original licences — see §3.
