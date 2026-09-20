# AMD ROCm 上的 BiGym 3DGS 闭环评测与全链路性能基准（gfx1100 · RDNA3）

本文档是 `amd_rocm_jax.md`（安装 / 训练 / 推理）的**评测篇**补全：把 OpenPI JAX 策略、BiGym/MuJoCo 仿真与标定 3DGS 房间壳组成**两进程闭环评测**，并给出训练 / 推理 / 评测 / 渲染的**完整实测性能指标**。**仅针对 AMD ROCm**（gfx1100 / RDNA3，ROCm 7.2.1）。

> 测试主机：AMD gfx1100（RDNA3，96 CU，`rocm-smi` 报告 51.5 GiB VRAM，W7900D 级），ROCm 7.2.1 装于 `/opt/rocm`，单卡可见，EPYC 9334。
> 默认任务：`DishwasherUnloadCutleryLong`；π0.5 LoRA checkpoint。

---

## 0. 为什么是两个进程

JAX（策略）与 PyTorch/gsplat（仿真 + 3DGS 渲染）各自带一套 ROCm 运行时。**塞进同一个 Python 进程会触发 MIOpen/rocBLAS 符号冲突**。因此闭环评测拆成两个独立进程，单卡时分时共享 GPU：

| 进程 | 运行栈 | venv | 默认 GPU | 职责 |
| --- | --- | --- | --- | --- |
| 策略服务 | JAX ROCm 0.6.0（CPU torch） | `.venv`（openpi） | `POLICY_GPU=0` | 加载 Orbax LoRA，提供 `POST /process_frame` |
| 仿真客户端 | PyTorch ROCm + gsplat 1.4.0 + MuJoCo | `/path/to/bigym_3dgs-venv` | `SIM_GPU=0`（单卡时同卡） | MuJoCo 步进 + 严格三相机 3DGS 渲染 |

> 单卡（48 GiB 级）支持：两个进程顺序加载，评测前跑一次显存 gate（见 §4.3）。不要把 JAX 与 PyTorch/gsplat ROCm 同时 import 到一个进程。

---

## 1. 环境（两套，互不污染）

### 1.1 策略服务环境（openpi 的 `.venv`：JAX ROCm + CPU torch）

完全按 [`amd_rocm_jax.md` §1.1](amd_rocm_jax.md) 的 .venv + apt 流程建（即 [README 的「安装」节](../README.md)）：

```bash
git clone https://github.com/WuChao-2024/openpi_lerobot_plus openpi
cd openpi
# 跑 README §安装 的 10 步：apt ffmpeg + python3.12 -m venv .venv + 分步 pip + transformers 补丁 + activate 钩子
source .venv/bin/activate
# 验证: import jax; jax.devices() -> [RocmDevice(id=0)];  import torch; torch.version.hip is None（必须 CPU torch）
pip install flask      # 评测 adapter 用
```

要点（详见 `amd_rocm_jax.md`）：AMD ROCm JAX 0.6.0（`repo.radeon.com` rocm-rel-7.0.2，gfx1100 内核内嵌）+ `ml-dtypes==0.5.4`（jaxlib 0.6.0 运行时必需 `float4_e2m1fn`）+ **CPU torch 2.7.1**（避开双 ROCm 栈）。`.venv/bin/activate` 钩子已写好 `LD_LIBRARY_PATH=/opt/rocm/lib`。

### 1.2 仿真客户端环境 `bigym_3dgs`（PyTorch ROCm + gsplat + MuJoCo）

仿真 + 3DGS 渲染需要 GPU torch 与 gsplat。**独立建一个 venv，不要和 openpi 的 `.venv` 混**：

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

钉版理由：`mujoco==3.10.0`（与演示轨迹对齐，新版破坏已录 demo）、`dm_control==1.0.43`（1.0.44 要求 mujoco≥3.11）。numpy 2.x 即可（无 lerobot 则不钉 2.2.6）。

---

## 2. gsplat 1.4.0 在 gfx1100 / ROCm 7.2.1 上的编译修复（关键）

gsplat 1.4.0 的 HIP 内核在 **ROCm 7.2.1 + 公开 rocm6.4 torch** 上直接编不过。复现步骤与根因如下（这是本路线最硬的坑）：

### 2.1 装 gsplat + 打补丁 + 建 ROCm wrapper

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

### 2.2 根因与两处必要修复

编译错误与修复（**对 site-packages 里的 gsplat 源码做**）：

| 现象 | 根因 | 修复 |
| --- | --- | --- |
| `unknown type name '__hip_bfloat16'` | torch 的 `hipify` **每次构建从 `cuda/csrc/types.cuh` 重新生成 `hip/csrc/types.cuh`**，把 `__nv_bfloat16` 映射成 `__hip_bfloat16`；而 ROCm 7.2.1 已把它**重命名**为 `hip_bfloat16`。改 `hip/csrc/*` 没用（会被 hipify 覆盖）。 | 改**源头** `gsplat/cuda/csrc/types.cuh:33`：`OpType<__nv_bfloat16>` → `OpType<hip_bfloat16>`（hipify 对非 CUDA token 直接透传，输出即正确的 `hip_bfloat16`）。 |
| `'cooperative_groups/reduce.h' file not found` | gsplat 的 `.hip` include 了 CUDA 风格的 `cooperative_groups/reduce.h`，ROCm 7.2.1 只发 `hip/hip_cooperative_groups.h`。但 `cg::reduce/plus/greater` 其实由 **gsplat 自己的 `hip/csrc/helpers.cuh` 提供**。 | 放一个**空** `cooperative_groups/reduce.h` 到 include 路径即可（仅满足 `#include` 解析，不重复定义）。 |
| `-D__hip_bfloat16=hip_bfloat16`（曾尝试） | 全局宏别名会**破坏 ROCm 自身** `amd_hip_bf16.h`（内部区分 `__hip_bfloat16_raw` 与 `hip_bfloat16`）。 | **不要用 -D 宏**；用上面的源头改字。 |

具体命令：

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

### 2.3 验证 shell 真的渲染进 BiGym

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

## 3. 评测复现步骤（ROCm-only，端到端）

### 3.1 输入固定（VERSION_LOCK）

| 组件 | 固定值 |
| --- | --- |
| OpenPI 服务 | `WuChao-2024/openpi_lerobot_plus` commit `9a98f327` |
| BiGym 客户端 | `WuChao-2024/bigym_plus` commit `d1293768` |
| π0.5 checkpoint | `WuChao-Cauchy/pi05_ckpts` rev `b20a8efa`（或本地已下载的 `run1_lora_h20_20k/19999`） |
| AMD 3DGS 壳 | `eustance/amd-bigym-3dgs-kitchen-shell` **分支 `amd-rocm-w7900d-20260804`**（含 `scene-shell-profile.json` + 校准 `alignment.json` + 三层 PLY） |
| 评测 lane | `eust-w/amd-bigym-3dgs-rocm` 的 `evaluation/openpi-jax-bigym/`（`bin/` + `src/`） |

> ⚠️ 外壳**必须用 `amd-rocm-w7900d-20260804` 分支**（W7900D 实拍相机标定）。默认分支是为另一型号 GPU 校准的版本，`scene-shell-profile.json` 的 sha 对不上、且 `layer_files` 带失效的 `/scratch` 旧路径，渲染会偏糊/相机落点在捕获轨迹外。下载：`hf download eustance/amd-bigym-3dgs-kitchen-shell --repo-type dataset --revision amd-rocm-w7900d-20260804 --local-dir .../amd-kitchen-shell`。

### 3.2 终端 A：策略服务（默认 autotune，首次可能 segfault→重启重试）

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

> gfx1100 上**首次 `/process_frame` 的 JIT 编译偶发 SIGSEGV(139)**——XLA `gemm_fusion_autotuner` 随机挑到坏内核。**直接重启服务重试**即可（autotuner 非确定，重试大概率挑到好内核；warm 后稳定）。warm 后用一帧确认 `np.isfinite(chunk).all()` 且 `shape==(20,16)` 再开评测。

### 3.3 终端 B：仿真客户端跑闭环

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

> **action-horizon 必须与 checkpoint 训练一致**：`run1_lora_h20_20k/19999` 是 **h20** 训练的，评测须用 `--action-horizon 20`，且 lane 的 chunk-shape 校验需为 `(20,16)`（服务端 `inference_server_bigym_amd.py` + 客户端 `eval_bigym_3dgs.py`）。

产物：`results/<run>/dishwasher_unload_cutlery_long/episodes/episode-NNNNNN/{steps.jsonl, manifest.json, videos/{head,left_wrist,right_wrist}.mp4}` + `results.json` + `recording-validation.json` + `evaluation-summary.json`。

---

## 4. 完整性能基准（实测）

### 4.1 训练（pi05 LoRA，单卡 gfx1100，bs=4，action-horizon 20）

| 指标 | 实测值 | 说明 |
| --- | --- | --- |
| 模型 | pi05 LoRA（base 冻结 + 关 EMA） | `gemma_2b_lora` + `gemma_300m_lora` |
| 配置 | bs=4，horizon=20，20000 步目标，peak_lr 2.5e-5，warmup 1000 | |
| **稳态吞吐** | **1.2 s/it = 0.83 step/s = 3.33 samples/s** | 排除前 ~95 s 编译期 |
| **峰值显存** | **35.32 GiB**（稳态均值 33.65 GiB）/ 51.5 GiB | on-demand 采样；bs=4·h20·LoRA |
| **稳态 GPU 利用率** | **95.6%** | 539/565 采样 100%，余为步间/存盘间隙 |
| 1000 步 wall | ~20 min | 稳态 1000×1.2 s + ~90 s 编译 + 末尾存盘 |
| loss 轨迹 | 0.2649 → ~0.0165 平台（单调下降） | step0 0.2649 / 1k 0.043 / 5k 0.0228 / 9k 0.0168 |
| 稳定配置 | `PREALLOCATE=false MEM_FRACTION=0.99 XLA_FLAGS=--xla_gpu_autotune_level=1 --num-workers 0` | ★ 见 §5.1 |

### 4.2 推理（pi05 LoRA，单卡，batch 1，action-horizon 20）

| 指标 | 实测值 | 说明 |
| --- | --- | --- |
| **端到端延迟** | **239.8 ms/call（评测实测 243.7 ms，p50 216 / p95 284 / max 441）** | 含 PNG 解码 + HTTP + pi05 前向 |
| 模型前向（去 HTTP/解码） | ~150–180 ms | `policy.infer` 的 `policy_timing.infer_ms` |
| **吞吐** | **~4.17 calls/s** | 持续 burst |
| **峰值显存** | **10.03 GiB**（稳态 9.44 GiB，on-demand 测真实工作集） | 权重 + JIT buffer |
| 部署常驻显存 | ~36–40 GiB | 默认 preallocate（`MEM_FRACTION=0.75`≈36 GiB）时空转也占 |
| autotune | **必须默认**（`level=1` 会让采样输出**全 NaN**） | gfx1100 / jax0.6.0 固有 |

### 4.3 闭环评测（DishwasherUnloadCutleryLong，单卡共享，ckpt 19999）

| 指标 | 实测值 |
| --- | --- |
| **成功率** | **5/50 = 10.0%** |
| policy 请求数 | 2622 |
| 延迟 ms（mean/p50/p95/max） | 243.7 / 216.2 / 283.6 / 441.3 |
| 总 transitions | 51646（50 集） |
| **GPU 利用率（评测期整卡）** | **≈100%**（持续） |
| **显存（评测期整卡）** | **38.68 / 47.98 GiB（80.6%）**，恒定 |
| └ 构成 | jax 策略预占 ~36 GiB + gsplat 渲染/MuJoCo EGL ~2.7 GiB，余 ~9 GiB |
| gates | `strict_visual_shell_runtime=true`、`policy_requests=true`、`full_evaluation_recording=true` |

> 闭环评测在单卡 gfx1100 上端到端跑通：BiGym 仿真判定 **5/50 集任务成功（10%）**，验证 OpenPI π0.5 策略 + 标定 3DGS 房间壳 + ROCm（JAX 策略 + gsplat 渲染 + MuJoCo）全链路可用。训练与评测的 action-horizon 一致（h20）。
>
> 🔭 **显存/GPU 监控**（评测期采样）：`rocm-smi --showuse --showmeminfo vram --json`（对应 NVIDIA 的 `nvidia-smi`）。本机评测期实测：GPU 利用率 98–100%、显存 38.68/47.98 GiB 恒定（jax 预占 ~36 GiB + gsplat/MuJoCo ~2.7 GiB）。

### 4.4 3DGS 渲染（gsplat 1.4.0 + gfx1100，BiGym 三相机）

| 指标 | 实测值 |
| --- | --- |
| native gate | `GATE_OK True` / `DEVICE AMD Radeon Graphics`（patched gsplat 1.4.0） |
| shell 激活 | `VISUAL_SHELL_ACTIVE=True`，三相机帧 finite、head 均值 ~195（明亮厨房壳） |
| 分辨率 | head 480×848，左/右腕 480×640 |
| 评测期渲染开销 | ~2.7 GiB VRAM（与 jax 同卡共存），不触发 OOM |
| 视频编码 | `mpeg4`（Part 2）写入 mp4 → **多数播放器放不了**，需转 H.264：`ffmpeg -i in.mp4 -an -c:v libx264 -pix_fmt yuv420p -movflags +faststart out.mp4` |

---

## 5. 关键坑（gfx1100 / ROCm 7.2.1 / jax0.6.0 固有）

### 5.1 训练 segfault（horizon=20，step 500–600）→ `autotune_level=1`

- 现象：`bs=4 horizon=20` 默认 autotune 下，~step 500–600 `SIGSEGV(139)`。非 OOM（崩时 VRAM 还有余）。
- 根因：XLA `gemm_fusion_autotuner` 在 gfx1100 挑出 "Results do not match the reference" 的错误 gemm 内核，horizon=20 的 action-expert 序列长度在该步触发它 segfault。
- 解法：`XLA_FLAGS="--xla_gpu_autotune_level=1"`（保留 MIOpen conv 自动调优、关掉 gemm-fusion 自动调优）。实测启动后 0 条该警告、step 600 原崩溃点通过，一路到 step 9860 才再（罕见）segfault。
- 兜底罕见 segfault：`run_train_loop.sh`（`save_interval=100 --resume` 自动续跑）。
- 完整稳定训练配置：`PREALLOCATE=false MEM_FRACTION=0.99 XLA_FLAGS=--xla_gpu_autotune_level=1 --num-workers 0`。

### 5.2 推理必须默认 autotune（否则全 NaN）；首调用偶发 segfault→重启

- `autotune_level=1` 起推理 → `/process_frame` 返回**全 NaN**（20×16）。"Results do not match" 其实是说**reference gemm 在 gfx1100 是错的**，autotuner 反而挑到对的；`level=1` 强制 reference → NaN。
- 默认 autotune → 动作有限正确，连续 1200+ 次调用零 segfault。
- 但**冷启动首调用**的 JIT 编译会**偶发 segfault**（同 autotuner，h20 形状更易触发）→ **重启服务重试**即过。

### 5.3 action-horizon 必须匹配 checkpoint

训练与评测的 action-horizon 必须一致；本仓库 checkpoint 与评测均用 h20（见 §4.3）。

### 5.4 外壳分支

默认分支（A800）≠ 评测 pin 的 `amd-rocm-w7900d-20260804`（W7900D 实拍标定）。默认版能渲染但偏糊、相机落点偏，拉低成功率。

### 5.5 gsplat bfloat16 / cooperative_groups

见 §2.2。改 `hip/csrc/*` 无效（hipify 覆盖），必须改 `cuda/csrc/types.cuh` 源头；cg::reduce 由 gsplat 自带 `helpers.cuh` 提供，只放空垫片。

---

## 6. 版本清单（实测可用）

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

## 7. 相关

- 安装 / 训练 / 推理（CPU torch 路线）：[`amd_rocm_jax.md`](amd_rocm_jax.md)
- 评测 lane 源码：`amd-bigym-3dgs-rocm` 仓库 `evaluation/openpi-jax-bigym/`（`bin/` + `src/` + `VERSION_LOCK.json`）
- 训练/推理/评测的原始实测报告（含 loss 轨迹、segfault 诊断链、GPU 采样方法）随交付提供。
