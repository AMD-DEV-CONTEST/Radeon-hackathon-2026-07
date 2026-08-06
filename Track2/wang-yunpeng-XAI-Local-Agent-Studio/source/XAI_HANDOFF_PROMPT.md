# XAI 统一操作台 — 项目交接提示词

> 复制以下全部内容到新对话，AI 即可接管此项目。

---

你正在协助维护「XAI 统一操作台」——一个本地私有化的 AI 工作中枢，跑在 macOS 上。

## 项目概览

- **仓库**: `/Users/Admin/Desktop/mask/xai/`
- **数据目录**: `~/.xai/`（SQLite 数据库、日志、配置）
- **运行服务**: launchd 守护 `com.xai.server`，绑定 `127.0.0.1:8000`
- **桌面入口**: `~/Desktop/XAI.app`（双击打开浏览器到 localhost:8000）
- **技术栈**: Python 3.13.12 纯标准库零外部依赖 + React 18 + Vite + TypeScript + Tailwind（液态玻璃 UI）

## 架构关键文件

- `server_xai.py` — 主入口（HTTP 服务基础设施）
- `server_router.py` — 绞杀者路由器（router 优先 dispatch）
- `server_routes_*.py` — 22 个按领域拆分的路由处理器
- `core/kernel/engine.py` — 主引擎
- `core/kernel/workflow.py` — 工作流 DAG 执行 + 节点处理器
- `core/node_registry.py` — 节点类型 → 处理函数映射表
- `core/adapters/openclaw_adapter.py` — 真实 shell/文件/浏览器执行（6 个本地工具）
- `core/openclaw_gateway.py` — 能力展示抽象层（Gateway，与上面是两套系统）
- `core/kb.py` — 知识库（BM25 + 稠密向量混合检索，dense_available=true）
- `core/memory_core.py` — 8 层记忆系统
- `core/grok_build_engine.py` — Grok Build 引擎
- `core/grok_history_store.py` — Grok 运行历史（自有 SQLite）
- `core/guardian.py` — P0/P1/P2 风险分级审批
- `frontend/src/` — React 前端源码

## 日常运维

```bash
# 重启服务（改 .py 后必须）
launchctl kickstart -k gui/$(id -u)/com.xai.server

# 前端构建（注意 vite build 的 emptyOutDir 会被 WorkBuddy 拦截）
cd /Users/Admin/Desktop/mask/xai/frontend && npx vite build --emptyOutDir false

# 冒烟自检（38 端点，目标全绿）
cd /Users/Admin/Desktop/mask/xai && python3 scripts/smoke_test.py

# 诚实度审计（13 项，目标全 PASS）
cd /Users/Admin/Desktop/mask/xai && python3 scripts/honesty_check.py

# 桌面 APP 若报"已损坏"
xattr -cr ~/Desktop/XAI.app
codesign --force --deep --sign - ~/Desktop/XAI.app

# 鉴权 token（所有 /api/* 需此头）
cat ~/.xai/.server_token
# 调用示例: curl -H "X-Auth-Token: $(cat ~/.xai/.server_token)" http://127.0.0.1:8000/api/...
```

## 设计铁律（不可违）

1. 不改配色/字体/圆角/毛玻璃
2. 不改 App.tsx 顶层布局
3. 不改 AppHeader 结构
4. 不改 Sidebar 导航
5. 新页面符合 `glass-*` CSS 类
6. 优先用已有 `var(--color-*)` 颜色变量
7. 必须亮/暗双主题
8. 功能叠加不推翻
9. 新功能加 Sidebar 项或 EditorSidePanel 项

## 开发铁律

- **路由优先**：` router.add()` 优先级高于 `server_xai.py` 里的 `do_GET/do_POST` 遗产链。改路由前必 `grep -rn "router.add" server_routes_*.py`
- **建议≠授权**：改文件/起服务/重构/装包/删文件需用户明确说"开干/做 X"
- **删文件三铁律**：删前 tarball 备份到仓库外 + 写 manifest；删前全仓库引用扫描；删后 py_compile + 重启 + e2e
- **改 .py 后必须 pkill 或 kickstart 重启**
- **不脑补**：未查明就说不清楚，不发虚假报告

## 当前环境

- **Ollama embeddings**: `127.0.0.1:11435`（launchd `com.ollama.11435`，模型 `nomic-embed-text`，KeepAlive）
- **llama.cpp 聊天**: `127.0.0.1:11434`（模型 `deepseek-r1-32b-abliterated`）
- **Grok Build 复用主程序 DeepSeek key**：`core/grok_build_engine.py` 的 `_shared_model_env()` 从 `~/.xai/models.json` 读取

## 问题清单现状（2026-07-27）

### 已闭环（不要重复修）

| 项 | 状态 |
|----|------|
| distill 下架 | 已修（GET/POST 均 deprecated） |
| OpenClaw 模拟标注 | 已修（前端横幅 + gateway 诚实化） |
| token 本机校验 | 已修（127.0.0.1/::1 校验） |
| 记忆项目隔离 | 已修（store 加 project_id） |
| 历史 stub 清理 | 已修（cleanup_stub_residue.py） |
| GEPA 横幅 / XAI.app | 已修 |
| /api/save 路径穿越 | 已核已修（ext isalnum 净化） |
| KB 语义搜索 | 已修（Ollama 11435 + nomic-embed-text, dense=true） |
| workflow 真跑 | 已修（新增 wf_node_openclaw 调度 6 工具） |
| gateway 诚实度 | 已修（per-capability 细分 + 引擎探测） |
| sandbox 诚实标注 | 已修（note 字段） |
| Ollama 持久化 | 已修（launchd plist） |
| 诚实度审计 | 已修（scripts/honesty_check.py, 13/13 PASS） |
| 自检假报告 | 已修（Turn5 真探针 + 思考剥离） |
| 思考泄漏 | 已修（Turn6 双段分流） |
| GrokConsole 历史 | 已修（Turn9 自有 SQLite） |
| GrokConsole 布局 | 已修（v2/v3） |
| grok --check flag 漂移 | 已修（_detect_grok_features 动态探测） |
| StubBackend 静默 | 已修（改显式 logger.warning） |
| Loop Safety 空写 | 已修 |

### 待设计决策（等痛了再修）

- ⑩ server_xai.py 拆分（router 已就绪，等下一次因为"太长找不到"导致的 bug 时顺手拆）
- ⑪ 模型池合并（前端名字统一映射，非功能缺陷）
- ⑫ webhook 触发器（等真实场景驱动）

## 验证状态

- 冒烟自检：38/38 全绿
- 诚实度审计：13/13 ALL PASS
- KB paraphrase recall@3：100%

## 禁止操作

- 不要删除 `.workbuddy/` 目录（项目数据，非临时缓存）
- 不要改 Ollama 11435 的端口绑定
- 不要重启 llama.cpp 11434（会打断 Grok Build 本地模型）

---

*此提示词生成于 2026-07-27，由 WorkBuddy 对话产出。项目当前处于"执行链已通 + KB 语义已通 + 诚实度可验证"状态。*
