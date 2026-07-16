# AGENTS.md — AMD Radeon Studio 项目 AI 工作规则

> **这是给所有 AI agent(包括我自己)工作的硬性约束。**
> 任何人/agent 接手本项目都必须遵守。规则优先级:本文档 > README > 临时对话。

---

## 1. 📐 面向文档编程(硬要求,用户的核心需求)

每次**新增/修改**功能模块,必须**先**在 `docs/modules/<name>.md` 写或更新设计文档。

每份模块文档必须包含 4 个固定章节:

1. **为什么这么设计** — 业务背景、选型理由、替代方案对比
2. **设计优点** — 这个方案的优劣
3. **能做什么** — 当前模块的输入/输出/能力清单
4. **做不到什么** — 明确边界,避免误用和过度承诺

**提交信息必须引用对应文档**(例: `docs(text2image): add SDXL pipeline`)。
没有文档的代码不能合并。

---

## 2. 🧱 代码规范(硬要求)

| 规则 | 说明 |
|---|---|
| **单文件 ≤ 300 行** | 超出必拆(职责/抽象/复用) |
| **设计模式必用** | 策略/工厂/单一职责/依赖注入 |
| **注释写"为什么"** | 解释意图,不重复代码(`# 把 GPU 缓存清掉,避免 OOM` ✓ / `# clear cache` ✗) |
| **分模块分目录** | `src/{core,models,api,ui,utils}`,跨目录的 import 走 `src.core.device` |
| **类型注解** | 公共函数必须有 type hint(Pydantic 优先于裸 dict) |
| **不要硬编码** | 设备名走 `core/device.py`;模型 ID 走 `config.py` |
| **inference 用 `torch.no_grad()`** | 推理路径禁止梯度计算 |

---

## 3. 📚 不重复造轮子(硬要求)

- 选库必须**给理由**;不知道**先问**用户
- 选型决策必须记录在 `docs/decisions/NNNN-why-X.md`(ADR 格式)
- 优先用成熟库:`diffusers` / `transformers` / `gradio` / `fastapi` / `pydantic`
- 能用现成 Pipeline 就别自己写 UNet

---

## 4. 🔁 标准流程(每次改动)

```
1. PLAN     → 更新 docs/PLAN.md 对应小节
2. DOCS     → 写/更新 docs/modules/<name>.md (4 章节)
3. CODE     → 写代码 + 注释 + 单元测试
4. TEST     → uv run pytest (全部测试必须绿)
5. LINT     → ruff / mypy 可选(暂不强制)
6. COMMIT   → git commit (格式见下)
```

**禁止跳过任何一步**。即使是小改也要跑测试。

---

## 5. 🗂️ 目录速查

```
src/core/         # 抽象层:模型基类、设备管理、Pipeline 工厂
src/models/       # 策略实现:text2image / img2img / style_transfer
src/api/          # FastAPI 后端:routes/ + schemas
src/ui/           # Gradio 前端:pages/ + components/
src/utils/        # 工具:image / io / logging
tests/unit/       # 单元测试(快、无 GPU 依赖)
tests/integration/# 集成测试(API 端到端)
docs/PLAN.md      # 总计划(5 天冲刺)
docs/architecture.md  # 架构图(Mermaid)
docs/modules/     # 每个模块的设计文档
docs/decisions/   # ADR 选型记录
scripts/          # 启动/部署脚本(.ps1 / .sh)
notebooks/        # Jupyter 开发笔记
```

---

## 6. 🐍 Python 环境

- **Python 3.11**(uv 管理,见 `pyproject.toml` 的 `requires-python`)
- **依赖管理**:uv,锁文件 `uv.lock` 必须提交
- **本地(Windows + NVIDIA CUDA)**:开发/语法测试,不跑大模型
- **部署(AMD Cloud + ROCm)**:实际跑模型,见 `scripts/prod.sh`
- **不要直接 `pip install`**,统一 `uv add` / `uv sync`

---

## 7. 📦 Git 规范

- **主分支**:`main`
- **提交格式**: `<type>(<scope>): <subject>`
  - type: `feat` / `fix` / `docs` / `refactor` / `test` / `chore`
  - scope: 模块名(`text2image` / `img2img` / `style_transfer` / `api` / `ui` / `core`)
  - 例: `feat(text2image): add SDXL pipeline with IP-Adapter`
- **每次提交前必须**:
  - 跑全部测试 `uv run pytest` → 全绿
  - 更新对应 docs(模块文档 + PLAN)

---

## 8. 🚫 不要做(黑名单)

- ❌ 单文件超 300 行不拆
- ❌ 改功能不写/不更新文档
- ❌ 选库/选方案不写理由
- ❌ 提交前不跑测试
- ❌ 直接 `pip install`(用 uv)
- ❌ 把模型权重、`outputs/`、`data/raw/` 提交进 git
- ❌ 在代码里硬编码设备名(用 `src/core/device.py`)
- ❌ 推理路径不用 `torch.no_grad()`
- ❌ 把 API key / token 提交进 git(用 `.env`,已在 .gitignore)
- ❌ 改 README/AGENTS.md 不走 PR/commit 流程

---

## 9. ⚠️ 当前项目硬约束(2026-07 比赛)

| 项 | 值 |
|---|---|
| 比赛 | AMD Radeon 开发者挑战赛 · 赛道一(多模态内容创作) |
| 部署平台 | AMD Radeon Cloud(Linux + ROCm) |
| 开发平台 | Windows + NVIDIA CUDA(语法测试) |
| 核心场景 | **3 个**:文生图 / 图生图 / 风格迁移 |
| UI 框架 | Gradio(模拟 LibLibAI 风格) |
| 模型栈 | SDXL + IP-Adapter + SDXL img2img + ControlNet |
| Python | 3.11(uv) |
| 截止 | 5 天冲刺(详见 `docs/PLAN.md`) |
| 仓库 | https://github.com/yaochang666/Radeon-hackathon-2026-07.git |

---

## 10. 🆘 当你不确定时

- 选库不确定 → 问用户,别瞎选
- 文档结构不确定 → 参照 `docs/modules/` 已有模板
- 设计模式不确定 → 参照 `src/core/base_model.py`(策略模式示范)
- 测试怎么写不确定 → 参照 `tests/unit/test_device.py`(无需 GPU 的纯逻辑测试示范)
- 与本规则冲突 → **以本文档为准**

---

_Last updated: 2026-07-16 · D1 初始化_
