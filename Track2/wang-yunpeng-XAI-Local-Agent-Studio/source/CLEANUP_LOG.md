# XAI 项目废代码清理记录（CLEANUP LOG）

> 2026-07-24 执行。原则：删除跟主线（XAI 统一操作台 v4）无关的废代码与程序，**仅留文字记录**。
> 所有主线运行时依赖经逐项引用分析确认后保留，未误删。

## 一、主线边界（保留 — 产品本身）

**后端**：`server_xai.py`（入口）、`server_router.py`、`server_runtime.py`、全部 23 个 `server_routes_*.py`
（注意：`server_routes_backup.py` 名字有误导性，实为 server_xai.py `import` 的主线依赖，非备份）、
`core/`（含 adapters/kernel/cognition/runner）、`xai-backend/data/`（运行时 orchestrations.json 存储，server_xai.py 4 处引用）、
`degradation_chain.yaml`（core/kernel/engine.py 读取的降级链配置）。

**前端**：`frontend/`（V4 官方产品）。

**启动/测试/配置**：`xai_launcher.py`、`xai_read_key.py`、`xai_go.sh`、`启动XAI*.command`、`tests/`、`requirements-dev.txt`、`.gitignore`、`.github/`。

**文字记录（全部保留）**：所有 `.md` 文档、`docs/`、`SYSTEM_OVERVIEW.html`、`output/xai_architecture.html`。

## 二、已删除清单（废代码/程序）

### A. 早期外部参考仓库 / 原型（能力已内化到 core/，无 import / 无 sys.path / 无 subprocess 调用）

| 目录 | 体积 | 判定依据 | 来源（可重新 clone 恢复） |
|------|------|---------|--------------------------|
| `vendor/MemOS` | 36M | 参考仓库，主线不 import | https://github.com/MemTensor/MemOS.git @main 13fbd43 |
| `vendor/OllamaFlow` | 9.7M | 参考仓库（C3 漂移根源） | https://github.com/richardyang92/OllamaFlow.git @main 8e75f9c |
| `vendor/hermes-agent` | 220M | 参考仓库，能力已落地 core/adapters/hermes_adapter.py | https://github.com/NousResearch/hermes-agent.git @main 0f102fa |
| `vendor/openclaw` | 451M | 参考仓库，能力已落地 core/adapters/openclaw_adapter.py | https://github.com/openclaw/openclaw.git @main 765bb373 |
| `rust/`（xai-grok-guardian/meta/reason/runner + target） | 29M | 早期 rust 原型，已被 core/runner.py、core/cognition/reasoner.py 的 Python 落地取代，无二进制调用 | 仅在本项目 git 历史 |
| `xai-frontend/` | 932M | V1 legacy 旧前端，V4 `frontend/` 已完全取代 | https://github.com/richardyang92/OllamaFlow.git @main b8c6957（即 OllamaFlow 模板 clone） |

### B. 无关程序 / 旧产物（git 历史可恢复）

| 目录/文件 | 体积 | 判定 |
|-----------|------|------|
| `tetris-3d/` | 32M | 俄罗斯方块 3D demo，与主线完全无关（原已 gitignore） |
| `XAI.app/` | 12K | 旧打包 mac app（含 .bak.20260720 备份），非主线启动方式 |
| `guardian_plugins/` | 12K | guardian_service.py + openclaw_hook.sh，无任何引用 |
| `examples/` | 4K | smoke.py 示例脚本，非主线 |
| `scripts/` | 12K | migrate_memory.py（一次性迁移）+ test-all.sh（便利脚本），非运行时依赖 |

### C. 垃圾 / 临时文件

`__pycache__/`（各级）、`.pytest_cache/`、`.DS_Store`（多个）、`server_xai.pid`（运行时会重建）、`from_mavis.log`（日志，已取消 git 追踪）。

## 三、恢复方式

- A 类嵌套仓库：按上表 URL + commit `git clone` 后 `git checkout <head>` 即可恢复到删除时状态。
- B 类目录：`git checkout <删除前 commit> -- <路径>` 从本仓库 git 历史恢复。
- 主线未受影响：清理后端到 `:8000` 健康自检 + 12 页真机 smoke 全绿。

## 四、清理效果

- 释放磁盘约 **1.7GB**（vendor 716M + xai-frontend 932M + rust 29M + tetris-3d 32M + 零头）。
- 项目根目录从探索期的混杂状态收敛为「主线代码 + 文字记录」两类。