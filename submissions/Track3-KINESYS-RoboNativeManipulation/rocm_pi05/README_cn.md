# openpi（ROCm 版 · 任意相机 + 一键训练/推理）

本仓库基于 [Physical Intelligence](https://www.physicalintelligence.company/) 的 openpi，针对 π05（π0.5）模型，面向 **AMD ROCm（gfx1100 / RDNA3）单卡** 做了落地交付改造：

- **ROCm-only**：安装/训练/推理全链路只走 AMD ROCm（系统 python3.12 + apt ffmpeg + `.venv`，gfx1100）。
- **功能一：任意相机数量**。π05 不再写死 3 个相机，支持 1–8 个（及更多）自由命名的相机；命令行声明「数据集哪些键对应哪个相机画面」即可。
- **功能二：一键训练 + HTTP 推理**。仓库根提供 `compute_norm_stats.py`、`train_jax.py`、`inference_server.py` 等入口脚本，全部纯 CLI，无需写 Python、无需改动 `src/openpi/training/config.py`。

> **两份配套文档（ROCm 实测）**
> - 安装 / 训练 / 推理（含显存与坑）：[docs/amd_rocm_jax.md](docs/amd_rocm_jax.md)
> - BiGym 带 3DGS 房间壳闭环评测 + 全链路性能基准：[docs/amd_rocm_bigym_eval.md](docs/amd_rocm_bigym_eval.md)

数据层采用 LeRobot Dataset v3.0（lerobot>=0.6.0），用 `--data-dir` 直接指向本地数据集目录。本仓库已实测的 BiGym 训练/评测数据由 [bigym_plus](https://github.com/WuChao-2024/bigym_plus) 生成（见各 doc）。

## 环境要求

| 模式 | 显存 | 已验证 GPU |
| --- | --- | --- |
| 推理 | > 8 GB | **AMD gfx1100（RX 7900 系列 / W7900D，RDNA3）** |
| 微调（LoRA） | > 22.5 GB | **AMD gfx1100（48 GiB，单卡 LoRA 已实测）** |
| 微调（全参） | > 70 GB | 需大显存卡（AMD 单卡暂不支持全参） |

在 Ubuntu + ROCm 7.2.1 上测试。**AMD ROCm（gfx1100 / RDNA3）是本仓库唯一主推且已验证的路线。**

## 安装（.venv + apt）

Ubuntu 24.04 自带 **python3.12**（AMD ROCm JAX 0.6.0 只发 cp312 wheel，正好匹配），`apt` 的 **ffmpeg 6.1.1** 落在 torchcodec 0.5 支持的 4–7 区间——所以系统 python + apt + 一个 `.venv` 就能把整套 ROCm 栈装起来，**无需 conda**。下面这条流程已在 gfx1100 / ROCm 7.2.1 上实测复现（apt ffmpeg → venv → JAX 见到 GPU → 归一化统计 → 训练 → HTTP 推理全跑通）。

```bash
git clone https://github.com/WuChao-2024/openpi_lerobot_plus openpi
cd openpi

# (1) apt：ffmpeg（视频解码）+ python3.12-venv。Ubuntu 24.04 的 ffmpeg 即 6.1.1（torchcodec 0.5 兼容）
sudo apt-get update
sudo apt-get install -y --no-install-recommends ffmpeg python3.12-venv

# (2) 建 venv（系统 python3.12）并升级 pip
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip

# (3) AMD ROCm JAX 0.6.0（repo.radeon.com 专有 wheel）+ jax/jaxlib/scipy/numpy
pip install \
  https://repo.radeon.com/rocm/manylinux/rocm-rel-7.0.2/jax_rocm7_pjrt-0.6.0-py3-none-manylinux_2_28_x86_64.whl \
  https://repo.radeon.com/rocm/manylinux/rocm-rel-7.0.2/jax_rocm7_plugin-0.6.0-cp312-cp312-manylinux_2_28_x86_64.whl \
  "jax==0.6.0" "jaxlib==0.6.0" "scipy>=1.11.1" "numpy>=1.26,<2.3.0"

# (4) ml-dtypes 0.5.4（--no-deps 防被拖回）
pip install --no-deps "ml-dtypes==0.5.4"

# (5) CPU torch / torchvision（避开 jax-rocm 与 torch-rocm 双 ROCm 运行时冲突）
pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.7.1" "torchvision==0.22.1"

# (6) openpi 生态依赖：requirements_rocm.txt 剥掉前几步已装的 jax/torch/ml-dtypes/lerobot
grep -v -E '^\s*(jax\[|jax==|jaxlib|ml-dtypes|torch==|torchvision|lerobot\[)|^https://repo.radeon.com' \
  requirements_rocm.txt > /tmp/req_rocm.txt
pip install -r /tmp/req_rocm.txt

# (7) lerobot 运行依赖 + torchcodec 0.5 CPU 构建
pip install "av==15.1.0" "datasets==4.8.5" "pyarrow==25.0.0" "pandas==2.3.3" \
            "draccus==0.10.0" "gymnasium==1.3.0" "jsonlines==4.0.0" \
            "opencv-python==4.11.0.86" "opencv-python-headless==4.11.0.86"
pip install --index-url https://pypi.org/simple "torchcodec==0.5"

# (8) lerobot（--no-deps 绕 hub 冲突）+ openpi editable（--no-deps 绕 pyproject 的 cuda 钉版）
pip install --no-deps "lerobot==0.6.0"
pip install -e . --no-deps

# (9) 打 PyTorch 后端的 transformers 补丁
cp -r src/openpi/models_pytorch/transformers_replace/* \
  "$(python -c 'import transformers,os;print(os.path.dirname(transformers.__file__))')"

# (10) 一次性把 ROCm 库路径写进 venv 激活钩子（等效 conda 的 activate.d）
cat >> .venv/bin/activate <<'EOF'
export LD_LIBRARY_PATH="/opt/rocm/lib:${LD_LIBRARY_PATH:-}"
EOF
```

前置：主机已装 ROCm（`/opt/rocm`），`rocminfo` 能识别 gfx1100。版本钉版与依赖清单在 `requirements_rocm.txt`。

之后每次新开 shell：`source .venv/bin/activate`（激活钩子已自动设好 `LD_LIBRARY_PATH=/opt/rocm/lib`，JAX 即可 dlopen `/opt/rocm/lib` 下的 HIP/MIOpen 库）。

**为什么不能一条 `pip install -r requirements_rocm.txt` 搞定**（上面分步就是为了绕这些坑）：

1. **lerobot 与 huggingface-hub 冲突**：lerobot 0.6.0 元数据声明 `huggingface-hub>=1.0`，但 transformers 4.53.2 与 requirements 都要 `<1.0`，pip resolver 直接报错。实际 lerobot 在 hub 0.36.x 可用（元数据过严），用 `--no-deps` 装 lerobot 绕过。
2. **ffmpeg 版本**：Ubuntu 24.04 的 apt 默认即 **ffmpeg 6.1.1**（`libavutil.so.59`），落在 torchcodec 0.5 支持的 4–7 区间，`apt install ffmpeg` 直接可用——无需像 conda 那样 pin（conda-forge 默认是 8，越界）。
3. **torchcodec 构建**：默认 index 会拉 `0.5+cu128`（依赖 `libnppicc`），用 `--index-url https://pypi.org/simple` 拉 CPU 构建 `torchcodec==0.5`。
4. **ml-dtypes 必须 0.5.4**：jaxlib 0.6.0 运行时要 `float4_e2m1fn`，0.4.1 没有会崩 `import jax`。
5. **torch 走 CPU**：避开 jax-rocm7 与 torch-rocm6.4 双 ROCm 运行时符号冲突。
6. **openpi 用 `--no-deps` 装**：绕开 pyproject 里上游遗留的 cuda 钉版（`jax[cuda12]==0.5.3`），保留本流程装的 AMD jax 0.6.0。

关键 pin（勿改）：`jax==0.6.0`（rocm7.0.2）、`jaxlib==0.6.0`、`ml-dtypes==0.5.4`、`torch==2.7.1+cpu`、`lerobot==0.6.0`、`transformers==4.53.2`、`huggingface-hub<1.0`、`numpy<2.3.0`、`ffmpeg 6.1.1`（apt）。

> 仓库仍附带 `install_rocm.sh`（conda 路线，旧）。本文档主推并已在 gfx1100 上实测复现的是上面的 **.venv + apt** 路线。
>
> **显存共存注意**：同一进程里 jax 会预占约 75% 显存从而挤占 torch。若同进程内有别的 GPU 负载需要把 JAX 挪到 CPU，设 `JAX_PLATFORMS=cpu`。

## pi05 基模 checkpoint

| 模型 | 用途 | 路径 |
| --- | --- | --- |
| pi05 | 微调基模 | gs://openpi-assets/checkpoints/pi05_base |

checkpoint 默认下载并缓存到 `~/.cache/openpi`，可用 `OPENPI_DATA_HOME` 覆盖。ROCm 主机上若无 GCP 凭据，`train_jax.py` 的匿名下载可能失败——先用 `python3 prefetch_base.py` 预填本地缓存（见入口脚本一览）。

## 入口脚本一览

仓库根的客户入口脚本（全部纯 CLI，不改动 `src/openpi/training/config.py`）：

| 脚本 | 作用 |
| --- | --- |
| compute_norm_stats.py | 手动计算 state/actions 归一化统计，写出 norm_stats.json |
| train_jax.py | **JAX 后端训练（主推）**，必传 --norm-stats |
| inference_server.py | 加载 checkpoint（JAX `params/`）起一个 HTTP 推理服务 |
| inference_post.py | inference_server.py 的 POST 接口处理逻辑（msgpack 解包→推理→打包） |
| inference_server_bigym.py | BiGym 评测专用适配器：适配 `/process_frame` 协议（评测端不改代码即可对接真实策略） |
| prefetch_base.py | ROCm 辅助：匿名从 GCS 预取 pi05_base 到本地缓存，避开 train_jax.py 的下载失败 |
| run_train_loop.sh | ROCm 辅助：训练自动 `--resume` 续跑，规避 gfx1100/jax0.6.0 偶发 gemm-fusion segfault |
| gpu_poll.py | ROCm 辅助：后台采样 `rocm-smi`，记录显存/GPU 占用 |

每个脚本各自独立、自带 argparse，不依赖任何共享模块：命令行参数在脚本内直接构造 openpi 的 `TrainConfig`（无 `config.py` 注册、无 dataclass）。训练与推理各自构造同一份 `Pi0Config`（相机顺序、动作维度必须一致），否则输入对不齐。

## 功能一：任意相机数量

### 原理

π05 的网络结构对相机数量无感知：视觉由一个共享 SigLIP 编码器逐图编码后拼接，位置编码（RoPE）按序列长度动态生成，没有任何与相机数量绑定的学习参数。改变相机数量不改变任何权重 shape，基模 checkpoint 可直接加载继续微调。

此前写死 3 个相机（`base_0_rgb / left_wrist_0_rgb / right_wrist_0_rgb`）只是数据/预处理层的硬编码。本仓库解除了这层硬编码：模型层按实际传入的相机集合处理，相机身份只取决于**输入顺序**。

### 用法：在命令行声明相机

相机的声明完全通过三个参数完成，对应底层 `CameraSpec(name, source, is_wrist)`：

- `--camera-names`：模型侧相机键，自由命名，可 1–8 个。整份列表的顺序就是模型 image-token 的顺序。
- `--camera-sources`：LeRobot 数据集里的拍平键路径，与 `--camera-names` 一一对应、同序。
- `--wrist-names`：`--camera-names` 的子集；其中的相机在训练时跳过几何增强（RandomCrop/Rotate），避免破坏腕部抓取参照点。

这三个参数在 `train_jax.py`、`inference_server.py` 里含义完全一致，保证训练与推理用的是同一份相机声明。`compute_norm_stats.py` 不需要相机参数——它只读 parquet 的 state/action 两列算统计量。

### 关键约束

- **相机顺序必须训练与推理一致**。相机身份只靠输入顺序，没有按相机名学习的参数。重命名相机无害，调换顺序有害。
- **腕部相机用 `--wrist-names` 声明，不靠名字**。旧逻辑按「名字是否含 wrist」决定增强，自由命名下已改为显式声明。
- 缺失的相机会被零填充并 mask 掉（pi05），因此用 ≤3 个相机时无需改动模型常量，复用现成的 mask 填充机制即可。

### 推理输入契约

推理客户端需发送一个 `images` 字典，键为相机名，值为 (H,W,3) uint8 图像：

```python
from openpi.policies.multi_camera_policy import make_multi_camera_example
example = make_multi_camera_example(("high", "l_wrist", "r_wrist"))
# example = {"images": {name: (224,224,3) uint8, ...}, "state": ..., "prompt": "..."}
action = policy.infer(example)["actions"]
```

## 任意 action 维度（机器人构型适配）

pi05_base 用 32 维 action 训练（openpi 官方注释："pi05 is trained with 32-dim actions"）。不同机器人 action 维度各异（BiGym 16 等），openpi 的适配方式是：**model 的 action 投影保持 32 维以匹配 base，数据侧 action 零填充到 32，推理输出再切片回机器人真实维度**。

两个参数分开控制：

| 参数 | 含义 |
| --- | --- |
| --action-dim | 机器人真实 action 维度（数据集/推理维度），如 BiGym 填 16 |
| --model-action-dim | base checkpoint 的 action 维度，默认 32（pi05_base）。model 的 action_in_proj/out_proj 用此维度，必须与 base 一致，否则加载时报 shape mismatch |

数据流：训练时 PadStatesAndActions 把 action 零填充到 --model-action-dim（32）匹配 base；归一化在填充前对原始维度进行（故 norm_stats 按机器人真实维度算）。推理时 MultiCameraOutputs 把 32 维输出切片回 --action-dim，客户端直接拿到机器人维度的 action。

多数情况只传 `--action-dim <机器人维度>`，`--model-action-dim` 用默认 32 即可。仅当换用其他 action_dim 的 base 时才需显式指定。

## 功能二：一键训练 + HTTP 推理

数据集用 `--data-dir` 指向一个本地 LeRobot Dataset v3.0 目录（含 `meta/`、`data/`、`videos/`），例如：

```
~/BiGym_Dev/data/bigym_plus/cupboards_close_all/
├── data/
│   └── chunk-000/
├── images/
│   ├── observation.images.cam_high/
│   ├── observation.images.cam_left_wrist/
│   └── observation.images.cam_right_wrist/
├── meta/
│   ├── episodes/
│   ├── info.json
│   ├── stats.json
│   └── tasks.parquet
├── videos/
│   ├── observation.images.cam_high/
│   ├── observation.images.cam_left_wrist/
│   └── observation.images.cam_right_wrist/
└── progress.json
```

下面用一个统一示例串起全流程：BiGym 的 3 相机数据集 `cupboards_close_all`（`cam_high` 外加左右腕部两个相机），动作维 16。先算归一化统计，再训练，最后起推理服务。

### 第 1 步：计算归一化统计（一次性，手动）

```bash
python3 compute_norm_stats.py \
    --data-dir ~/BiGym_Dev/data/bigym_plus/cupboards_close_all \
    --output-dir ./assets/cupboards_close_all
```

`compute_norm_stats.py` 是自包含脚本，只需 `--data-dir`（本地 LeRobot v3.0 目录）与 `--output-dir`：通过 lerobot 接口读 parquet 的 state/action 两列（不解码视频），逐帧全表算 mean/std/q01/q99。`--state-source`（默认 `observation.state`）与 `--action-source`（默认 `action`）可在数据集列名不同时覆盖。

产出 `./assets/cupboards_close_all/norm_stats.json`。数据集变更后需重算。

### 第 2 步：训练

> **AMD gfx1100 单卡**：跑 pi05 **必须 `--lora`**（全参单卡放不下），稳定配置为 `--lora --batch-size 4 --num-workers 0`（前缀 `XLA_PYTHON_CLIENT_MEM_FRACTION=0.9` 已在示例中）。**action-horizon 必须训练/推理/评测三者一致**：本仓库交付的演示权重与 BiGym 评测均为 **horizon 20**，故示例用 20（h20 训练在 gfx1100 偶发 segfault，需 `XLA_FLAGS=--xla_gpu_autotune_level=1`；推理**不可**设该 flag，否则输出全 NaN）。显存/GPU 占用、OOM 排查与续跑见 [docs/amd_rocm_jax.md](docs/amd_rocm_jax.md) §性能 与 [docs/amd_rocm_bigym_eval.md](docs/amd_rocm_bigym_eval.md) §5。

从官方 JAX 基模微调，权重经 `--base-checkpoint` 加载：

```bash
XLA_PYTHON_CLIENT_MEM_FRACTION=0.9 python3 train_jax.py \
    --action-dim 16 --action-horizon 20 \
    --camera-names high l_wrist r_wrist \
    --camera-sources observation.images.cam_high observation.images.cam_left_wrist observation.images.cam_right_wrist \
    --wrist-names l_wrist r_wrist \
    --data-dir ~/BiGym_Dev/data/bigym_plus/cupboards_close_all \
    --exp-name run1 --norm-stats ./assets/cupboards_close_all \
    --base-checkpoint gs://openpi-assets/checkpoints/pi05_base \
    --lora --batch-size 4 --num-workers 0 \
    --num-train-steps 20000 --overwrite
```

checkpoint 保存到 `checkpoints/<config_name>/<exp_name>/`，其中 `<config_name>` 默认取 `--data-dir` 的末段目录名（可用 `--config-name` 覆盖）。上面的示例即 `checkpoints/cupboards_close_all/run1/`。训练 `--num-train-steps 20000` 时，最终 checkpoint 落在 **19999** 步目录（步号从 0 计），故推理用 `--checkpoint-dir checkpoints/cupboards_close_all/run1/19999`。

常用训练参数（均可通过命令行覆盖）：

| 参数 | 默认 | 含义 |
| --- | --- | --- |
| --num-train-steps | 30000 | 总训练步数 |
| --batch-size | 32 | 全局 batch |
| --save-interval | 1000 | 每隔多少步存 checkpoint |
| --log-interval | 100 | 每隔多少步打印指标 |
| --peak-lr | 2.5e-5 | 余弦退火峰值学习率 |
| --warmup-steps | 1000 | 学习率 warmup 步数 |
| --decay-steps | 30000 | 余弦退火衰减步数 |
| --weight-decay | 1e-10 | AdamW 权重衰减 |
| --grad-clip | 1.0 | 梯度裁剪范数 |
| --fsdp-devices | 1 | JAX FSDP 切分设备数 |
| --overwrite | False | 覆盖已有 checkpoint 目录 |
| --resume | False | 从最近 checkpoint 续训 |
| --no-wandb | 启用 | 关闭 wandb 日志 |

完整参数列表见 `python3 train_jax.py --help`。

### 第 3 步：HTTP 推理服务

演示权重（已训练好的 pi05 LoRA，horizon 20，可直接下载用于推理 / BiGym 评测）：https://huggingface.co/WuChao-Cauchy/AMD_OpenSource_dishwasher_unload_cutlery_long_pi05_lora

`inference_server.py` 加载 checkpoint 并起一个 HTTP 服务；后端（JAX 的 `params/` 或 PyTorch 的 `model.safetensors`）由 checkpoint 目录自动识别，命令行用法两种后端完全一致。权重与 norm_stats 都从 `--checkpoint-dir` 加载。

```bash
python3 inference_server.py \
    --action-dim 16 --action-horizon 20 \
    --camera-names high l_wrist r_wrist \
    --camera-sources observation.images.cam_high observation.images.cam_left_wrist observation.images.cam_right_wrist \
    --wrist-names l_wrist r_wrist \
    --data-dir ~/BiGym_Dev/data/bigym_plus/cupboards_close_all \
    --checkpoint-dir checkpoints/cupboards_close_all/run1/19999 \
    --host 0.0.0.0 --port 8000
```

端点：

- `POST /infer`：body 为 msgpack 编码的观测字典，返回 msgpack 编码的动作字典。
- `GET /healthz`：存活探针。
- `GET /metadata`：策略元数据 JSON。

客户端调用（图像必须用 msgpack，不能用 JSON）：

```python
import requests
from openpi_client import msgpack_numpy as mn
from openpi.policies.multi_camera_policy import make_multi_camera_example

obs = make_multi_camera_example(("high", "l_wrist", "r_wrist"))
resp = requests.post(
    "http://<host>:8000/infer",
    data=mn.packb(obs),
    headers={"Content-Type": "application/msgpack"},
)
action = mn.unpackb(resp.content)
```

> BiGym 闭环评测（带 3DGS 房间壳）用的是 `inference_server_bigym.py` 的 `/process_frame` 协议 + 两进程评测客户端，完整步骤与性能基准见 [docs/amd_rocm_bigym_eval.md](docs/amd_rocm_bigym_eval.md)。

## 权重格式

本仓库的训练（`train_jax.py`）产出 JAX 权重（Orbax 目录树）：

| 内容 | 说明 |
| --- | --- |
| `<ckpt>/params/` | Orbax 权重目录树 |
| `<ckpt>/assets/<asset_id>/norm_stats` | 归一化统计（与训练时同一份） |

推理时 `inference_server.py` 从 `--checkpoint-dir` 加载 `params/` 与 norm_stats 即可。（`inference_server.py` 内部仍保留对 `model.safetensors` 的兼容检测，但本仓库已不再提供产生该 PyTorch 格式的训练 / 转换脚本。）

## 数据：LeRobot Dataset v3.0

训练数据采用 LeRobot Dataset v3.0 格式（lerobot>=0.6.0）。本仓库的入口脚本用 `--data-dir` 直接指向本地数据集目录（含 `meta/`、`data/`、`videos/`），lerobot 以该目录为 `root` 直接从磁盘加载，全程离线，不访问 Hugging Face Hub。数据集在整个管线里始终由这个本地路径定位，与网络无关。

BiGym 的训练/评测数据由 [bigym_plus](https://github.com/WuChao-2024/bigym_plus) 的录制/回放生成工具产出，直接落盘为上述 v3.0 目录结构，无需额外转换。已有的 v2.1 数据集可用官方转换工具升级：

```bash
python -m lerobot.scripts.convert_dataset_v21_to_v30 --repo-id <org>/<dataset>
```

归一化统计的计算与字段含义见 [docs/norm_stats.md](docs/norm_stats.md)。
