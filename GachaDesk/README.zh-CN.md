# GachaDesk

> Track 1 — 基于 AMD Radeon GPU (ROCm) 的多模态内容创作工具

简短一句话介绍 GachaDesk 是什么。

## 项目结构

```
GachaDesk/
├── README.md                              # 英文版说明(比赛提交主文件)
├── README.zh-CN.md                        # 本文件(中文版)
├── .gitignore                             # 忽略 .env / .bat 等敏感文件
├── requirements.txt                       # 主项目依赖列表
├── scripts/                               # 启动 / 部署脚本
└── src/                                   # 源代码
    ├── app.py                             # 主程序入口(瘦客户端,调用远程子服务 API)
    ├── requirements.txt                   # 主项目依赖
    ├── app/                               # 应用入口与界面(预留包)
    │   └── __init__.py
    ├── models/                            # 模型与算法(预留包)
    │   └── __init__.py
    ├── Qwen-Image-2512-AMD-MI308X/        # 文生图子服务(MI308X 部署)
    │   ├── app.py                         # Qwen-Image-2512 推理入口
    │   ├── requirements.txt
    │   ├── README.md                      # 英文版
    │   └── README.zh-CN.md                # 中文版
    ├── Qwen-Image-Edit-2511-AMD-MI308X/   # 图生图子服务(MI308X 部署)
    │   ├── app.py                         # Qwen-Image-Edit-2511 推理入口
    │   ├── requirements.txt
    │   ├── images/                        # 示例图片(t1-1.png / t1-2.png)
    │   ├── README.md                      # 英文版
    │   └── README.zh-CN.md                # 中文版
    └── Wan2.2-14B-I2V-LoRA-AMD-MI308X/    # 图生视频子服务(MI308X 部署)
        ├── app.py                         # Wan2.2-I2V 推理入口
        ├── requirements.txt
        ├── images/                        # 示例图片(t1.jpg / t2.jpg / t3.jpg)
        ├── README.md                      # 英文版
        └── README.zh-CN.md                # 中文版
```

## 环境要求

- 硬件:AMD Radeon GPU(ROCm)
- 操作系统:Linux(ROCm 支持)
- Python:3.10+
- ROCm:见 [Radeon Cloud User Guide](../Radeon-Cloud-User%20Guide/README.md)

## 依赖列表

```bash
pip install -r requirements.txt
```

> 注意:运行上述命令前,需按照 ROCm 官方文档单独安装支持 ROCm 的 PyTorch wheel。

## 启动指南

```bash
# 1. 进入源代码目录
cd src

# 2. 启动应用
python app.py
```

Web 界面默认访问地址:`http://localhost:7860`。

## 视频工作台功能介绍

`src/app.py` 是 GachaDesk 的主程序入口,提供一个名为 **"视频工作台"** 的 Gradio 网页界面,集成文生图、图生图、图生视频、8 镜分镜编排、合片与水印等能力,支持完整的 **"分镜脚本 → 视频成片"** 工作流。主项目自身不加载模型,所有生成任务均通过 ModelScope 创空间 API 调用三个远程子服务完成。

### 核心功能模块

#### 1. 主操作台

- 上传一张图片,作为后续图生图 / 分镜图生图的输入素材
- 可接收文生图 / 图生图结果的"推送操作台"动作,实现素材流转

#### 2. 文生图

- **输入**:正向提示词 + 尺寸(7 档比例)+ 推理步数(10-100)
- **后端**:调用 `Qwen-Image-2512-AMD-MI308X` 远程 API
- **结果动作**:可"推送操作台"或"推送分镜 1"

#### 3. 图生图

- **输入**:主操作台图片 + 正向提示词
- **后端**:调用 `Qwen-Image-Edit-2511-AMD-MI308X` 远程 API(背景替换、风格转换、人物换装等)
- **结果动作**:可"推送操作台"或"推送分镜 2"

#### 4. 分镜台(8 镜)

2 行 × 4 列共 8 个分镜,每个分镜独立包含:图片、提示词、图生图按钮、图生视频按钮、续帧按钮。

- **图生图**:以主操作台图片 + 本分镜提示词生成本分镜图片
- **图生视频**:以本分镜图片 + 本分镜提示词调用 `Wan2.2-14B-I2V-LoRA-AMD-MI308X` API 生成视频
- **续帧**:自动提取本镜视频的最后一帧,作为下一镜的输入图片,实现分镜间画面连贯过渡(共 7 个续帧按钮:1→2, 2→3, …, 7→8)

#### 5. 合片区

- **8 图合片**:把分镜台 8 张图片按每图 16 帧拼接成视频(8 FPS)
- **8 镜合片**:把 8 个分镜视频顺序拼接成一个长视频
- **水印**:支持自定义水印文字(留空则不添加),逐帧绘制黑色阴影 + 白色文字,右下角自适应大小

### 默认参数

| 模块 | 参数 | 默认值 |
|------|------|--------|
| 文生图 | CFG / 种子 / 尺寸 / 步数 | 4.0 / -1(随机) / 16:9 (1664×928) / 25 |
| 图生图 | 分辨率 / 步数 / CFG | 1664×928 / 4 / 1.5 |
| 图生视频 | 模型 / LoRA / 分辨率 / 帧数 / FPS | Wan2.2-I2V-A14B / LightX2V 4 步 / 768×432 / 81 帧 / 16 |
| 水印 | 默认文字 | `AI ART XIHUYISHENG AMD RADEON` |

### 推荐使用流程(分镜成片)

1. **准备素材**:在主操作台上传一张图片(或先用"文生图"生成一张,点击"推送操作台")
2. **生成第 1 镜**:在正向提示词框输入画面描述 → 点击"文生图" → 点击"推送分镜 1"
3. **生成第 1 镜视频**:在分镜 1 的提示词框输入动作描述 → 点击"图生视频 1"
4. **续帧到第 2 镜**:点击"续帧 1→2",自动提取第 1 镜最后一帧作为第 2 镜图片
5. **重复生成**:在分镜 2 输入提示词 → "图生视频 2" → "续帧 2→3" … 直至完成 8 镜
6. **合片输出**:在合片区输入水印文字 → 点击"8 镜合片",把 8 个分镜视频拼接为最终长视频

> **快捷路径**:若已有 8 张分镜图片,可直接跳过视频生成,点击"8 图合片"快速产出幻灯片式视频。

### 适用场景

- 🏫 **乡村助教课件**:为乡村教师快速生成配图素材,让课件生动直观
- 👗 **女装宣传展示**:一键生成服装上身效果图与宣传短视频,低成本打造商品展示
- 🌄 **文旅风光推广**:生成景区意境图与分镜短片,助力乡村文旅宣传
- 🥬 **农产直播带货**:为农产品制作精美海报与预告短片,提升带货转化
- 📱 **短视频素材库**:批量产出多分镜画面,快速合成创意短视频

## Demo 视频

- 视频链接:(待补充,建议上传 Bilibili / YouTube)

## 项目 Profile 文档

- [GachaDesk-Profile.pdf](docs/GachaDesk-Profile.pdf)

## AMD Radeon GPU / ROCm 适配说明

本项目三个子模块均运行在 **AMD Instinct MI308X (192GB HBM3)** 单卡上,基于 **ROCm 6.3.0+** 与 PyTorch ROCm 版本进行本地推理,无需调用远程 API。各子模块针对自身模型特性分别采用了不同的 ROCm 优化组合:

### 1. Qwen-Image-2512(文生图)

- **精度**:bfloat16(ROCm 原生支持)
- **注意力**:`attn_implementation="flash_attention_2"`,并通过 `torch.backends.cuda.preferred_rocm_fa_library("aotriton")` 优先选用 AOTriton 后端
- **矩阵乘法**:`torch.backends.cuda.matmul.allow_tf32 = True` + `set_float32_matmul_precision("high")`(MI300+ 系列 TF32 加速显著)
- **显存**:全量 GPU 加载,20B MMDiT 完整载入 192GB HBM3,零换页
- **容错**:VAE float16 解码失败时自动回退 float32 重试,并在关键节点 `torch.cuda.synchronize()` 避免 ROCm 异步错误

### 2. Qwen-Image-Edit-2511(图像编辑)

- **精度**:bfloat16
- **注意力**:启用 `enable_flash_sdp(True)` + `enable_mem_efficient_sdp(True)`,禁用慢速 `math_sdp`,强制走 Triton Flash Attention 内核
- **关键环境变量**:
  - `TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1` — 启用 AOTriton 实验性内核
  - `FLASH_ATTENTION_TRITON_AMD_ENABLE=TRUE` — 启用 AMD Triton Flash Attention
  - `HIP_FORCE_DEV_KERNARG=1` — 强制设备侧内核参数
  - `PYTORCH_HIP_ALLOC_CONF=garbage_collection_threshold:0.8,max_split_size_mb:512` — 优化显存分配碎片
- **缓存持久化**:`TRITON_CACHE_DIR` / `TORCH_EXTENSIONS_DIR` 重定向至 `/mnt/workspace`,避免容器重启后重新编译 AMD GPU 内核(首次编译约 20 分钟,后续秒出)
- **加速**:挂载 `lightx2v/Qwen-Image-Edit-2511-Lightning` 蒸馏 LoRA,4 步即可出图
- **分辨率锁定**:固定 1664×928,避免不同 shape 触发内核重编译

### 3. Wan2.2-14B-I2V-LoRA(图生视频)

- **精度**:float16
- **注意力**:`attn_implementation="xformers"`(失败自动回退默认实现)
- **加速**:挂载 `lightx2v/Wan2.2-Distill-Loras` 的 `high_noise` + `low_noise` 双适配器(各 50% 权重),实现 4 步极速推理
- **输出**:固定 16 FPS,支持 1280×720 / 832×480 / 768×432 三档分辨率,81 或 121 帧
- **监控**:集成 `rocm-smi` 实时获取温度、核心/显存频率,补充 `torch.cuda` 无法获取的信息

### 共性优化

- **本地全量推理**:三个模块的模型均完整载入 MI308X 显存,不走量化分片或 CPU offload
- **Gradio + MCP**:均启用 `mcp_server=True`,每个 API 端点自动映射为 MCP 工具,可供智能体调用
- **日志双通道**:`logger.info` / `print` 同时输出到控制台与 Gradio 界面运行日志框
- **显存治理**:每次推理前后 `gc.collect()` + `torch.cuda.empty_cache()`,避免碎片累积

### 部署架构(主项目 + 远程子服务)

主项目 `src/app.py` 采用 **瘦客户端 + 远程 GPU 服务** 的部署架构,自身不加载任何模型,而是通过 ModelScope 创空间提供的 Gradio API 调用三个独立部署的子项目:

- **主项目(瘦客户端)**:运行在任意环境(本地 / 边缘 / 低配机器),负责用户交互、分镜编排、合片与水印绘制。零 GPU 依赖,只依赖 `requests`、`gradio`、`imageio`、`PIL`。
- **三个远程子服务(重 GPU 端)**:分别部署在 AMD MI308X 上,通过 ModelScope 创空间暴露 Gradio API + SSE 流式响应:
  - `studio-xihuyisheng-qwen-image-2512-amd-mi308x` — 文生图
  - `studio-xihuyisheng-qwen-image-edit-2511-amd-mi308x` — 图生图
  - `studio-xihuyisheng-wan2-2-14b-i2v-lora-amd-mi308x` — 图生视频

主项目通过 `ModelScopeImageClient` 客户端封装完整的远程调用流程:`/config` 探测端点 → 提交任务 → 监听 SSE 流获取结果 → 通过 API 网关鉴权下载产物,以及 `upload_image` 上传待编辑图片。鉴权使用 Bearer Token(从 `.env` 的 `MODELSCOPE_API_TOKEN` 读取)。

这种架构让算力与交互解耦:**真正的 ROCm 推理算力集中在云端 MI308X 子服务,主项目可在任何低配终端运行**,适合乡村助教、直播带货等终端资源有限的场景。

## 团队信息

- 团队名:xihuyisheng
- 成员:xihuyisheng
