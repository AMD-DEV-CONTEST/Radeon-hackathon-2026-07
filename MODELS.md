# 模型清单 / Models

本项目的**模型权重不通过 `requirements.txt` 安装**（它们是 GB 级二进制大文件，不是 pip 包）。
请按下方命令下载，并放到指定本地路径，再由各脚本通过路径/环境变量引用。

> 国内加速（已写入项目约定）：先执行
> `export HF_ENDPOINT=https://hf-mirror.com`
> 再跑 `huggingface-cli download`，可走 hf-mirror 镜像避免官方源超时。

---

## 1. Animagine XL 4.0（出图基座，SDXL finetune）
- **HF repo：** `cagliostrolab/animagine-xl-4.0`
- **本地路径：** `models/animagine-xl-4.0/`
- **大小：** ~12 GB（含 VAE / 双 text_encoder 缓存）
- **引用：** `src/generation/sticker_pipeline.py` 与 `src/webui/gradio_app.py` 的基座路径指向此目录。

## 2. Qwen2.5-VL-3B-Instruct（图生文多模态引擎）
- **HF repo：** `Qwen/Qwen2.5-VL-3B-Instruct`
- **本地路径：** `models/Qwen2.5-VL-3B-Instruct/`
- **大小：** ~7.1 GB（FP16）
- **引用：** `src/multimodal/img2prompt.py` 通过环境变量 `QWEN_VL_PATH` 覆盖路径（默认 `/persistent/models/Qwen2.5-VL-3B-Instruct`）。

## 3. stkstyle 风格 LoRA（自训，随本仓库 Git LFS 分发）
- **路径：** `src/lora/models/stkstyle_lora_diffusers/pytorch_lora_weights.safetensors`（~177 MB / 185,961,496 B）
- **触发词：** `stkstyle`
- **训练配方：** 见 `src/lora/README.md`（在 AMD ROCm 上以 animagine-xl-4.0 为基座、rank32/α16、2000 步自训）。
- **该文件由 Git LFS 托管，真实对象已上传到远程仓库。** 标准获取方式：

  ```bash
  git clone https://github.com/kwangroy/candy-chibi.git
  cd candy-sticker-generator
  git lfs install
  git lfs pull        # 拉取真实权重（185 MB）
  ```

  校验：文件应为 **185,961,496 字节**；若只有 134 B 说明仍是 LFS 指针（LFS 未拉取成功）。
  WebUI 设计为静默回退——权重缺失时仍可出图，只是没有 `stkstyle` 风格。

- **备用下载（当 Git LFS 端点不可达时，例如中国大陆无 VPN）：** 真实权重同时发布在仓库 Release `lora-v1`：

  ```bash
  curl -L -o src/lora/models/stkstyle_lora_diffusers/pytorch_lora_weights.safetensors \
    https://github.com/kwangroy/candy-chibi/releases/download/lora-v1/stkstyle_lora_pytorch_lora_weights.safetensors
  ```

> 注：LTX-Video 仅用于早期「动态贴纸」探索（已弃用，非核心管线），不列入必需模型；其权重在 `models/ltx/` 仅作实验残留。

---

## 下载命令

```bash
# 0) 国内镜像（可选，强烈建议）
export HF_ENDPOINT=https://hf-mirror.com

# 1) Animagine XL 4.0 基座
huggingface-cli download cagliostrolab/animagine-xl-4.0 \
  --local-dir models/animagine-xl-4.0

# 2) Qwen2.5-VL-3B-Instruct 多模态
huggingface-cli download Qwen/Qwen2.5-VL-3B-Instruct \
  --local-dir models/Qwen2.5-VL-3B-Instruct
```

---

## 目录约定

```
candy-sticker-generator/
├── models/
│   ├── animagine-xl-4.0/            ← 出图基座（需下载）
│   └── Qwen2.5-VL-3B-Instruct/      ← 图生文引擎（需下载）
└── src/lora/models/
    └── stkstyle_lora_diffusers/     ← 自训风格 LoRA（Git LFS 托管，git lfs pull 获取；Release lora-v1 作备用）
```
