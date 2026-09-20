# BiGym 3DGS Closed-Loop Evaluation and End-to-End Performance Benchmark on AMD ROCm (gfx1100 · RDNA3)

This document is the **evaluation chapter** supplement to `amd_rocm_jax.md` (installation / training / inference): composing the OpenPI JAX policy, BiGym/MuJoCo simulation, and calibrated 3DGS room shell into a **two-process closed-loop evaluation**, and providing the **complete measured performance metrics** for training / inference / evaluation / rendering. **For AMD ROCm only** (gfx1100 / RDNA3, ROCm 7.2.1).

> Test host: AMD gfx1100 (RDNA3, 96 CU, `rocm-smi` reports 51.5 GiB VRAM, W7900D-class), ROCm 7.2.1 installed at `/opt/rocm`, single GPU visible, EPYC 9334.
> Default task: `DishwasherUnloadCutleryLong`; π0.5 LoRA checkpoint.

---

## 0. Why Two Processes

JAX (policy) and PyTorch/gsplat (simulation + 3DGS rendering) each bring their own ROCm runtime. **Stuffing them into the same Python process triggers MIOpen/rocBLAS symbol conflicts**. Therefore the closed-loop evaluation is split into two independent processes that time-share the GPU on a single card:

| Process | Runtime stack | venv | Default GPU | Responsibility |
| --- | --- | --- | --- | --- |
| Policy service | JAX ROCm 0.6.0 (CPU torch) | `.venv` (openpi) | `POLICY_GPU=0` | Load Orbax LoRA, serve `POST /process_frame` |
| Simulation client | PyTorch ROCm + gsplat 1.4.0 + MuJoCo | `/path/to/bigym_3dgs-venv` | `SIM_GPU=0` (same card for single-GPU) | MuJoCo stepping + strict three-camera 3DGS rendering |

> Single-GPU (48 GiB-class) support: the two processes load sequentially; run a VRAM gate once before evaluation (see §4.3). Do not import JAX and PyTorch/gsplat ROCm into the same process simultaneously.

---

## 1. Environments (Two Sets, Mutually Non-Contaminating)

### 1.1 Policy Service Environment (openpi's `.venv`: JAX ROCm + CPU torch)

Build exactly following the .venv + apt procedure in [`amd_rocm_jax.md` §1.1](amd_rocm_jax.md) (i.e., the [README "Installation" section](../README.md)):

```bash
git clone https://github.com/WuChao-2024/openpi_lerobot_plus openpi
cd openpi
# 跑 README §安装 的 10 步：apt ffmpeg + python3.12 -m venv .venv + 分步 pip + transformers 补丁 + activate 钩子
source .venv/bin/activate
# 验证: import jax; jax.devices() -> [RocmDevice(id=0)];  import torch; torch.version.hip is None（必须 CPU torch）
pip install flask      # 评测 adapter 用
```

Key points (see `amd_rocm_jax.md` for details): AMD ROCm JAX 0.6.0 (`repo.radeon.com` rocm-rel-7.0.2, gfx1100 kernels embedded) + `ml-dtypes==0.5.4` (jaxlib 0.6.0 runtime requires `float4_e2m1fn`) + **CPU torch 2.7.1** (to avoid dual ROCm stacks). The `.venv/bin/activate` hook already sets `LD_LIBRARY_PATH=/opt/rocm/lib`.

### 1.2 Simulation Client Environment `bigym_3dgs` (PyTorch ROCm + gsplat + MuJoCo)

Simulation + 3DGS rendering requires GPU torch and gsplat. **Create a separate venv; do not mix it with openpi's `.venv`**:

```bash
python3.12 -m venv /path/to/bigym_3dgs-venv
source /path/to/bigym_3dgs-venv/bin/activate
# (a) ROCm torch（公开 rocm6.4 wheel，HIP 6.4 运行时，跑在 ROCm 7.2.1 驱动上，前向兼容）
pip install --no-cache-dir torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/rocm6.4
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"   # True / AMD Radeon Graphics
# (b) gsplat 1.4.0 + ROCm 补丁（见 §2，必须做 bfloat16 修复）
# (c) BiGym 仿真栈
pip install -e /path/to/bigym_plus[examples]        # 不要装 [visual-shell]：会拖一个新 gsplat 覆盖 §2 的修复
pip install "mujoco==3.10.0" "dm_control==1.0.43" requests "av==15.1.0"
pip install --no-deps "gaussian_renderer==0.2.0" plyfile   # BiGym 视觉壳渲染器（--no-deps 保住修好的 gsplat）
```

Pin reasons: `mujoco==3.10.0` (aligned with demo trajectories; newer versions break recorded demos), `dm_control==1.0.43` (1.0.44 requires mujoco≥3.11). numpy 2.x is sufficient (without lerobot, no need to pin 2.2.6).

---

## 2. Compile Fix for gsplat 1.4.0 on gfx1100 / ROCm 7.2.1 (Critical)

gsplat 1.4.0's HIP kernels fail to compile directly on **ROCm 7.2.1 + public rocm6.4 torch**. Reproduction steps and root cause are as follows (this is the hardest pitfall on this path):

### 2.1 Install gsplat + Apply Patch + Build ROCm Wrapper

```bash
# 用 amd-bigym-3dgs-rocm 仓库的补丁与 wrapper 脚本（与 openpi-eval lane 同源）
cd /path/to/amd-bigym-3dgs-rocm
export VENV=/path/to/bigym_3dgs-venv        # 指向 §1.2 的 env
export ROCM_ROOT=/opt/rocm-7.2.1
export ROCM_WRAPPER=/path/to/amd-bigym-3dgs/toolchains/rocm-7.2.1-clang22
export PYTORCH_ROCM_ARCH=gfx1100
export TORCH_EXTENSIONS_DIR=/path/to/amd-bigym-3dgs/cache/torch-extensions-gsplat
./scripts/create_rocm_wrapper.sh                    # 生成薄 hipcc wrapper（指向 /opt/rocm-7.2.1，不改 /opt/rocm）
$VENV/bin/pip install --no-deps gsplat==1.4.0
$VENV/bin/pip install --no-deps rich ninja jaxtyping plyfile   # gsplat 运行期纯 python 依赖
patch -d $($VENV/bin/python -c 'import site;print(site.getsitepackages()[0])') -p1 \
      < patches/gsplat-1.4.0-rocm-gfx1100.patch
```

### 2.2 Root Cause and Two Necessary Fixes

Compile errors and fixes (**applied to gsplat source in site-packages**):

| Symptom | Root cause | Fix |
| --- | --- | --- |
| `unknown type name '__hip_bfloat16'` | torch's `hipify` **regenerates `hip/csrc/types.cuh` from `cuda/csrc/types.cuh` on every build**, mapping `__nv_bfloat16` to `__hip_bfloat16`; but ROCm 7.2.1 has **renamed** it to `hip_bfloat16`. Modifying `hip/csrc/*` is useless (it gets overwritten by hipify). | Edit the **source** `gsplat/cuda/csrc/types.cuh:33`: `OpType<__nv_bfloat16>` → `OpType<hip_bfloat16>` (hipify passes non-CUDA tokens through unchanged, so the output is the correct `hip_bfloat16`). |
| `'cooperative_groups/reduce.h' file not found` | gsplat's `.hip` includes the CUDA-style `cooperative_groups/reduce.h`, but ROCm 7.2.1 only ships `hip/hip_cooperative_groups.h`. However, `cg::reduce/plus/greater` is actually **provided by gsplat's own `hip/csrc/helpers.cuh`**. | Just place an **empty** `cooperative_groups/reduce.h` in the include path (only satisfies `#include` resolution, no duplicate definitions). |
| `-D__hip_bfloat16=hip_bfloat16` (attempted) | A global macro alias **breaks ROCm's own** `amd_hip_bf16.h` (which internally distinguishes `__hip_bfloat16_raw` from `hip_bfloat16`). | **Do not use -D macro**; use the source edit above. |

Concrete commands:

```bash
SP=$($VENV/bin/python -c 'import site;print(site.getsitepackages()[0])')/gsplat
# 修复 1：bfloat16 源头改字（cuda/csrc，hipify 源）
python3 -c "p='$SP/cuda/csrc/types.cuh'; s=open(p).read(); open(p,'w').write(s.replace('__nv_bfloat16','hip_bfloat16'))"
# 修复 2：空 cg/reduce.h 垫片
mkdir -p /path/to/amd-bigym-3dgs/shim/cooperative_groups
printf '#pragma once\n' > /path/to/amd-bigym-3dgs/shim/cooperative_groups/reduce.h
# 编译冒烟（首次 JIT，几分钟）
export ROCM_HOME=$ROCM_WRAPPER PATH=$ROCM_WRAPPER/bin:$PATH
export CPLUS_INCLUDE_PATH="/path/to/amd-bigym-3dgs/shim:$SP/cuda/csrc/third_party/glm"
$VENV/bin/python scripts/smoke_test_gsplat.py
# 期望: GATE_OK True / DEVICE AMD Radeon Graphics
```

### 2.3 Verify the Shell Actually Renders into BiGym

```bash
export MUJOCO_GL=egl PYOPENGL_PLATFORM=egl
$VENV/bin/python - <<'PY'
import sys; sys.path.insert(0, '/path/to/bigym_plus/d/replay_generation')
from env_utils import build_env
env = build_env('DishwasherUnloadCutleryLong', render_mode='rgb_array',
                visual_shell_profile='/path/to/scene-shell-profile.json', visual_shell_strict=False)
print('VISUAL_SHELL_ACTIVE:', getattr(env, '_visual_shell', None) is not None)   # True
obs, _ = env.reset(seed=0); print('head', obs['rgb_head'].shape, obs['rgb_head'].mean())  # (3,480,848), 明亮
PY
```

---

## 3. Evaluation Reproduction Steps (ROCm-only, End-to-End)

### 3.1 Input Pinning (VERSION_LOCK)

| Component | Pinned value |
| --- | --- |
| OpenPI service | `WuChao-2024/openpi_lerobot_plus` commit `9a98f327` |
| BiGym client | `WuChao-2024/bigym_plus` commit `d1293768` |
| π0.5 checkpoint | `WuChao-Cauchy/pi05_ckpts` rev `b20a8efa` (or locally downloaded `run1_lora_h20_20k/19999`) |
| AMD 3DGS shell | `eustance/amd-bigym-3dgs-kitchen-shell` **branch `amd-rocm-w7900d-20260804`** (includes `scene-shell-profile.json` + calibrated `alignment.json` + three-layer PLY) |
| Evaluation lane | `eust-w/amd-bigym-3dgs-rocm`'s `evaluation/openpi-jax-bigym/` (`bin/` + `src/`) |

> ⚠️ The shell **must use the `amd-rocm-w7900d-20260804` branch** (W7900D real-camera calibration). The default branch is calibrated for a different GPU model; the sha in `scene-shell-profile.json` won't match and `layer_files` carries stale `/scratch` paths, causing blurry rendering / camera landing outside the capture trajectory. Download: `hf download eustance/amd-bigym-3dgs-kitchen-shell --repo-type dataset --revision amd-rocm-w7900d-20260804 --local-dir .../amd-kitchen-shell`.

### 3.2 Terminal A: Policy Service (Default autotune, first run may segfault → restart and retry)

```bash
source /path/to/openpi/.venv/bin/activate     # openpi 的策略服务 venv（含 LD_LIBRARY_PATH 钩子）
cd /path/to/amd-bigym-3dgs-rocm/evaluation/openpi-jax-bigym
export ROCR_VISIBLE_DEVICES=0 HIP_VISIBLE_DEVICES=0
export XLA_PYTHON_CLIENT_MEM_FRACTION=0.75          # 单卡与 gsplat 共享: 给 gsplat 留余量
export ROCM_PATH=/opt/rocm LD_LIBRARY_PATH="/opt/rocm/lib:$LD_LIBRARY_PATH"
export OPENPI_DIR=/path/to/openpi  POLICY_CHECKPOINT_REVISION=19999
# ★ 推理必须用默认 autotune（不要设 XLA_FLAGS=--xla_gpu_autotune_level=1，否则输出全 NaN）
python -u src/inference_server_bigym_amd.py \
  --action-dim 16 --model-action-dim 32 --action-horizon 20 \
  --camera-names high l_wrist r_wrist \
  --camera-sources observation.images.cam_high observation.images.cam_left_wrist observation.images.cam_right_wrist \
  --wrist-names l_wrist r_wrist \
  --data-dir /path/to/dishwasher_unload_cutlery_long \
  --checkpoint-dir /path/to/run1_lora_h20_20k/19999 \
  --lora --default-prompt "Unload cutlery from dishwasher to drawer task." \
  --host 127.0.0.1 --port 7891
```

> On gfx1100, **the first `/process_frame` JIT compilation occasionally SIGSEGV(139)** — XLA's `gemm_fusion_autotuner` randomly picks a bad kernel. **Just restart the service and retry** (the autotuner is non-deterministic; retry most likely picks a good kernel; stable once warmed). After warming, confirm with one frame that `np.isfinite(chunk).all()` and `shape==(20,16)` before starting evaluation.

### 3.3 Terminal B: Simulation Client Runs the Closed Loop

```bash
source /path/to/bigym_3dgs-venv/bin/activate
cd /path/to/amd-bigym-3dgs-rocm/evaluation/openpi-jax-bigym
export AMD_EVAL_ROOT=$PWD
export BIGYM_DIR=/path/to/bigym_plus
export PYTHONPATH="$BIGYM_DIR/d/replay_generation:$BIGYM_DIR"
export VENV=/path/to/bigym_3dgs-venv
export SHELL_DIR=/path/to/amd-kitchen-shell                      # 含 scene-shell-profile.json
export POLICY_BASE_URL=http://127.0.0.1:7891
export TORCH_EXTENSIONS_DIR=/path/to/amd-bigym-3dgs/cache/torch-extensions-gsplat
export CPLUS_INCLUDE_PATH="/path/to/amd-bigym-3dgs/shim:$BIGYM_DIR/.../glm"
export ROCM_HOME=/path/to/amd-bigym-3dgs/toolchains/rocm-7.2.1-clang22 PATH=$ROCM_HOME/bin:$PATH
export PYTORCH_ROCM_ARCH=gfx1100 MUJOCO_GL=egl PYOPENGL_PLATFORM=egl SIM_GPU=0 POLICY_GPU=0

./bin/probe_policy.sh                                  # 探测服务返回有限 (20,16)
N_EPISODES=3  RUN_NAME=smoke   ./bin/run_eval.sh smoke    # 3 集冒烟
N_EPISODES=50 RUN_NAME=custom-50 ./bin/run_eval.sh custom  # 50 集（action-horizon 20）
```

> **action-horizon must match checkpoint training**: `run1_lora_h20_20k/19999` is trained with **h20**, so evaluation must use `--action-horizon 20`, and the lane's chunk-shape validation must be `(20,16)` (server-side `inference_server_bigym_amd.py` + client-side `eval_bigym_3dgs.py`).

Artifacts: `results/<run>/dishwasher_unload_cutlery_long/episodes/episode-NNNNNN/{steps.jsonl, manifest.json, videos/{head,left_wrist,right_wrist}.mp4}` + `results.json` + `recording-validation.json` + `evaluation-summary.json`.

---

## 4. Complete Performance Benchmark (Measured)

### 4.1 Training (pi05 LoRA, single gfx1100, bs=4, action-horizon 20)

| Metric | Measured value | Notes |
| --- | --- | --- |
| Model | pi05 LoRA (base frozen + EMA off) | `gemma_2b_lora` + `gemma_300m_lora` |
| Config | bs=4, horizon=20, 20000-step target, peak_lr 2.5e-5, warmup 1000 | |
| **Steady-state throughput** | **1.2 s/it = 0.83 step/s = 3.33 samples/s** | Excludes the ~95 s compile period |
| **Peak VRAM** | **35.32 GiB** (steady-state mean 33.65 GiB) / 51.5 GiB | on-demand sampling; bs=4·h20·LoRA |
| **Steady-state GPU utilization** | **95.6%** | 539/565 samples at 100%, remainder is between-step / save gaps |
| 1000-step wall | ~20 min | Steady 1000×1.2 s + ~90 s compile + final save |
| Loss trajectory | 0.2649 → ~0.0165 plateau (monotonic decrease) | step0 0.2649 / 1k 0.043 / 5k 0.0228 / 9k 0.0168 |
| Stable config | `PREALLOCATE=false MEM_FRACTION=0.99 XLA_FLAGS=--xla_gpu_autotune_level=1 --num-workers 0` | ★ see §5.1 |

### 4.2 Inference (pi05 LoRA, single GPU, batch 1, action-horizon 20)

| Metric | Measured value | Notes |
| --- | --- | --- |
| **End-to-end latency** | **239.8 ms/call (eval-measured 243.7 ms, p50 216 / p95 284 / max 441)** | Includes PNG decode + HTTP + pi05 forward |
| Model forward (excluding HTTP/decode) | ~150–180 ms | `policy_timing.infer_ms` from `policy.infer` |
| **Throughput** | **~4.17 calls/s** | Sustained burst |
| **Peak VRAM** | **10.03 GiB** (steady-state 9.44 GiB, on-demand measures real working set) | Weights + JIT buffer |
| Deployed resident VRAM | ~36–40 GiB | With default preallocate (`MEM_FRACTION=0.75`≈36 GiB), occupies even when idle |
| autotune | **Must be default** (`level=1` makes sampling output **all NaN**) | Intrinsic to gfx1100 / jax0.6.0 |

### 4.3 Closed-Loop Evaluation (DishwasherUnloadCutleryLong, single-GPU shared, ckpt 19999)

| Metric | Measured value |
| --- | --- |
| **Success rate** | **5/50 = 10.0%** |
| Policy requests | 2622 |
| Latency ms (mean/p50/p95/max) | 243.7 / 216.2 / 283.6 / 441.3 |
| Total transitions | 51646 (50 episodes) |
| **GPU utilization (whole card during eval)** | **≈100%** (sustained) |
| **VRAM (whole card during eval)** | **38.68 / 47.98 GiB (80.6%)**, constant |
| └ Breakdown | jax policy preallocated ~36 GiB + gsplat rendering/MuJoCo EGL ~2.7 GiB, remaining ~9 GiB |
| gates | `strict_visual_shell_runtime=true`, `policy_requests=true`, `full_evaluation_recording=true` |

> The closed-loop evaluation runs end-to-end on a single gfx1100: BiGym simulation judges **5/50 episodes successful (10%)**, verifying the full chain of OpenPI π0.5 policy + calibrated 3DGS room shell + ROCm (JAX policy + gsplat rendering + MuJoCo) is usable. Training and evaluation action-horizon are consistent (h20).
>
> 🔭 **VRAM/GPU monitoring** (sampled during eval): `rocm-smi --showuse --showmeminfo vram --json` (equivalent to NVIDIA's `nvidia-smi`). Measured on this host during eval: GPU utilization 98–100%, VRAM constant at 38.68/47.98 GiB (jax preallocated ~36 GiB + gsplat/MuJoCo ~2.7 GiB).

### 4.4 3DGS Rendering (gsplat 1.4.0 + gfx1100, BiGym three cameras)

| Metric | Measured value |
| --- | --- |
| native gate | `GATE_OK True` / `DEVICE AMD Radeon Graphics` (patched gsplat 1.4.0) |
| shell activation | `VISUAL_SHELL_ACTIVE=True`, three-camera frames finite, head mean ~195 (bright kitchen shell) |
| Resolution | head 480×848, left/right wrist 480×640 |
| Rendering overhead during eval | ~2.7 GiB VRAM (coexists with jax on same card), no OOM triggered |
| Video encoding | `mpeg4` (Part 2) written to mp4 → **most players cannot play it**, must convert to H.264: `ffmpeg -i in.mp4 -an -c:v libx264 -pix_fmt yuv420p -movflags +faststart out.mp4` |

---

## 5. Key Pitfalls (Intrinsic to gfx1100 / ROCm 7.2.1 / jax0.6.0)

### 5.1 Training segfault (horizon=20, step 500–600) → `autotune_level=1`

- Symptom: Under `bs=4 horizon=20` default autotune, `SIGSEGV(139)` around step 500–600. Not OOM (VRAM still has headroom at crash time).
- Root cause: XLA's `gemm_fusion_autotuner` picks a bad gemm kernel flagged "Results do not match the reference" on gfx1100; horizon=20's action-expert sequence length triggers its segfault at that step.
- Solution: `XLA_FLAGS="--xla_gpu_autotune_level=1"` (keeps MIOpen conv autotuning, disables gemm-fusion autotuning). Measured: 0 such warnings after startup, the original crash point at step 600 passes, and it runs all the way to step 9860 before another (rare) segfault.
- Fallback for rare segfault: `run_train_loop.sh` (`save_interval=100 --resume` auto-resume).
- Complete stable training config: `PREALLOCATE=false MEM_FRACTION=0.99 XLA_FLAGS=--xla_gpu_autotune_level=1 --num-workers 0`.

### 5.2 Inference Must Use Default autotune (Otherwise All NaN); First Call May Occasionally segfault → Restart

- Starting inference with `autotune_level=1` → `/process_frame` returns **all NaN** (20×16). "Results do not match" actually means the **reference gemm is wrong on gfx1100**, and the autotuner instead picks the correct one; `level=1` forces reference → NaN.
- Default autotune → actions are finite and correct, zero segfaults across 1200+ consecutive calls.
- But the JIT compilation of the **cold-start first call** will **occasionally segfault** (same autotuner, h20 shape is more prone to trigger it) → **restart the service and retry** to pass.

### 5.3 action-horizon Must Match the Checkpoint

Training and evaluation action-horizon must be consistent; this repo's checkpoint and evaluation both use h20 (see §4.3).

### 5.4 Shell Branch

The default branch (A800) ≠ the eval-pinned `amd-rocm-w7900d-20260804` (W7900D real-camera calibration). The default version renders but is blurry, with offset camera landing points, dragging down the success rate.

### 5.5 gsplat bfloat16 / cooperative_groups

See §2.2. Modifying `hip/csrc/*` is ineffective (overwritten by hipify); you must edit the source `cuda/csrc/types.cuh`; cg::reduce is provided by gsplat's own `helpers.cuh`, so only place an empty shim.

---

## 6. Version Manifest (Measured Working)

```
# 策略服务 env (pi05)
jax            0.6.0          (AMD ROCm, rocm7.0.2, gfx1100 内核)
jaxlib         0.6.0
ml-dtypes      0.5.4          (★ jaxlib 0.6.0 必需)
torch          2.7.1+cpu      (★ 必须 CPU，避开双 ROCm 栈)
flax/orbax/chex 0.10.2/0.11.13/0.1.90
transformers   4.53.2

# 仿真客户端 env (bigym_3dgs)
torch          2.9.1+rocm6.4  (HIP 6.4 运行时, 前向兼容 ROCm 7.2.1)
gsplat         1.4.0          (+ rocm gfx1100 patch + §2.2 bfloat16 修复)
mujoco         3.10.0
dm_control     1.0.43
gaussian_renderer 0.2.0       (--no-deps)
bigym_plus     d1293768       (editable)
ROCm           7.2.1          (/opt/rocm, gfx1100)
```

## 7. Related

- Installation / training / inference (CPU torch path): [`amd_rocm_jax.md`](amd_rocm_jax.md)
- Evaluation lane source: `amd-bigym-3dgs-rocm` repo `evaluation/openpi-jax-bigym/` (`bin/` + `src/` + `VERSION_LOCK.json`)
- The original measured reports for training/inference/evaluation (including loss trajectory, segfault diagnostic chain, GPU sampling methodology) are provided with the deliverable.
