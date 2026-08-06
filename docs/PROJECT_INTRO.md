# 3DGenerateFlow 项目简介

## 1. 项目背景

随着消费级 3D 打印、全彩打印（Mimaki / Stratasys / PolyJet）和 AI 生成技术的成熟，普通用户和小型工作室越来越希望能够把一张物品、宠物或人物照片快速变成可打印的全彩 3D 或 2.5D 纪念品。然而，现有工具普遍存在以下门槛：

- 多视角拍摄与建模流程复杂；
- 风格化、3D 生成、打印检查需要在多个工具间跳转；
- 核心模型推理依赖闭源 API，成本高且可控性差；
- 缺少面向“从照片到打印”的端到端创作工具。

**3DGenerateFlow** 旨在解决这些问题：用户上传一张照片、用一句话描述想要的风格，系统即可在本地 AMD Radeon GPU 上自动完成多视角合成、3D 生成/2.5D 浮雕、纹理贴图和打印检查，最终输出可直接 3D 打印的模型文件。

---

## 2. 目标用户与应用场景

### 目标用户

- **个人创作者**：想把自己、宠物、手办原型做成 3D 打印纪念品。
- **小型设计工作室 / 电商卖家**：批量生产个性化 IP 衍生品、冰箱贴、纪念币、浮雕奖牌。
- **3D 打印服务商**：接收客户照片后快速生成可打印文件，缩短交付周期。
- **教育工作者 / 创客空间**：用于 AI + 3D 打印的入门教学与演示。

### 应用场景

- 宠物/人物全身像 3D 手办（写实、卡通、低多边形、体素等风格）。
- 照片浮雕 / 透光浮雕（Lithophane）/ 纪念币 / 剪影挂件。
- 商业视觉设计：快速把产品照片变成 3D 展示模型或 3D 打印原型。
- 社交媒体内容制作：生成带 3D 预览的分享卡片。

### 社会价值

- 降低 3D 内容创作门槛，让非专业用户也能参与个性化制造。
- 支持本地 AMD GPU 推理，减少依赖国外闭源 API，提升数据隐私与可控性。
- 为开源 AI 3D 生成 pipeline（Hunyuan3D-2、Zero123）在 ROCm 生态上的工程化落地提供参考实现。

---

## 3. 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         Web UI（React + R3F）                      │
│  上传照片 · AI 风格规划 · Lazy Canvas 流程 · 3D 预览 · 下载模型  │
└───────────────────────────────┬───────────────────────────────────┘
                                │ HTTP/WebSocket
┌───────────────────────────────┴───────────────────────────────────┐
│                   FastAPI + Celery（Eager 模式）                    │
│  /upload · /agent/plan · /agent/execute · /jobs · /health/gpu    │
└───────────────────────────────┬───────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌───────────────┐     ┌───────────────┐     ┌───────────────┐
│  ROCm 适配层   │     │  Hunyuan3D-2  │     │  3D Director  │
│  · SD img2img  │     │  · 2D → 3D    │     │  · 风格规划    │
│  · Zero123     │     │  · 2mv 多视角  │     │  · 任务调度    │
│  · Depth V2    │     │  · 纹理 fallback│     │  · 记忆/聊天   │
└───────┬───────┘     └───────┬───────┘     └───────────────┘
        │                       │
        └───────────┬───────────┘
                    ▼
          ┌───────────────────┐
          │   打印检查 / 导出   │
          │  · 缩放/居中/底面   │
          │  · 体积/包围盒/流形 │
          │  · GLB / STL 输出   │
          └───────────────────┘
```

### 技术栈

- **前端**：React 19 + TypeScript + Tailwind CSS + Vite + React Three Fiber / Drei
- **后端**：Python 3.12 + FastAPI + Celery（Eager 同步模式用于演示）+ SQLAlchemy + SQLite
- **AI 推理**：PyTorch 2.5.1 + ROCm 6.1 + Diffusers + Transformers + Trimesh
- **核心模型**：
  - Stable Diffusion v1.5（img2img 风格化）
  - Zero123-xl（多视角合成）
  - Depth Anything V2 Small（深度估计）
  - Hunyuan3D-2 / Hunyuan3D-2mv（图生 3D）
- **运行环境**：AMD Radeon GPU（gfx1100，48 GB VRAM）+ ROCm 开源软件栈

---

## 4. 模型与算法介绍

### 4.1 图生图风格化（Stable Diffusion img2img）

- 使用 `runwayml/stable-diffusion-v1-5` 在 ROCm 上本地运行。
- 按原图比例缩放到最大边 1024px，保留照片清晰度。
- 根据风格目录拼接 prompt（写实、卡通、低多边形、体素、粘土、素描等）。
- 输出 `styled_preview.png`，同时作为 3D 生成的正面参考图。

### 4.2 多视角合成（Zero123）

- 使用 `ashawkey/zero123-xl-diffusers` 从单张正面图生成 front / right / back / left 四个视角。
- 512×512 输出，输入图先中心裁剪为正方形，保证视角一致性。
- 为后续 Hunyuan3D-2mv 多视角 3D 生成提供输入。

### 4.3 深度估计（Depth Anything V2）

- 使用 `depth-anything/Depth-Anything-V2-Small-hf` 在 ROCm 上运行。
- 输出灰度深度图，作为 2.5D 浮雕的高度场。

### 4.4 图生 3D（Hunyuan3D-2 / Hunyuan3D-2mv）

- **Hunyuan3D-2**：单视图生成 3D 网格，适合快速验证。
- **Hunyuan3D-2mv**：多视图（front / right / back / left）输入，几何一致性更好，是作品主链路。
- 在 ROCm 上通过 `torch.float16` 推理，48 GB VRAM 可完整加载模型。
- 原始输出为归一化坐标，后处理模块按风格 `target_height_mm`（如 80 mm）等比缩放、居中并把底面置于 Z=0。

### 4.5 全彩纹理

- 首选 Hunyuan3D-2 自带纹理模块；在 ROCm 上若 CUDA 扩展无法编译，则自动 fallback：
  - 3D 模型：使用正面投影 UV，把风格化参考图贴到网格正面。
  - 2.5D 浮雕：1:1 像素 UV，把原图作为贴图生成彩色 GLB；同时导出 STL 用于单色打印。

### 4.6 打印检查

- 使用 Trimesh 计算网格体积、包围盒尺寸、watertight 状态。
- 3D 模型缩放后确保底面平整、尺寸以 mm 为单位，输出 `print_report` 供前端展示。

---

## 5. AMD Radeon GPU / ROCm 适配说明

### 5.1 硬件环境

- GPU：AMD Radeon Graphics（Navi31 / gfx1100）
- 计算单元：96 CU
- 显存：48 GB GDDR6
- 驱动：amdgpu 6.16.13
- ROCm：PyTorch 2.5.1+rocm6.1

### 5.2 适配要点

1. **PyTorch for ROCm**：`setup_rocm.sh` 自动检测 ROCm 并安装 `torch==2.5.1+rocm6.1`，验证 `torch.cuda.is_available()` 返回 True。
2. **Hunyuan3D-2 在 ROCm 上运行**：使用 `torch.float16` 和 `device='cuda'`（ROCm 在 PyTorch 中通过 CUDA 兼容层暴露）。`Hunyuan3DDiTFlowMatchingPipeline.to()` 为 in-place 操作，已修复误用导致的 `None` pipeline 问题。
3. **纹理模块 fallback**：Hunyuan3D-2 的 `custom_rasterizer` 和 `differentiable_renderer` 依赖 CUDA 扩展，在 ROCm 上编译失败；系统自动 fallback 到基于 Trimesh 的正面投影贴图，保证链路可用。
4. **Celery 内存 backend**：演示环境无 Redis，启用 `CELERY_TASK_ALWAYS_EAGER=true` 并强制 broker/backend 为 `memory://` / `cache+memory://`，避免连接 Redis 失败。
5. **显存优化**：对 Stable Diffusion 和 Zero123 启用 `enable_model_cpu_offload`，48 GB 显存可同时容纳风格化、多视角和 3D 生成模型。

### 5.3 性能数据

- 2.5D 浮雕：从照片到 STL/GLB 约 2–5 分钟（取决于图像分辨率）。
- 3D 全彩：从照片到多视角 + 3D 网格 + 纹理约 10–30 分钟（首次需下载模型）。
- 所有关键推理步骤均在 AMD GPU 本地完成，无需调用闭源在线 API。

---

## 6. 创新点

- **Lazy Canvas 工作流**：把复杂的 3D 生产流程抽象为 6 步可视化节点，降低上手门槛，同时保留 Agent 可修改的灵活性。
- **3D Director Agent**：一句话生成风格、参数和流程计划，无需用户手动选择每个模型节点。
- **多模态 + 可打印闭环**：图生图、多视角、图生 3D、2.5D 浮雕、打印检查、Web UI 预览与下载一体化。
- **ROCm 本地优先**：在 AMD GPU 上跑通 Hunyuan3D-2 / Zero123 / Depth Anything V2，并给出纹理 fallback 方案。
