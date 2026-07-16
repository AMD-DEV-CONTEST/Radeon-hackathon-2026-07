# AMD Radeon Studio — 总实施计划(PLAN)

> 5 天冲刺 · 3 个核心场景 · 3 天实施 + 1 天 UI + 1 天部署验证
>
> 详细任务分配见 `docs/modules/`,选型理由见 `docs/decisions/`,工作规则见 `AGENTS.md`

---

## 1. 项目背景

| 项 | 值 |
|---|---|
| 比赛 | AMD Radeon 开发者挑战赛 · 赛道一(多模态内容创作) |
| 目标 | 在 AMD Radeon GPU + ROCm 上跑一个实用、轻量级、高性能的多模态 AI 创作工具 |
| 仓库 | https://github.com/yaochang666/Radeon-hackathon-2026-07.git |
| 部署平台 | AMD Radeon Cloud(https://radeon-global.anruicloud.com/)— Linux + ROCm 6.1+ |
| 开发平台 | Windows + NVIDIA CUDA(语法/逻辑测试,大模型在 AMD Cloud 跑) |

---

## 2. 范围(v0.1)

### ✅ 包含
1. **文生图 (text2image)** — SDXL,基于 diffusers
2. **图生图 (img2img)** — SDXL img2img + ControlNet(可选)
3. **风格迁移 (style_transfer)** — IP-Adapter + SDXL
4. **Web UI** — Gradio,LibLibAI 风格(白底 + 左侧深色栏 + 瀑布流)
5. **环境验证** — `notebooks/00_env_check.ipynb`

### ❌ 不包含(v0.2+)
- 图生视频(Wan2.1)
- 画质增强(Real-ESRGAN)
- Agent 一键短片
- ComfyUI 集成
- 自动部署 CI/CD

---

## 3. 5 天冲刺路线

| Day | 任务 | 关键交付 | 验证 |
|---|---|---|---|
| **D1** | 项目初始化 | git + AGENTS.md + uv + docs 框架 + 目录骨架 | `uv run pytest` 全绿 |
| **D2** | 文生图模块 | `BaseModel` + `Text2ImageSDXL` + API + UI stub | 单元测试 + AMD Cloud 跑通 SDXL |
| **D3** | 图生图模块 | `Img2ImgSDXL` + ControlNet + API + UI | 单元测试 + AMD Cloud 跑通 |
| **D4** | 风格迁移 | `StyleTransferIPAdapter` + API + UI | 单元测试 + AMD Cloud 跑通 |
| **D5** | Gradio UI + 部署 | LibLibAI 风格 UI + 部署 AMD Cloud + 录 demo | UI 截图 + 演示视频初剪 |

---

## 4. 每个模块的子任务模板(D2/D3/D4 共用)

1. 写 `docs/modules/<name>.md`(4 章节:为什么/优点/能做什么/做不到什么)
2. 写 `src/models/<name>.py`(< 300 行,继承 `BaseModel`)
3. 写 `src/api/routes/<name>.py`(FastAPI route)
4. 写 `src/ui/pages/<name>.py`(Gradio page)
5. 写 `tests/unit/test_<name>.py` + 跑 `uv run pytest`
6. AMD Cloud 上跑 `notebooks/0X_<name>.ipynb` 验证(可选)

---

## 5. 部署流程(本地 → AMD Cloud)

```powershell
# === 本地(Windows) ===
# 1. 开发 + 单元测试
uv run pytest
uv run jupyter lab   # 跑测试 notebook

# 2. 提交
git add -A
git commit -m "feat(text2image): ..."
git push origin main
```

```bash
# === AMD Cloud (Linux + ROCm) ===
# 1. 拉代码
git clone https://github.com/yaochang666/Radeon-hackathon-2026-07.git
cd Radeon-hackathon-2026-07
uv sync --extra dev

# 2. 装 ROCm 版 PyTorch
uv pip install torch torchvision --index-url https://download.pytorch.org/whl/rocm6.1

# 3. 跑 env_check 验证
jupyter lab notebooks/00_env_check.ipynb

# 4. 启动 UI
chmod +x scripts/prod.sh
./scripts/prod.sh ui
# 浏览器打开 JupyterLab 给的端口映射 URL
```

---

## 6. 风险 & 缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| ROCm 装不上 | 中 | 高 | AMD Cloud 预装环境,跳过本地 ROCm 安装 |
| SDXL 显存不够 | 中 | 高 | 优先 SD-Turbo(快,2GB);prod 用 SDXL base(6.5GB) |
| Gradio UI 太慢 | 低 | 中 | 异步加载模型 + `show_progress="minimal"` |
| IP-Adapter 兼容问题 | 中 | 中 | 锁版本:`diffusers==0.30.x` + `transformers==4.44.x` |
| 5 天赶不完 | 中 | 高 | 严格 5 天,超时就砍 v0.2+ 功能(图生视频/画质增强) |

---

## 7. 验证标准(D5 末)

- [x] D1: 目录结构 + 文档 + git + 测试就绪
- [ ] D2: 文生图模块 — 文档 + 代码 + 测试 + AMD Cloud 跑通截图
- [ ] D3: 图生图模块 — 文档 + 代码 + 测试 + AMD Cloud 跑通截图
- [ ] D4: 风格迁移模块 — 文档 + 代码 + 测试 + AMD Cloud 跑通截图
- [ ] D5: Gradio UI 跑通 + demo 视频初剪 + 提交物清单

---

## 8. 当前进度

| Day | 状态 |
|---|---|
| D1 | 🟡 进行中(本 plan 文档) |
| D2 | ⚪ 待开始 |
| D3 | ⚪ 待开始 |
| D4 | ⚪ 待开始 |
| D5 | ⚪ 待开始 |

---

_Last updated: 2026-07-16 · D1_
