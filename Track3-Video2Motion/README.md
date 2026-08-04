# Video2Motion

**Record a video of a person moving; get a control policy the Unitree G1 can execute — end to end on AMD ROCm**

[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![ROCm](https://img.shields.io/badge/ROCm-7.2.1-red)](https://rocm.docs.amd.com/)
[![GPU](https://img.shields.io/badge/GPU-Radeon%20Pro%20W7900-ED1C24)](https://www.amd.com/)
[![JAX](https://img.shields.io/badge/JAX-0.11%20(rocm)-orange)](https://github.com/jax-ml/jax)

AMD AI DevMaster Hackathon 2026 · Track 3, Physical AI

| | |
|---|---|
| [Technical report](docs/TECHNICAL_REPORT.md) | architecture, results, how the AMD GPU is used, contributions |
| [Algorithm design](docs/ALGORITHM.md) | how the method evolved; differences from BeyondMimic |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | every failure we hit, including three that fail *silently* |
| [Docker](docker/DOCKER.md) | image build; why no prebuilt image is published |

---

## 1. Overview

Teaching a humanoid a new motion normally needs a motion-capture rig, an RL
engineer to tune rewards for that motion, and a sim2real process that often
fails. This project compresses it to **record a video → wait → get a policy**,
through a web UI, with no code.

```
  video (mp4)
      │  GVHMR          62 s for a 3.2 s clip        AMD GPU
  SMPL-X body motion
      │  GMR            inverse kinematics           CPU
  G1 29-DoF joint trajectory
      │  Brax PPO on MuJoCo MJX   4096 envs          AMD GPU
  control policy  →  pure NumPy, 251k params, no JAX
      │
      └── DDS ──▶ unitree_mujoco / real Unitree G1
```

**Why this is not a backend swap.** Every mainstream stack in this field is
CUDA-only — Isaac Lab, Isaac Sim, MuJoCo Warp, unitree_rl_mjlab, and
BeyondMimic's own implementation. The only viable massively-parallel path on
AMD is MuJoCo MJX with JAX-ROCm, so the tracking algorithm was reimplemented on
MJX from source.

### Result

Validated in three progressive layers, **each swapping one group of
components** so that a failure can be localised:

| Layer | Physics | Robot model | Inference | Interface | Motion completed | Body position error |
|---|---|---|---|---|---|---|
| Zero-action baseline | — | — | — | — | 44/156 (28.2%) | 0.0772 m |
| **1** | MuJoCo MJX (JAX/GPU) | Playground G1 | brax network | direct memory | **100%** | **0.0269 m** |
| **2** | MuJoCo native C (CPU) | Playground G1 | **pure NumPy** | direct memory | **100%** | **0.0273 m** |
| **3** | MuJoCo native C | **Unitree official G1** | pure NumPy | **DDS** | **100%** | 4–5° joint error |

Layer 3 runs on Unitree's own simulator, robot model and transport, with the
policy restricted to what `LowState` actually provides. Videos in
[`videos/`](videos/); reasoning in the
[technical report](docs/TECHNICAL_REPORT.md).

Training: 371M steps in 357 min at 17,326 env-steps/s on one W7900. The motion
is fully performed from ~112M steps (2 h); the rest buys smoothness.

### Data

There is no training dataset in the usual sense — **the input is a single video
the user records**, and the reference motion is derived from it at runtime.

| Artifact | Source | Size |
|---|---|---|
| Input video | recorded by the user (demo: 3.17 s, 1280×720, 30 fps) | 1.9 MB |
| Reference motion | derived at runtime; 157 frames at 50 fps, 14 tracked body links | 1.2 MB |
| Training samples | generated online by the simulator; 371M environment steps | — |
| Pretrained weights | GVHMR (HMR2, ViTPose, YOLO) and SMPL/SMPL-X, all upstream | ~8 GB |

---

## 2. Setup

Verified on **ROCm 7.2.1**, Python **3.12.3**, Ubuntu 22.04, Radeon Pro W7900
(gfx1100, 48 GB). Needs ~40 GB disk and 32 GB+ RAM.

```bash
git clone <this-repo> && cd Track3-Video2Motion
./scripts/setup.sh                 # add --with-dds to also enable layer 3
source env.sh
./scripts/verify.sh
```

`setup.sh` takes roughly 60–90 minutes, dominated by compiling pytorch3d. It
creates three virtual environments, writes `env.sh`, and applies our patches to
`unitree_mujoco`.

**Why three environments** — they cannot coexist in one interpreter. `numpy`
alone differs, and one side needs `jax` while the other needs `torch`:

| venv | Key packages | Must NOT contain |
|---|---|---|
| `mjx` | JAX 0.11 (rocm), mujoco 3.11, brax 0.14.2, gradio | `torch` |
| `gvhmr` | torch 2.9.1+rocm, pytorch3d, numpy 1.26.4 | `jax` |
| `gmr` | mujoco 3.11, smplx, numpy 2.5.1 | — |

The backend therefore runs every stage as a subprocess and passes data through
files. `verify.sh` asserts the isolation.

### One manual step: SMPL / SMPL-X

GVHMR needs the SMPL and SMPL-X body models (~1 GB). They are
registration-gated and **their licence forbids redistribution**, so no script
can fetch them. Register on the official sites, then place them at:

```
$V2M_GVHMR/inputs/checkpoints/body_models/
├── smpl/SMPL_{NEUTRAL,MALE,FEMALE}.pkl
└── smplx/SMPLX_{NEUTRAL,MALE,FEMALE}.npz
```

The remaining GVHMR checkpoints (HMR2, ViTPose, YOLO, DPVO) follow GVHMR's own
download instructions. Steps 2–4 work without any of this if you already have a
retargeted motion.

If `setup.sh` fails, the cause is almost certainly listed under
[Troubleshooting → Installation](docs/TROUBLESHOOTING.md).

---

## 3. Usage

### Web UI

```bash
source env.sh
$V2M_PY_MJX src/webapp/app.py        # http://localhost:7860
```

Four steps: extract motion → retarget → train → simulate. Each step can reuse
earlier artifacts and offers a download. Training length is user-chosen with no
upper limit, shows four live curves, can be stopped mid-run, and keeps every
checkpoint.

### Command line

```bash
source env.sh
./scripts/run_pipeline.sh my_video.mp4 my_motion 6     # video → validated policy
./scripts/run_layer3.sh my_motion                      # DDS on unitree_mujoco
```

`run_pipeline.sh` runs all five stages and prints the retargeting video path so
you can inspect it before committing hours to training. The last argument is
the training budget in hours (default 6). The script is the authoritative list
of commands if you want to run stages individually.

### Verification

```bash
./scripts/verify.sh
```

Three checks: paths and GPU, environment isolation, and the reward function.

The third is the one that matters. It sets the state exactly to a reference
frame, where a perfect tracker **must** score 1.0000 on every reward term.
Anything else means a frame, reference-point or unit convention is wrong — and
in such an environment no policy can score, however good it is. Run it whenever
you touch the reward.

Expected end to end: 100% motion completed in layers 1 and 2, and the robot
surviving the full motion in layer 3.

---

## 4. Repository layout

```
src/
├── config.py              path resolution from environment variables
├── g1_track.py            tracking environment (BeyondMimic MDP ported to MJX)
├── train_track.py         training entry point
├── motion_prep.py         derives body poses/velocities from joint trajectories
├── gmr_to_mjx.py          format conversion
├── eval_track.py          layer 1 + side-by-side rendering
├── layer2_numpy.py        layer 2: pure NumPy in the native C engine
├── deploy_track.py        layer 3: DDS controller, SDK-only observations
├── webapp/                Gradio UI and the cross-venv backend
├── diagnostics/           reward validation, reachability, torso FK, camera
└── third_party_patches/   patched unitree_mujoco bridge and headless recorder
scripts/                   setup, verification, end-to-end pipeline
docker/                    Dockerfile and build script
docs/                      technical report, algorithm design, troubleshooting
videos/                    input, retargeting, and all three validation layers
assets/policy_salute.npz   the trained policy for the demo motion
```

---

## 5. Code attribution

| Project | Licence | Purpose | Our modifications |
|---|---|---|---|
| [MuJoCo Playground](https://github.com/google-deepmind/mujoco_playground) | Apache-2.0 | G1 model and env base | subclass `G1Env`; force `impl="jax"`; `full_reset=True` on the training wrapper |
| [Brax](https://github.com/google/brax) | Apache-2.0 | PPO | `device_put_replicated` compatibility shim |
| [MuJoCo / MJX](https://github.com/google-deepmind/mujoco) | Apache-2.0 | physics | unmodified |
| [GVHMR](https://github.com/zju3dv/GVHMR) | see upstream | video → SMPL-X | ROCm dependency adaptation; clear stale cache before each run |
| [GMR](https://github.com/YanjieZe/GMR) | MIT | retargeting | unmodified code; environment adaptation only |
| [unitree_mujoco](https://github.com/unitreerobotics/unitree_mujoco) | BSD-3 | layer-3 simulator | **PD moved out of the DDS callback**; headless recorder; keyframe height solved by contact bisection; start from the motion's first frame |
| [unitree_sdk2_python](https://github.com/unitreerobotics/unitree_sdk2_python) | BSD-3 | DDS | unmodified |
| [mujoco_menagerie](https://github.com/google-deepmind/mujoco_menagerie) | Apache-2.0 | G1 model | unmodified |
| [BeyondMimic](https://github.com/HybridRobotics/whole_body_tracking) | see upstream | **algorithm reference** | not used as code (CUDA-only); MDP reimplemented on MJX from source |

Everything under `src/`, `scripts/`, `docker/` and `docs/` is written by us.
Upstream contributions we made are listed in the
[technical report](docs/TECHNICAL_REPORT.md).

---

## 6. Team

> To be completed before submission.

| Member | Contribution |
|---|---|
| (name) | (contribution) |

---

## 7. Notes

**Real hardware** — contest FAQ Q66/Q69 states all work must be done in the
cloud and real-robot results do not count towards scoring. All layer-3
validation runs in the cloud on `unitree_mujoco`. `deploy_track.py` shares the
same DDS interface and NumPy weights as a real deployment; only the network
interface name changes.

**Licence** — Apache-2.0 (see [`LICENSE`](LICENSE)). Third-party components
retain their original licences; see §5.
