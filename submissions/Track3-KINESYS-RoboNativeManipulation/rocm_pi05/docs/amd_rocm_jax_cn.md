# openpi 在 AMD ROCm 上的 JAX 训练 / 推理（gfx1100 · RDNA3）

本文档是 openpi 在 AMD ROCm（gfx1100 / RDNA3）上的**唯一主推路径**：.venv + apt 安装、训练 / 推理用法、以及训练与推理时的显存与 GPU 计算占用性能指标。主推 `.venv + apt`（无需 conda）；仓库另附 `install_rocm.sh` 作为 conda 备选路线。

> 测试主机：AMD gfx1100（RX 7900 系列 / RDNA3），ROCm 7.2.1 装于 `/opt/rocm`，单卡报告 VRAM 51.5 GiB。
> 测试模型：pi05 LoRA 微调（`gemma_2b_lora` + `gemma_300m_lora`，base 冻结），3 相机（cam_high 480×848 + 左/右腕 480×640），action-dim 16，action-horizon 10。
>
> 📗 **配套评测篇**：带 3DGS 房间壳的 BiGym **闭环评测**（两进程架构）+ **gsplat-on-AMD 编译修复** + **训练/推理/评测/渲染全链路性能基准** + autotune-segfault/h10-vs-h20 等关键坑，见 [`amd_rocm_bigym_eval.md`](amd_rocm_bigym_eval.md)。

---

## 0. 总览

| 维度 | AMD / ROCm 路线（本仓库唯一主推） |
| --- | --- |
| 安装 | **系统 python3.12 + apt ffmpeg + `.venv`**（Ubuntu 24.04；见 §1.1） |
| 依赖清单 | `requirements_rocm.txt` |
| JAX | **AMD ROCm JAX 0.6.0**（rocm7.0.2，`repo.radeon.com` 专有 wheel） |
| jaxlib | PyPI `jaxlib==0.6.0` + AMD `jax_rocm7_pjrt`/`jax_rocm7_plugin` |
| torch | `torch==2.7.1` **CPU**（训练 GPU 算力由 JAX 承担；CPU torch 避开双 ROCm 运行时冲突） |
| ml-dtypes | **0.5.4**（jaxlib 0.6.0 运行时需要 `float4_e2m1fn`） |
| ffmpeg | **apt 6.1.1**（Ubuntu 24.04 默认；torchcodec 0.5 兼容 4–7，无需 pin） |
| GPU 可见性 | `ROCR_VISIBLE_DEVICES` |
| venv 激活 | `source .venv/bin/activate`（激活钩子自动设 `LD_LIBRARY_PATH=/opt/rocm/lib`） |

关键点：openpi 用 `pip install -e . --no-deps` 绕开 pyproject 里上游遗留的 cuda 钉版（`jax[cuda12]==0.5.3`），保留 AMD jax 0.6.0。pyproject 的 `[tool.uv] override-dependencies` 设 `ml-dtypes==0.5.4`——jaxlib 0.6.0 对 ml-dtypes 无上限（`>=0.2.0`），故 0.5.4 对 pip 与 uv 都安全。

JAX 在本机**确实可用**：AMD 官方 ROCm 7.x 的 JAX 后端显式编译了 `gfx1100` 内核（解包 `jax_rocm7_plugin`/`jax_rocm7_pjrt` 的 `.so` 后 grep 到 `gfx1100`、`gfx1101`、`gfx1150`、`gfx1200` 等）。

---

## 1. 环境配置

### 1.1 安装（.venv + apt，无需 conda）

Ubuntu 24.04 自带 **python3.12**（AMD jax 0.6.0 只发 cp312 wheel，正好匹配），apt 的 **ffmpeg 6.1.1** 落在 torchcodec 0.5 兼容区间（4–7）内，所以系统 python + apt + 一个 `.venv` 就能装起整套 ROCm 栈。完整可复制命令见 [README 的「安装」节](../README.md)；要点：

```bash
sudo apt-get install -y ffmpeg python3.12-venv          # Ubuntu 24.04: ffmpeg 6.1.1
python3.12 -m venv .venv && source .venv/bin/activate
# 分步 pip：AMD ROCm JAX → ml-dtypes → CPU torch → requirements → lerobot deps → openpi(-e --no-deps)
# ROCm 库路径一次性写进 .venv 激活钩子（等效 conda 的 activate.d）：
echo 'export LD_LIBRARY_PATH="/opt/rocm/lib:${LD_LIBRARY_PATH:-}"' >> .venv/bin/activate
```

前置：主机已装 ROCm（`/opt/rocm`），`rocminfo` 能识别 gfx1100。

流程做的事（10 步，详见 README）：

1. `apt install ffmpeg python3.12-venv`（Ubuntu 24.04 的 ffmpeg 即 6.1.1，torchcodec 0.5 兼容；只有 conda 路线才需 pin=7 绕开 conda-forge 的 8）。
2. `python3.12 -m venv .venv`（系统 python3.12；AMD jax 0.6.0 只发 cp312 wheel，必须 3.12）。
3. **AMD ROCm JAX**：装两个 AMD wheel（`jax_rocm7_pjrt` + `jax_rocm7_plugin`，0.6.0/cp312）+ `jax==0.6.0 jaxlib==0.6.0 scipy numpy`。
4. **`ml-dtypes==0.5.4`**（`--no-deps` 防被拖回）。★ jaxlib 0.6.0 运行时要 `float4_e2m1fn`，ml-dtypes 0.4.1 没有会崩 `import jax`，**这是 AMD 路线最隐蔽的坑**。
5. **CPU torch / torchvision**（`--index-url .../whl/cpu`）：训练 GPU 算力是 JAX，torch 只做数据管线；CPU 路线避开 jax-rocm7 与 torch-rocm6.4 双 ROCm 运行时符号冲突。
6. openpi 生态依赖：从 `requirements_rocm.txt` 剥掉 AMD jax/torch/ml-dtypes/lerobot 那几行后 `pip install -r`（flax/orbax/chex/transformers 等；optax 由 flax 传递依赖拉入）。
7. lerobot 运行依赖（av/datasets/pyarrow/pandas/draccus/jsonlines/opencv，CPU）+ `torchcodec==0.5` CPU 构建。
8. `lerobot==0.6.0 --no-deps`（绕 hub>=1.0 元数据冲突）+ `pip install -e . --no-deps`（★ `--no-deps`：绕开 pyproject 的 `jax[cuda12]==0.5.3`，保留 AMD jax 0.6.0）。
9. 打 transformers 补丁。
10. 把 `export LD_LIBRARY_PATH=/opt/rocm/lib:...` 写进 `.venv/bin/activate`（之后每次 `source .venv/bin/activate` 自动生效）。

### 1.2 为什么是 JAX 0.6.0（rocm7.0.2）

AMD 不在 PyPI 发布 ROCm JAX，只在 `https://repo.radeon.com/rocm/manylinux/rocm-rel-X/` 发若干版本：

| ROCm rel | jax 版本 | 可用 Python | gfx1100 内核 | 对 openpi 适用性 |
| --- | --- | --- | --- | --- |
| rocm-rel-6.4.x | 0.4.35 | cp310, cp312 | — | ❌ orbax 0.11.13 要 `jax>=0.5.0` |
| **rocm-rel-7.0.2** | **0.6.0** | cp310, **cp312** | ✅ | ⚠️ 仅 cp312（openpi 要 py≥3.11） |
| rocm-rel-7.2.1 / 7.2.4 | 0.8.2 | cp311, cp312 | ✅ | 离 fork 钉的 0.5.3 太远（3 个 minor），flax/orbax/chex 要级联升级，风险高 |

`0.6.0` 是同时满足「orbax ≥0.5.0 下限」且「离 fork 生态最近」的唯一选择。代价：放弃可选 RLDS 数据集组（`rlds` 组的 `tensorflow-cpu==2.15.0` 只发 cp311，py3.12 装不了——**不影响 pi05 核心训练/推理**）。

### 1.3 安装后验证

```bash
source .venv/bin/activate        # 激活钩子自动设好 LD_LIBRARY_PATH=/opt/rocm/lib
python -c "import jax; print(jax.__version__); print(jax.devices())"
#   期望: 0.6.0  /  [RocmDevice(id=0)]
python -c "import jax.numpy as jnp; x=jnp.ones((1024,1024)); print((x@x).sum())"   # 小算力烟测
python train_jax.py --help     # 期望 EXIT=0（完整模型/import 链加载）
```

若 JAX 报 "unsupported gfx / no GPU device" 兜底（本机 `rocminfo` 已识别 gfx1100 时通常不需要）：
```bash
export HSA_OVERRIDE_GFX_VERSION=11.0.0
```

### 1.4 torch：CPU 还是 GPU？

- **CPU 路线（默认，`.venv` 流程采用）**：避开双 ROCm 运行时冲突，数据管线瓶颈在 GPU 上的 JAX，CPU 足够。
- **GPU 路线（可选）**：本机 bigym 环境已验证 `torch 2.9.1+rocm6.4` 在 gfx1100 可用（`torch.cuda.is_available()==True`）。若要让 torch 也用 GPU，单独装后跑一次 `import torch; torch.cuda.is_available()`；若与 JAX 同进程报 MIOpen/rocBLAS 符号错，回退 CPU。
- **GPU 共存**：JAX 默认预分配约 75% VRAM。若同进程内有别的 GPU 负载需要把 JAX 挪到 CPU，设 `JAX_PLATFORMS=cpu`。

---

## 2. 使用细节

### 2.1 base checkpoint（pi05_base）获取 —— GCS 匿名缓存坑

**推荐：仓库自带 `prefetch_base.py` 可一键完成下述匿名预取**（已处理好缓存路径）。下面给出手动步骤与根因，便于离线 / 排查。

`train_jax.py --base-checkpoint gs://openpi-assets/checkpoints/pi05_base/params` 会触发 `download.maybe_download(path)`。该函数对 `openpi-assets` 桶**优先走 `gsutil`**（多数 AMD 主机没装）→ 回退 `gcsfs`，但 `CheckpointWeightLoader` 调用时**没传 `token="anon"`** → 在无 GCP 凭据的主机上失败。

桶本身**公开**（约 12.4 GB 的 orbax ocdbt checkpoint）。解法：用匿名 fsspec 把 `params/` 预下到 openpi 的本地缓存路径，之后 `maybe_download` 命中本地缓存直接返回，训练时零网络：

```python
# 在 venv 里跑一次（source .venv/bin/activate 后）
import fsspec, pathlib, os
src = "openpi-assets/checkpoints/pi05_base/params"
dst = pathlib.Path(os.path.expanduser("~/.cache/openpi/openpi-assets/checkpoints/pi05_base/params")).resolve()
dst.parent.mkdir(parents=True, exist_ok=True)
if (dst/"_METADATA").exists() or (dst/"manifest.ocdbt").exists():
    print("cache already present:", dst); raise SystemExit
fs = fsspec.filesystem("gs", token="anon")          # ★ 关键：匿名 token
print("du bytes:", fs.du(src))
partial = dst.parent / "pi05_base_params.partial"
fs.get(src, str(partial), recursive=True)             # ~12GB
partial.rename(dst)
print("DONE ->", dst)
```

缓存路径来自 `maybe_download` 的 `cache_dir/<netloc>/<path>` 规则：`gs://openpi-assets/checkpoints/pi05_base/params` → `~/.cache/openpi/openpi-assets/checkpoints/pi05_base/params`。验证：该目录需含 `_METADATA`、`manifest.ocdbt`、`_sharding`、`d/`。

### 2.2 计算归一化统计（一次性）

```bash
python compute_norm_stats.py \
    --data-dir /path/to/lerobot_dataset \
    --output-dir ./assets/<dataset_name>
# 产物: ./assets/<dataset_name>/norm_stats.json，键 state / actions
# 离线读 parquet，不解码视频；只用到数据集目录 + state/action 列名
```

### 2.3 训练（`train_jax.py`）

单卡 gfx1100（~48 GiB VRAM）跑 pi05 **必须用 LoRA**（冻结 base，只训适配器），全参微调单卡放不下。训练命令本身厂商无关，与 README 的训练示例一致，仅在环境变量与单卡配置上为 AMD 调优：

```bash
XLA_PYTHON_CLIENT_MEM_FRACTION=0.9 python train_jax.py \
    --action-dim 16 --action-horizon 10 --model-action-dim 32 \
    --camera-names high l_wrist r_wrist \
    --camera-sources observation.images.cam_high \
                    observation.images.cam_left_wrist \
                    observation.images.cam_right_wrist \
    --wrist-names l_wrist r_wrist \
    --data-dir /path/to/lerobot_dataset \
    --exp-name run1_lora \
    --norm-stats ./assets/<dataset_name> \
    --base-checkpoint gs://openpi-assets/checkpoints/pi05_base/params \
    --lora \
    --num-train-steps 4000 --batch-size 4 --save-interval 500 \
    --log-interval 50 --num-workers 0 --overwrite
```

要点：
- `--model-action-dim 32` 必须等于 pi05_base 的 action_dim（32），勿改；数据集动作 zero-pad 到 32，推理再切回 `--action-dim`。
- `--lora`：单卡必选；同时冻结 base、关闭 EMA。
- 训练与推理的 `Pi0Config`（相机顺序 / action_dim / action_horizon / lora 变体）**必须一致**，否则输入不对齐。
- 单卡稳定配置：`--batch-size 4 --num-workers 0 XLA_PYTHON_CLIENT_MEM_FRACTION=0.9`（详见 §3.3 OOM 排查）。
- wandb 默认关；要开先 `wandb login` 再加 `--wandb`。
- checkpoint 落在 `./checkpoints/<config_name>/<exp_name>/<step>/`（`config_name` 默认取 `--data-dir` 的 basename），含 `params/`（orbax）与 `assets/<asset_id>/norm_stats.json`。

### 2.4 推理服务（`inference_server.py`）

openpi 自带服务使用 **msgpack** 协议（不是 JSON）：

```bash
python inference_server.py \
    --action-dim 16 --action-horizon 10 --model-action-dim 32 \
    --camera-names high l_wrist r_wrist \
    --camera-sources observation.images.cam_high observation.images.cam_left_wrist observation.images.cam_right_wrist \
    --wrist-names l_wrist r_wrist \
    --data-dir /path/to/lerobot_dataset \
    --checkpoint-dir ./checkpoints/<config_name>/<exp_name>/<final_step> \
    --lora --default-prompt "<训练用的 prompt>" \
    --host 0.0.0.0 --port 8000
```

- `--checkpoint-dir` 指向 **step 目录**（含 `params/` 与 `assets/`）；JAX / PyTorch 后端自动探测。
- norm_stats 从 `checkpoint_dir/assets/<asset_id>/norm_stats.json` 加载（asset_id = 数据集 basename）。
- 端点：`POST /infer`（msgpack obs → msgpack action）、`GET /healthz`、`GET /metadata`。
- 客户端编码图像用 `openpi_client.msgpack_numpy`（不能 JSON，uint8 图像数组 JSON 无法承载）：

```python
import requests, openpi_client.msgpack_numpy as mn
obs = {
    "state": state16,                          # np.float32, 16 维
    "images": {"high": rgb_high, "l_wrist": rgb_l, "r_wrist": rgb_r},  # HxWx3 uint8 RGB
    "prompt": "your prompt",
}
r = requests.post("http://host:8000/infer", data=mn.packb(obs),
                  headers={"Content-Type": "application/msgpack"})
action = mn.unpackb(r.content)                # {"state":..., "actions": (action_horizon,16), ...}
```

图像约定：`data["images"][name]` 为 **H×W×3 uint8 RGB**（`MultiCameraInputs` 也接受 CHW 自动转 HWC、浮点自动 ×255）；`ResizeImages(224,224)` 在服务端内部缩放，客户端可发原始分辨率。

### 2.5 多卡

本机为单卡 gfx1100，JAX 默认占用该卡（GPU 可见性由 `ROCR_VISIBLE_DEVICES` 与驱动决定）。多卡主机可：

- 限定可见卡：`export ROCR_VISIBLE_DEVICES=0,1`。
- 数据/模型并行：`train_jax.py --fsdp-devices <N>`（JAX FSDP 分片数，默认 1）。
- JAX 预分配：`XLA_PYTHON_CLIENT_MEM_FRACTION=<0..1>` 控制单卡预分配上限；`XLA_PYTHON_CLIENT_PREALLOCATE=false` 改按需分配（牺牲一点吞吐换显存余量）。

---

## 3. 性能指标（实测）

### 3.1 训练（pi05 LoRA，单卡 gfx1100，48 GiB VRAM）

| 指标 | 实测值 | 说明 |
| --- | --- | --- |
| 模型配置 | pi05 LoRA（base 冻结） | `gemma_2b_lora` + `gemma_300m_lora` |
| 相机 | 3 路（cam_high 480×848 + 左/右腕 480×640） | resize 到 224 喂模型 |
| batch-size | 4 | 单卡 LoRA 下的稳定上限，见 3.3 |
| 显存上限 | `XLA_PYTHON_CLIENT_MEM_FRACTION=0.9`（≈46.4 GiB） | 默认 0.75（≈38.6 GiB）在 batch≥8 时触顶 OOM |
| **峰值显存** | **45.29 GiB / 51.5 GiB（≈88%）** | rocm-smi 1457 次采样最大值 |
| **稳态 GPU 利用率** | **≈100%** | 1093/1093 采样 100%，仅启停阶段有 0% |
| 吞吐 | **≈1.2 s/it** | 4000 步 ≈ 81 分钟 |
| loss | 单调下降，grad_norm 收敛到 ~0.2 | 每 `--log-interval` 打印 `Step N: loss=.. grad_norm=.. param_norm=..` |
| 非致命告警 | XLA `gemm_fusion_autotuner` 报 "Results do not match the reference" | 数值精度警告，训练正常越过，不影响收敛 |

### 3.2 推理（pi05 LoRA，单卡，batch 1）

| 指标 | 实测值 | 说明 |
| --- | --- | --- |
| 服务常驻显存 | **≈40 GiB**（默认预分配 75%≈38.6 GiB + 模型权重） | 进程启动后即占用，与是否在推理无关 |
| 单次推理增量显存 | 可忽略（batch 1） | 峰值≈常驻 |
| **端到端延迟** | **≈208 ms / 次 `/infer`** | 含 PNG 解码 + HTTP + pi05 LoRA 前向；返回 10 步 action chunk |
| 模型前向（去 HTTP/解码） | 约 150–180 ms | `policy.infer` 返回的 `policy_timing.infer_ms` |
| 非致命告警 | 同训练：gemm autotuner 数值精度警告 | 不影响输出 |

> 训练用 `MEM_FRACTION=0.9`；推理可不设（默认 0.75 已够 batch-1）。推理若与其他 GPU 进程共驻，调小 `XLA_PYTHON_CLIENT_MEM_FRACTION` 留余量。监控显存与利用率用 `rocm-smi --showmeminfo vram --showuse`（对应 NVIDIA 的 `nvidia-smi`）。

### 3.3 OOM / 稳定性排查记录（重要经验）

单卡 48 GiB 跑 pi05 LoRA，**不是任何 batch 都能起**。实测（3 路 480×848/640 相机）：

| 配置 | 结果 | 原因 |
| --- | --- | --- |
| `--batch-size 16`，默认预分配 | ~step8 被 SIGKILL（无 Python 栈） | 峰值 ~40 GiB 超过默认 75% 预分配上限（~38.6 GiB）→ XLA 直接杀进程 |
| `--batch-size 8` + `PREALLOCATE=false` | step0 autotuning/编译期崩 | 按需分配在 ROCm/XLA 上不稳定 |
| `--batch-size 8`，默认预分配 | ~step3 崩 | 显存余量紧 |
| **`--batch-size 4` + `--num-workers 0` + `MEM_FRACTION=0.9`** | ✅ 稳定跑到 4000 步 | 见下 |

**稳定配置**：`--batch-size 4`、`--num-workers 0`、`XLA_PYTHON_CLIENT_MEM_FRACTION=0.9`。

经验判断：
1. 这些崩溃多为 **ROCm/XLA 的硬杀（SIGKILL，无 Python OOM 异常）**，不会抛 `RESOURCE_EXHAUSTED`——排查时别只盯 Python 栈，要看 `dmesg`/进程是否被 OOM killer 或 XLA 杀。
2. 主要诱因是**数据加载 worker 子进程**（`--num-workers>0`）与紧显存叠加；`--num-workers 0` + 放大托管池（`MEM_FRACTION=0.9`）解决。数据集很小时 `num-workers 0` 几乎不掉吞吐。
3. 显存吃紧时优先级：先降 `--batch-size` → 再设 `XLA_PYTHON_CLIENT_MEM_FRACTION` 逼近上限 → 仍不行才关 `PREALLOCATE`（最后手段，ROCm 上不稳定）。
4. 多相机高分辨率（如 3×480×848）会显著抬高每样本激活显存；必要时在数据管线先把图像缩小再喂模型（注意训练/推理一致）。

---

## 附：版本清单（已实测可用）

```
jax            0.6.0          (AMD ROCm, rocm7.0.2)
jaxlib         0.6.0
ml-dtypes      0.5.4          (★ jaxlib 0.6.0 必需，勿用 0.4.1)
flax           0.10.2         (传递依赖拉入 optax 0.2.8)
orbax-checkpoint 0.11.13
chex           0.1.90
torch          2.7.1+cpu
torchvision    0.22.1+cpu
torchcodec     0.5            (CPU 构建)
lerobot        0.6.0          (--no-deps 绕 hf-hub 冲突)
transformers   4.53.2
huggingface-hub 0.36.2
numpy          2.2.6
ffmpeg         6.1.1          (apt, Ubuntu 24.04)
openpi         0.1.0          (editable, --no-deps)
```
