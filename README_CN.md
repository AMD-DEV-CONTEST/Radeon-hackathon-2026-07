# 3DGenerateFlow

基于一张照片生成可直接 3D 打印的全彩 3D / 2.5D 模型的内容创作工具。内置 **3D Director Agent**：输入一句话需求，Agent 自动选择风格、编排生成流程、合成多视角图并输出可打印模型。作品以 **Web UI** 形式交付，后端核心推理链路完全在 **AMD Radeon GPU + ROCm** 上本地运行。

---

## 赛道定位

**赛道一：多模态内容创作工具开发**

- 核心创作任务：图生图 / 图生 3D / 2.5D 浮雕 / 全彩 3D 打印模型
- 应用场景：个人纪念品、宠物/人物手办、IP 衍生品、商业视觉设计、3D 打印内容制作
- 交付形式：Web UI（React + TypeScript + R3F 前端，FastAPI + Celery 后端）

---

## 快速开始

### 1. 环境准备（AMD ROCm）

```bash
# 一键安装 ROCm 环境、PyTorch for ROCm、Hunyuan3D-2
./rocm/setup_rocm.sh
./rocm/setup_hunyuan3d.sh
```

> 要求：AMD Radeon GPU，ROCm 软件栈，PyTorch 2.5.1+rocm6.1 已通过 `setup_rocm.sh` 安装。

### 2. 启动后端

```bash
cd services/api
source .venv/bin/activate
export USE_ROCM=true
export USE_HUNYUAN3D=true
export USE_HUNYUAN3D_MV=true
export HIP_VISIBLE_DEVICES=0
export CELERY_TASK_ALWAYS_EAGER=true
export CELERY_RESULT_BACKEND=cache+memory://
export CELERY_TASK_EAGER_PROPAGATES=true

PYTHONPATH=../.. uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 3. 启动前端

```bash
cd apps/web
npm install
npm run dev
```

浏览器打开 `http://localhost:5173`。

如果前端在 Mac/Windows 上而后端在云端 AMD 实例上，启动时指定后端地址：

```bash
VITE_API_URL=http://<AMD实例公网IP>:8000 npm run dev
```

### 4. 复制环境变量（可选）

```bash
cp services/api/.env.example services/api/.env
```

不填写 LLM key 时，Agent 会自动退回到规则模式，仍可跑通全流程。

---

## 项目结构

```
3DGenerateFlow/
├── apps/web                # React + TypeScript + Tailwind + R3F 前端
├── services/api            # FastAPI + Celery 后端
│   ├── agents/             # 3D Director Agent（Planner / Director / Memory / Chat）
│   ├── pipelines/          # 3D / 2.5D 生成管线
│   ├── adapters/           # ROCm / Hunyuan3D-2 / Zero123 适配层
│   ├── routers/            # API 路由
│   └── jobs/               # Celery 异步任务
├── shared/schemas          # 前后端共享 Pydantic 结构
├── rocm/                   # ROCm 与 Hunyuan3D-2 安装脚本
├── scripts/                # benchmark 与下载脚本
├── docs/                   # 参赛文档与海报源文件
└── infra/                  # Nginx 部署配置
```

---

## 主要能力

| 能力 | 说明 | 运行位置 |
|------|------|----------|
| **图像上传** | 物品 / 宠物 / 人物照片 | 前端 |
| **AI Director Agent** | 一句话生成执行计划，自动选择风格、输出模式、生成步骤 | 后端（规则 fallback，可选 LLM） |
| **风格目录** | 写实 3D、卡通 3D、低多边形、体素、粘土、素描、2.5D 浮雕、透光浮雕、纪念币/硬币、剪影浮雕 | 后端 |
| **图生图风格化** | Stable Diffusion img2img，最高 1024px | 后端 ROCm |
| **多视角合成** | Zero123 从正面图生成 front/right/back/left | 后端 ROCm |
| **3D 生成** | Hunyuan3D-2 / Hunyuan3D-2mv 多视角图生 3D | 后端 ROCm |
| **2.5D 浮雕** | 本地深度估计 + 高度图 → 带贴图 GLB + 可打印 STL | 后端 ROCm + CPU |
| **全彩纹理 fallback** | 当 Hunyuan3D-2 纹理模块在 ROCm 上无法编译时，自动用正面投影贴图 | 后端 CPU |
| **打印就绪检查** | 体积、包围盒、watertight 计算 | 后端 |
| **3D 预览** | Web UI 内嵌 Three.js 模型查看器 | 前端 |
| **右侧 AI 聊天** | 用自然语言切换风格、调整参数、重新生成 | 前端 |

---

## 当前实现状态

- [x] 项目脚手架（前后端 + Docker）
- [x] 单图上传与任务投递接口
- [x] Landing / Director Console / Result 三页式极简 Web UI
- [x] 3D Director Agent（LLM / 规则 fallback）
- [x] 风格目录（3D + 2.5D 多种风格）
- [x] 3D / 2.5D 异步管线调度
- [x] ROCm 本地图生图风格化
- [x] ROCm 本地深度估计
- [x] Zero123 多视角合成
- [x] Hunyuan3D-2 / Hunyuan3D-2mv 本地图生 3D
- [x] 全彩纹理贴图 fallback
- [x] 打印报告（体积、尺寸、watertight）
- [x] 前端 3D 模型预览与下载
- [ ] 云端 3D API 兜底（Tripo / Meshy / Rodin，可选）
- [ ] 更复杂的 UV 展开与多视角纹理融合

---

## ROCm / AMD GPU 本地运行

本项目已针对 **AMD Radeon GPU + ROCm** 进行适配，核心创作链路（风格迁移 → 多视角合成 → 3D 生成 → 2.5D 浮雕 → 打印检查）全部可在本地 AMD GPU 上运行，无需依赖闭源 3D API。

快速启动：

```bash
./rocm/setup_rocm.sh
./rocm/setup_hunyuan3d.sh
```

然后按上文“启动后端”和“启动前端”操作。

详细说明请见 [`docs/ROCM_GUIDE.md`](docs/ROCM_GUIDE.md)。

---

## 比赛演示检查点

1. 打开 Web UI 首页，右上角显示 **AMD ROCm Ready** 徽章。
2. 拖拽上传一张照片，选择风格（如 Realistic 3D / Relief Coin），输入描述后点击 **Start Generate**。
3. 自动进入 **Director Console**，左侧参数面板、中间 6 步故事板时间线、右侧 AI 助手与任务日志实时展示进度。
4. 等待后端在 AMD GPU 上完成本地推理（Upload → Style → Multiview → 3D → Print Check → Export）。
5. 完成后自动进入 **Result 页**，展示转盘 3D 预览与打印报告（Volume / Dimensions / Wall Thickness / Watertight）。
6. 下载 `model.glb`（全彩 3D）或 `relief.stl` / `relief.glb`（2.5D 浮雕）。

---

## 演示视频脚本

详见 [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md)。

---

## 参赛文档

- 前端重新设计依据：[`docs/FRONTEND_DESIGN.md`](docs/FRONTEND_DESIGN.md)
- 英文项目简介（PDF 源文件）：[`docs/PROJECT_INTRO_EN.md`](docs/PROJECT_INTRO_EN.md)
- 英文海报（PDF 源文件）：[`docs/POSTER_EN.md`](docs/POSTER_EN.md)
- Pull Request 描述模板：[`docs/PR_DESCRIPTION.md`](docs/PR_DESCRIPTION.md)
- 演示视频脚本（3–5 分钟）：[`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md)
- 演示视频制作指南（含自动录屏脚本）：[`docs/VIDEO_PRODUCTION.md`](docs/VIDEO_PRODUCTION.md)

---

## 性能测试

```bash
cd services/api
source .venv/bin/activate
python scripts/benchmark_rocm.py --image assets/samples/dog.jpg --style relief_embossed
python scripts/benchmark_rocm.py --image assets/samples/bride.jpg --style realistic_3d
```

---

## 许可

MIT
