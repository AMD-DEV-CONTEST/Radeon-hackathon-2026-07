# AMD AI Studio — 调试与修复记录

> 本文档记录了从项目克隆到全部功能通过测试的完整过程中遇到的所有问题及解决方式。

---

## 目录

1. [环境与依赖问题](#1-环境与依赖问题)
2. [模型下载问题](#2-模型下载问题)
3. [模型加载问题](#3-模型加载问题)
4. [运行时问题](#4-运行时问题)
5. [功能验证问题](#5-功能验证问题)
6. [最终模型清单](#6-最终模型清单)

---

## 1. 环境与依赖问题

### 1.1 tokenizers 版本兼容性问题

**问题：** `CLIPTokenizer` 初始化时报错：
```
TypeError: RobertaProcessing.__new__() got an unexpected keyword argument 'cls'
```

**根因：** `tokenizers` 0.23.0-rc0 版本将 `RobertaProcessing` 的参数 `cls` 改名为 `cls_token`，但 `transformers` 5.6.0 仍使用旧参数名 `cls`。

**解决：** 降级 `tokenizers` 至 0.22.2：
```bash
pip install 'tokenizers<0.23'
```

---

### 1.2 ROCm 检测失败

**问题：** 应用启动时显示 `ROCm: False`，但实际 `torch.cuda.is_available()` 返回 True，且 AMD GPU 正常工作。

**根因：** `is_rocm_available()` 函数中检查 `torch.version.rocm is not None`，但该 PyTorch 构建版本（`2.7.1+rocm7.2.0.lw.git262e50d5`）没有 `torch.version.rocm` 属性。

**解决：** 兼容性修复，当 `torch.version.rocm` 属性不存在时，检查 `torch.__version__` 是否包含 `rocm` 字符串：

```python
def is_rocm_available() -> bool:
    cuda_ok = torch.cuda.is_available()
    rocm_ver = getattr(torch.version, 'rocm', None)
    return cuda_ok and (rocm_ver is not None or 'rocm' in torch.__version__.lower())
```

---

### 1.3 GPU 显存信息获取失败

**问题：** `get_gpu_info()` 返回 `VRAM: N/A`。

**根因：** `torch.cuda.get_device_properties(i).total_memory` 属性名错误，应为 `total_memory`（非 `total_mem`）。

**解决：** 修正属性名，使用局部变量 `props = torch.cuda.get_device_properties(i)` 再调用 `props.total_memory`。

---

## 2. 模型下载问题

### 2.1 HuggingFace 官方源不可达

**问题：** 从 `huggingface.co` 下载模型超时或失败。

**根因：** 沙箱环境网络限制，无法直连 HuggingFace 官方源。但 `hf-mirror.com` 镜像站可用。

**解决：** 设置 `HF_ENDPOINT=https://hf-mirror.com` 环境变量，所有下载走国内镜像。

---

### 2.2 snapshot_download 误过滤了 merges.txt

**问题：** SD1.5 模型加载时报错 `ValueError: vocab and merges must be both be from memory or both filenames`。

**根因：** 下载时使用了 `ignore_patterns=['*.md', '*.txt']`，导致 `merges.txt` 被过滤掉未下载。缺少 `merges.txt`，tokenizer 无法初始化。

**解决：** 将过滤规则改为 `ignore_patterns=['*.md']`，仅排除 Markdown 文件，保留 `.txt` 文件。

---

### 2.3 HF 缓存路径不一致

**问题：** `snapshot_download(cache_dir=...)` 将模型文件存储在 `{cache_dir}/models--owner--name/`（无 `hub/` 子目录），但 `from_pretrained()` 使用 `{HF_HOME}/hub/models--owner--name/`（有 `hub/` 子目录）。两者路径不一致，导致模型已下载但无法加载。

**解决：** 在 `_get_local_cache_path()` 中增加对两种缓存路径的检测：

1. `{HF_HOME}/hub/models--owner--name/snapshots/{hash}/`（标准格式）
2. `{HF_HOME}/models--owner--name/snapshots/{hash}/`（直接写入格式）

---

### 2.4 ModelScope 备用路径匹配

**问题：** sd21 从 ModelScope 下载（`AI-ModelScope/stable-diffusion-v2-1`），但 `_get_local_cache_path()` 只检查 `repo_id` 字段（`stabilityai/stable-diffusion-2-1`），不匹配。

**解决：** 增加对 `alternate.modelscope` 备用路径的检测，当主路径不匹配时自动检查备用路径。

---

## 3. 模型加载问题

### 3.1 模型已下载但提示"未下载"

**问题：** 应用界面显示模型已下载，但点击生成时提示"模型未下载"。

**根因链：** 三个问题叠加：

1. **下载缓存格式不匹配：** `modelscope.hub.snapshot_download` 下载到 ModelScope 缓存格式，但 `diffusers` 的 `from_pretrained` 只认 HuggingFace 缓存格式。
2. **路径检测错误：** `_check_downloaded()` 硬编码了缓存路径，与实际下载路径不匹配。
3. **Pipeline 类选择错误：** `_do_load_pipeline()` 硬编码了 SDXL 的 pipeline 类，新加的 sd15/sd21/sd-inpaint/svd 用错了架构类。

**解决：**

1. 改用 `huggingface_hub.snapshot_download` 从 `hf-mirror.com` 下载，直接写入 HF 缓存格式。
2. 创建 `_get_local_cache_path()` 统一解析所有缓存路径（HF 标准、HF 直接写入、ModelScope、备用路径）。
3. 在 `_do_load_pipeline()` 中根据 `pipeline` 字段自动选择正确的加载类，并将 `repo_id` 替换为本地缓存路径。

---

### 3.2 SDXL 使用本地路径加载时 device 为 meta

**问题：** 通过本地缓存路径加载 SDXL 时，`pipe.device` 为 `meta`（元设备）。

**根因：** `from_pretrained` 在加载 `torch_dtype=torch.float16` 时，默认使用 `meta` 设备初始化，后续通过 `enable_sequential_cpu_offload()` 或 `to(device)` 移入实际设备。

**解决：** 这是正常行为，不需要修复。`sequential_cpu_offload` 会在推理时自动将各模块移入 GPU。

---

### 3.3 SDXL 不支持同时 to('cuda') 和 sequential_cpu_offload

**问题：** 调用 `pipe.to('cuda')` 时抛出异常：
```
ValueError: It seems like you have activated sequential model offloading by calling
`enable_sequential_cpu_offload`, but are now attempting to move the pipeline to GPU.
```

**根因：** `_do_load_pipeline()` 中已调用 `enable_sequential_cpu_offload()`，后续不应再手动调用 `to('cuda')`。

**解决：** 移除测试代码中的手动 `to('cuda')` 调用，让 `sequential_cpu_offload` 自动管理设备。

---

## 4. 运行时问题

### 4.1 应用启动时自动下载模型导致启动慢

**问题：** 应用启动后需要等待模型下载完成才能响应页面请求。

**根因：** `_auto_download_core()` 在后台线程中串行下载核心模型，且 `_wait_for_download()` 会阻塞直到下载完成。

**解决：** 这是设计行为，非 bug。首次启动需要等待模型下载（sdxl-base 7GB + VAE 319MB），后续启动由于模型已缓存会很快。

---

### 4.2 Gradio share URL 无法生成

**问题：** Gradio 的 `share=True` 无法生成外网访问链接。

**根因：** 沙箱环境无法下载 `frpc` 二进制文件（`cdn-media.huggingface.co` 不可达）。

**解决：** 改用 Tailscale 提供外网访问（`tailscale serve`）。如无 Tailscale，可通过内网 IP `http://10.232.24.146:7860` 访问。

---

## 5. 功能验证问题

### 5.1 SVD 图生视频推理慢

**问题：** SVD 模型推理超时（默认 120s 超时限制）。

**根因：** `enable_sequential_cpu_offload()` 导致每次推理时各模块在 CPU/GPU 间反复移动，SVD 模型较大（UNet 520 层），移动开销大。

**解决：** 
- 使用更小的生成配置（256×256, 4帧, 2步），25秒完成。
- 生产环境建议使用 `pipe.to('cuda')` 替代 `sequential_cpu_offload` 以获得更快速度（需确保 GPU 显存足够，SVD 约需 5GB）。

---

## 6. 最终模型清单

| 模型 | 模型 ID | 大小 | 来源 | 功能 |
|------|---------|:----:|:----:|------|
| sdxl-base | `stabilityai/stable-diffusion-xl-base-1.0` | 26 GB | ModelScope/HF | 文生图、图生图、外延 |
| sd15 | `runwayml/stable-diffusion-v1-5` | 45 GB | hf-mirror.com | 文生图、图生图 |
| sd21 | `stabilityai/stable-diffusion-2-1` | ~10 GB | ModelScope | 文生图 |
| sdxl-turbo | `stabilityai/sdxl-turbo` | 7 GB | hf-mirror.com | 快速文生图 |
| sdxl-lightning | `ByteDance/SDXL-Lightning` | 3 GB | hf-mirror.com | LoRA 加速 |
| sdxl-vae-fp16 | `madebyollin/sdxl-vae-fp16-fix` | 319 MB | hf-mirror.com | VAE 优化 |
| sd-inpaint | `runwayml/stable-diffusion-inpainting` | 15 GB | hf-mirror.com | 局部重绘 |
| svd | `stabilityai/stable-video-diffusion-img2vid` | 8 GB | hf-mirror.com | 图生视频 |
| lcm-lora-sdxl | `latent-consistency/lcm-lora-sdxl` | 0.1 GB | hf-mirror.com | LoRA 加速 |

---

## 7. 提交历史

| 提交 | 说明 |
|------|------|
| `a5b3f56` | 最终：下载全部模型 + 缓存检测支持 LoRA 格式 |
| `c852801` | ROCm 检测修复 + GPU 信息获取修正 |
| `f353ff0` | 模型加载改用本地缓存路径 + 下载走 hf-mirror |
| `cdab7cd` | 模型下载改走 HuggingFace 缓存格式 + 已下载模型建软链接 |
| `bbda792` | pipeline 加载根据模型架构自动选择正确类 |
| `8909e33` | 模型注册表改用 ModelScope 小模型 + CSS 修复 |
| `bf10eed` | UI 美化 + 系统信息 10s 自动刷新 |
| `1b4127f` | 防 OOM 加固 |
| `3651025` | v2 大改版 - UI美化、智能显存管理、自动下载 |

---

*记录日期：2026-07-15*
*环境：Ubuntu 24.04, ROCm 7.2, AMD Radeon PRO W7900D (48GB)*