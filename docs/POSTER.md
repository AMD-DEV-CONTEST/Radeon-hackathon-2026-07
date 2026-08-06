# 3DGenerateFlow 参赛海报（Markdown 源文件）

> 可配合浏览器打印或 `docs/generate_poster_pdf.py` 导出为 PDF。

---

## 3DGenerateFlow

### 一张照片 → 一句话 → 可打印的全彩 3D / 2.5D 模型

**赛道**：多模态内容创作工具开发  
**交付形式**：Web UI  
**运行平台**：AMD Radeon GPU + ROCm 开源软件栈

---

## 为什么做这个项目？

- 3D 内容创作门槛高：多视角拍摄、建模、风格化、打印检查分散在多个工具。
- 闭源 API 成本高、可控性差。
- 缺少面向“照片 → 3D 打印”的端到端工具。

**3DGenerateFlow = 照片 + 一句话 + AMD GPU → 全彩 3D 模型 / 2.5D 浮雕**

---

## 核心能力

| 功能 | 说明 |
|------|------|
| **AI Director Agent** | 一句话规划风格、参数与 6 步生产流程 |
| **图生图风格化** | Stable Diffusion img2img，最高 1024px，ROCm 本地推理 |
| **多视角合成** | Zero123 生成 front / right / back / left |
| **图生 3D** | Hunyuan3D-2 / Hunyuan3D-2mv 多视角 3D 生成 |
| **2.5D 浮雕** | Depth Anything V2 + 高度图 → 彩色 GLB + 可打印 STL |
| **全彩纹理 fallback** | ROCm 不兼容 CUDA 扩展时自动投影贴图 |
| **打印检查** | 体积、包围盒、watertight 实时报告 |
| **Web UI 预览** | Three.js 内嵌 3D 查看器与下载 |

---

## 系统架构

```
Web UI（React + R3F）
    ↓
FastAPI + Celery（Eager 模式）
    ↓
┌─────────────┬──────────────┬─────────────┐
│  ROCm 适配层 │ Hunyuan3D-2  │ 3D Director │
│  · SD img2img│ · 2D → 3D    │ · Agent 规划 │
│  · Zero123   │ · 2mv 多视角 │ · 记忆/聊天 │
│  · Depth V2  │ · 纹理 fallback            │
└─────────────┴──────────────┴─────────────┘
              ↓
        打印检查 / 导出（GLB / STL）
```

---

## 技术栈

- **前端**：React 19 + TypeScript + Tailwind + Vite + R3F
- **后端**：FastAPI + Celery + SQLAlchemy + SQLite
- **AI**：PyTorch 2.5.1 + ROCm 6.1 + Diffusers + Transformers
- **模型**：Stable Diffusion v1.5、Zero123-xl、Depth Anything V2、Hunyuan3D-2 / 2mv
- **打印**：Trimesh 网格处理、UV 贴图、体积/流形检查

---

## AMD ROCm 适配亮点

- 一键脚本安装 ROCm 环境 + PyTorch for ROCm + Hunyuan3D-2。
- 在 AMD Radeon gfx1100（48 GB VRAM）上本地跑通核心推理。
- 修复 Hunyuan3D-2 `to()` 在 ROCm 上返回 `None` 的兼容性问题。
- 当纹理模块 CUDA 扩展无法编译时，自动 fallback 到正面投影贴图，保证链路可用。
- Celery 启用内存 backend，无需 Redis 即可演示。

---

## 应用场景

- 宠物 / 人物 3D 手办与纪念品
- 冰箱贴、钥匙扣、纪念币、浮雕奖牌
- 产品原型快速 3D 化
- 教育 / 创客空间 AI + 3D 打印教学

---

## 演示效果

- **2.5D 浮雕**：80×80×7 mm，watertight，体积 30 cm³，带彩色 GLB + 可打印 STL。
- **全彩 3D**：多视角输入 → 目标高度 80 mm → 彩色 GLB，支持 Web UI 预览。
- **多样化风格**：写实、卡通、低多边形、体素、粘土、素描、透光浮雕、剪影等。

---

## 开源与仓库

- **GitHub**：`SuppartWang/3DGenerateFlow`
- **README**：包含 ROCm 启动指南、依赖列表、Web UI 操作说明。
- **文档**：`docs/PROJECT_INTRO.md`、`docs/DEMO_SCRIPT.md`、`docs/POSTER.md`

---

**3DGenerateFlow —— 让每个人都能用 AMD GPU 把照片变成可打印的 3D 记忆。**
