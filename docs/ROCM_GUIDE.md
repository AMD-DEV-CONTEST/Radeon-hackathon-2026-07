# ROCm / AMD GPU 适配指南

本指南说明如何在 AMD Radeon GPU + ROCm 环境下运行 3DGenerateFlow 的核心本地推理链路。

## 核心本地链路

```
单张照片
  → ROCmStyleProvider（本地 Stable Diffusion img2img 风格迁移）
  → ROCmDepthProvider（本地 Depth Anything V2 深度估计）
  → ROCmReliefProvider（CPU 几何处理生成 2.5D 浮雕 STL）
```

该链路不依赖闭源在线 3D API，可在 AMD Radeon GPU 上完整运行。

## 环境要求

- AMD Radeon GPU（建议显存 ≥ 8GB）
- ROCm 6.0 或兼容版本
- Ubuntu 22.04（推荐）或其他受 ROCm 支持的 Linux 发行版
- Python 3.10 / 3.11

## 快速安装

在项目根目录执行：

```bash
./rocm/setup_rocm.sh
```

该脚本会：
1. 检测并安装 ROCm 基础包
2. 创建 `.venv` 并安装 ROCm 版 PyTorch
3. 安装 `requirements-rocm.txt` 中的依赖
4. 预下载 HuggingFace 模型到 `services/api/models/hf_cache`

## 手动安装（若脚本不适用）

```bash
# 1. 安装 ROCm（Ubuntu 22.04 示例）
sudo apt update
sudo apt install rocm-dev rocm-hip-runtime rocminfo

# 2. 创建虚拟环境
cd services/api
python3 -m venv .venv
source .venv/bin/activate

# 3. 安装 ROCm 版 PyTorch
pip install torch==2.3.1+rocm6.0 torchvision==0.18.1+rocm6.0 \
    --index-url https://download.pytorch.org/whl/rocm6.0

# 4. 安装项目依赖
pip install -r requirements-rocm.txt

# 5. 下载模型
python ../../scripts/download_models.py
```

## 启动后端

```bash
cd services/api
source .venv/bin/activate
export USE_ROCM=true

CELERY_TASK_ALWAYS_EAGER=true \
CELERY_RESULT_BACKEND=cache+memory:// \
CELERY_TASK_EAGER_PROPAGATES=true \
PYTHONPATH=../.. \
uvicorn main:app --reload
```

## Docker 启动（推荐比赛环境）

```bash
# 需要主机已安装 ROCm 驱动并配置 docker 设备权限
docker compose -f docker-compose.rocm.yml up --build
```

## 验证 GPU 状态

浏览器打开 `http://localhost:5173`，页面右上角应显示 **AMD ROCm Ready** 徽章。

也可直接调用 API：

```bash
curl http://localhost:8000/health/gpu
```

预期返回示例：

```json
{
  "rocm_available": true,
  "hip_version": "6.0.0",
  "gpu_name": "AMD Radeon RX 7900 XTX",
  "gpu_count": 1,
  "gpu_memory_mb": 24576,
  "torch_cuda_available": true,
  "use_rocm_forced": false
}
```

## 运行基准测试

```bash
cd services/api
source .venv/bin/activate
export USE_ROCM=true
python ../../scripts/benchmark_rocm.py \
    --image ../../assets/sample_dog.png \
    --style relief_embossed
```

该脚本会输出：
- 风格迁移耗时
- 深度估计耗时
- 浮雕网格生成耗时
- 显存峰值

## 模型缓存

默认模型缓存目录：

```
services/api/models/hf_cache
```

可通过环境变量修改：

```bash
export HF_HOME=/path/to/cache
```

## 常见问题

### 1. `torch.cuda.is_available()` 返回 False

- 确认已安装 ROCm 并加载内核模块：`rocminfo` 应能看到 GPU
- 确认 PyTorch 是 ROCm 版：`python -c "import torch; print(torch.version.hip)"` 应输出 HIP 版本号
- 检查当前用户是否在 `render` 和 `video` 组

### 2. 显存不足

- 在 `adapters/rocm.py` 中降低 `max_image_size`（默认 768）
- 使用更小的模型（如 `depth-anything/Depth-Anything-V2-Small-hf`）
- 开启 `enable_model_cpu_offload`（已默认开启）

### 3. Docker 中无法访问 GPU

- 确认 `docker-compose.rocm.yml` 中映射了 `/dev/kfd` 和 `/dev/dri`
- 确认 docker 有访问权限：`sudo usermod -aG video,render $USER` 后重新登录

### 4. HuggingFace 下载慢

- 预先用 `scripts/download_models.py` 下载
- 设置镜像：`export HF_ENDPOINT=https://hf-mirror.com`
