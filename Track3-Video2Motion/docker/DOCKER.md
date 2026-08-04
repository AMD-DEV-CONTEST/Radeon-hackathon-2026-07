# Docker packaging

The Track 3 rules say a Docker image containing the full source and runtime
"would be preferable". We provide a complete, tested `Dockerfile` but
deliberately **do not publish a prebuilt image** — GVHMR depends on SMPL/SMPL-X,
whose licence forbids redistribution, so a public image would violate it. The
image builds in one command once you supply those models yourself.

## Where you can build this

**Not inside a non-privileged container.** We verified this on the contest
machine:

| Attempt | Result |
|---|---|
| `dockerd` with defaults | ❌ `iptables: Permission denied` |
| `dockerd --iptables=false --bridge=none` | ✅ daemon starts, storage driver `overlayfs` |
| `docker build` on a two-line Dockerfile | ❌ **`unshare: operation not permitted`** |

`capsh --print` shows the capability set is stripped:

```
Current IAB: ... !cap_sys_admin, !cap_net_admin, !cap_sys_module, ...
```

Without `CAP_SYS_ADMIN` the daemon cannot create namespaces, so no `RUN` step
can execute. Build on a host with a normal Docker install, or a VM, or CI.

## Build

```bash
cd 成果产物
REGISTRY=<your-registry>/<ns>/<repo> TAG=1.0 ./docker/build.sh
```

Expect **~45 GB** and a long first build. The bulk is:

| Component | Size |
|---|---|
| ROCm 7.2.1 base image | ~22 GB |
| three venvs (mjx 4.2 + gvhmr 5.3 + gmr 5.2) | ~15 GB |
| GVHMR checkpoints (hmr2 2.6 + vitpose 2.4 + …) | ~6 GB |
| GMR assets | ~1.5 GB |

The slowest step is compiling pytorch3d. `MAX_JOBS=8` is set in the Dockerfile
and is **not optional** — an unbounded build spawns 30+ `cc1plus` processes and
can starve the machine to the point where `sshd` cannot fork.

## Run

```bash
docker run --rm -it \
  --device=/dev/kfd --device=/dev/dri --group-add video \
  --ipc=host --shm-size 16G \
  -p 7860:7860 \
  -v $PWD/smpl_models:/opt/models/body_models:ro \
  -v $PWD/workdir:/workspace \
  <image>:1.0
```

Then open <http://localhost:7860>.

Other entrypoints:

```bash
docker run ... <image>:1.0 check                    # GPU + model sanity check
docker run ... <image>:1.0 train  --motion ... --run_name ...
docker run ... <image>:1.0 layer2 --params ... --motion ...
docker run ... <image>:1.0 bash
```

## SMPL / SMPL-X are not included

GVHMR needs the SMPL and SMPL-X body models (~1 GB). They are
registration-gated and **their licence forbids redistribution**, so they are
deliberately left out of the image.

Register and download from the official sites, then mount:

```
body_models/
├── smpl/
│   ├── SMPL_NEUTRAL.pkl
│   ├── SMPL_MALE.pkl
│   └── SMPL_FEMALE.pkl
└── smplx/
    ├── SMPLX_NEUTRAL.npz
    ├── SMPLX_MALE.npz
    └── SMPLX_FEMALE.npz
```

```bash
-v /path/to/body_models:/opt/models/body_models:ro
```

Without them, step 1 (video → SMPL-X) fails; steps 2–4 still work on motions
that are already retargeted. The entrypoint checks for them and prints this
same guidance.

## Patches baked into the image

These are applied over the upstream repos at build time. Skipping any of them
produces a **silent** failure — see
[`踩坑清单-Docker打包必读.md`](../docs/zh/踩坑清单-Docker打包必读.md).

| # | File | Why |
|---|---|---|
| 1 | `unitree_sdk2py_bridge.py` | PD moved out of the DDS callback. Upstream computes torque in the 50 Hz callback and holds it for 20 ms; training runs at 500 Hz and real motor drivers at 1–2 kHz. A stiff policy falls at ~18–47 steps over DDS while being perfectly stable in native MuJoCo. Raising `kd` does not help. |
| 2 | `unitree_mujoco.py` | calls `ApplyPD()` inside the simulation loop |
| 3 | `unitree_mujoco_headless.py` | headless recorder (EGL offscreen). Upstream requires a GLFW window; under Xvfb, `x11grab` captures a frozen frame. Also supports `--init_motion` so the robot starts from the motion's first frame rather than a generic standing keyframe (they can differ by 36°). |

## Runtime environment

Set by the Dockerfile:

```
MUJOCO_GL=egl                        offscreen rendering (osmesa only for CPU-only)
XLA_PYTHON_CLIENT_PREALLOCATE=false  otherwise JAX grabs all VRAM at import
MPLBACKEND=Agg                       GVHMR needs a headless matplotlib
CYCLONEDDS_URI=file:///opt/cyclonedds_lo.xml
```

## Why three separate venvs

They cannot coexist in one interpreter:

| venv | Key dependencies | Must not contain |
|---|---|---|
| `/opt/venv/gvhmr` | PyTorch-ROCm, pytorch3d | jax |
| `/opt/venv/gmr` | retargeting deps | — |
| `/opt/venv/mjx` | JAX-ROCm, MuJoCo, MJX, brax, gradio | torch |

Verify after a build:

```bash
docker run --rm <image>:1.0 bash -c \
  '/opt/venv/gvhmr/bin/python -c "import torch, jax" 2>&1 | tail -1; \
   /opt/venv/mjx/bin/python   -c "import jax, torch" 2>&1 | tail -1'
# both must report ModuleNotFoundError
```

The backend (`webapp/pipeline.py`) therefore runs every stage as a subprocess
and passes data between them through files.
