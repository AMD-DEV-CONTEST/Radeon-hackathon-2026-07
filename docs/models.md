# 模型清单（Model Manifest）

> 所有模型均**不提交到 git**，统一放在 `ComfyUI/models/` 下。
> 国内下载走 `hf-mirror.com` 镜像；海外可把 `download_models.sh` 中的
> `HF` 改为 `https://huggingface.co`。

## P1：概念原画 + 深度图（当前阶段）

| 用途 | 文件 | 来源 | 大小 | 目标路径 |
| --- | --- | --- | --- | --- |
| W1 概念原画 | `sd_xl_base_1.0.safetensors` | stabilityai/stable-diffusion-xl-base-1.0 | ~6.9 GB | `models/checkpoints/` |
| W1 VAE | `sdxl_vae.safetensors` | stabilityai/sdxl-vae | ~330 MB | `models/vae/` |
| W2 深度图 | `dpt_hybrid-midas-501f0c75.pt` | lllyasviel/Annotators（MiDaS） | ~87 MB | `models/controlnet/auxiliary/` |

## 可选升级：Depth Anything V2（W2 更优）

Depth Anything V2 精度更高，但 hf-mirror 暂未镜像该仓库，
需要时可从 GitHub Releases 或 ModelScope 自行获取
`depth_anything_v2_vits.pth`（~90MB），放入 `models/depthanything/`，
并配合自定义节点 `ComfyUI-DepthAnythingV2` 使用。

## 后续阶段（按需追加）

| 阶段 | 用途 | 建议模型 | 大小（约） |
| --- | --- | --- | --- |
| P3 | 3D 材质（深度→法线） | 基于 W2 深度图程序化生成，无需新模型 | — |
| P3 | 背景音乐 | MusicGen small（已下载，`ComfyUI/models/musicgen/`） | 2.3 GB |
| P3 | 环境音效 | 程序化合成，无需模型；可加音效库 | — |
| P4 | 序列帧姿态控制 | ControlNet OpenPose SDXL（已下载，`OpenPoseXL2.safetensors`） | 5.0 GB |
| P4 | 动作一致性 | 动作 LoRA（按角色风格选用） | 数十 MB |
| W7 | 2D 角色图 → 3D 模型 | TripoSR（`TripoSR.ckpt`，stabilityai/TripoSR） | ~1 GB |

## 下载方式

```bash
bash scripts/download_models.sh        # W1~W6 模型
bash scripts/setup_3d.sh              # W7 TripoSR 节点
bash scripts/download_3d_model.sh     # W7 TripoSR 权重
```

## 注意

- 模型文件较大，请勿使用 `git add -A` 提交（`.gitignore` 已排除 `*.safetensors` 等）；
- 更换模型时只需删除旧文件重新执行下载脚本；
- 每个模型应记录来源与版本，方便复现生成结果。

## 提示词翻译（中→英，网页功能）

| 用途 | 文件 | 来源 | 大小 | 目标路径 |
| --- | --- | --- | --- | --- |
| 中文提示词→英文 | `opus-mt-zh-en/*`（5 个文件） | Helsinki-NLP/opus-mt-zh-en | ~300 MB | `models/translator/opus-mt-zh-en/` |

下载：`bash scripts/download_translator.sh`

> 提示词框支持中文输入：提交时自动翻译成英文；已是英文则原样保留。
