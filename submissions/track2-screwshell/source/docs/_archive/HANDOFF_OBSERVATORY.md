# ScrewShell 观测台 — 需求 / 调查 / 交接文档

> 用途：给后续评审（如 DeepSeek）接手 ScrewShell「UI 观测台」方向时使用。
> 文档自包含：背景、用户需求、OpenCode 接入调查结论、已交付内容、已知缺口、文件与命令速查。
> 生成时间：2026-08-05。相关提交：`3fcf869`（观测台）、`d21f08a`（误标修复）、`d6b0fd1`（HANDOFF 文档修复），均**本地已提交、未 push**。

---

## 0. 背景（30 秒上手）

**ScrewShell** 是一个私有、本地、隐私优先的 AI 调查员，跑在单台 **AMD Radeon PRO W7900 48GB / ROCm** 上，使用 **MoL（Mixture-of-LoRA）**：冻结的基座 `Qwen3.6-27B-Q4_K_M` GGUF + 可热切换的 LoRA 专家（`btl3` / `cybersec` / `rag_n7` 等）。

**请求架构（三层）**：

```
UI(Gradio) ┐
opencode    ├─► relay(:18090, ScrewShell gateway) ─► llama-server(:8080)
pi         ┘        │ 全局单 LoRA 串行锁（一次只一个专家生效）
                    │ 唯一记录所有前端请求的中继（RequestEvent 存储）
```

- **relay 是单一数据源（SSOT）**：所有经它中转的请求（UI / opencode / pi）都会被记录成 `RequestEvent`，暴露给 UI 观测面板。
- **opencode / pi 是外部前端**：它们把 relay 当成 OpenAI 兼容的 `/v1/chat/completions` 端点使用，走自己的 tool loop，**不经过 ScrewShell 的 Python 编排器（orchestrator）**。

**关键文件**：

| 文件 | 作用 |
|---|---|
| `screwshell/ui/app.py` | Gradio UI（观测台在此） |
| `screwshell/gateway/relay.py` | 中继，暴露 `/v1/observ/{summary,events,gpu}` |
| `screwshell/observ/event.py` | `RequestEvent` 数据结构（含 `entry`/`adapter`/`user_msg`/`tool_calls`/`decode_tps`） |
| `screwshell/core/inference_coordinator.py` | 全局 LoRA 锁 + 串行 switch/generate |
| `screwshell/core/orchestrator.py` | ScrewShell UI 自己的编排器（`run_id` 在此生成并下传） |

---

## 1. 用户需求（整理自对话）

用户要的不是一个"聊天框 + 文字面板"，而是一个**观测台（observatory）**：一眼看清模型在干什么、性能是否健康、GPU 在怎么跑、权限/审计/证据/LoRA 切换是否实时。

**四条核心需求（R1–R4）**：

- **R1 · 模型在干什么——清晰可见**：实时状态（规划中 / 第几步 / 汇总中），而不是静态"调查中…"。
- **R2 · 性能明确**：指标不能只是裸数字，要带"正常/异常"判读（如首字延迟<5s 正常、解码 23–31 tok/s 正常、KV 命中应>80%）。
- **R3 · GPU 图形化 + 随时间变化的图表**（用户最在意的最大缺口）：当前 GPU 面板只是一行静态文字（VRAM%/利用率），**没有历史折线**。
- **R4 · 权限/审计日志、证据卡片、LoRA 切换更实时**。

**用户拍板的决策（本次构建依据）**：

- 图表技术栈：**`gr.LinePlot`**（Gradio 原生，零新依赖，实例离线可用）。
- 范围：**重做一站式观测台**（左对话 + 右仪表盘），不是只在旧面板上打补丁。
- 误标修复 `d21f08a`：**现在就部署**。

**用户隐含的偏好（贯穿全程）**：开箱即用、不要过度工程、实例大概率离线（不能依赖 CDN）。

---

## 2. 调查：OpenCode 调用能否被各面板 ingest（Turn 4）

**用户疑问**：用 OpenCode 时，LoRA / 工具流 / 证据卡 / 权限审计日志 / 活动流，有一部分没有更新出新日志——是不是某些面板接不了 OpenCode？

**调查方法**：
1. 读 `app.py` 的面板数据源（`panel_contents` 约 373–396 行），二分面板数据来源。
2. 用 opencode 格式的 tool-call 请求 live 打 relay，查 `/v1/observ/events` 验证 relay 是否真的捕获 opencode 流量。

**面板数据来源二分（决定谁接得了 opencode）**：

| 面板 | 数据来源 | OpenCode 更新？ | 原因 |
|---|---|---|---|
| 活动流（obs_recent） | relay `_obs_state` | ✅ 更新（标 `[opencode]`） | 全前端统一视图，relay 已 live 验证 |
| 工具流（tools） | relay `_obs_state` | ✅ 更新 | opencode 的 `tool_calls` 直接进 relay |
| GPU / 吞吐 / 指标 | relay `_obs_state` | ✅ 更新 | 全局瞬时值，与前端无关 |
| LoRA 切换轨迹 | relay `_obs_state` | ❌ 不更新 | opencode 走 `screwshell-base`、不传 `X-Expert` → relay `adapter=null`、无切换记录 |
| 证据卡片（evidence） | UI 编排器 `ctx.evidence` | ❌ 不更新 | 仅 ScrewShell UI 会话内部，opencode 不填 |
| 权限审计（audit） | UI 编排器 `ctx.gate.audit` | ❌ 不更新 | 同上，opencode 走自己的 loop |
| 计划（plan） | UI 编排器 `on_event` | ❌ 不更新 | 同上 |

**结论（回答用户）**：直觉"部分面板接不了 opencode"**对一半、错一半**。
- ✅ **接得了**：活动流、工具流（已 live 证明：relay 捕获 opencode 的 `user_msg` + `tool_calls`，`entry="api"`）。
- ❌ **接不了（且 by design）**：LoRA 切换轨迹（opencode 不切专家）、证据卡、权限审计、计划（这三类是 ScrewShell 自己编排器的内部产物，opencode 根本不进那个 `ctx`）。
- 对 opencode 来说，它的"审计/证据"实际上就是活动流里那一串 `tool_calls`——这块已经通。

**Live 证据（relay 实测返回）**：
```json
{"entry": "api", "adapter": null, "user_msg": "read the config file for me",
 "tool_calls": [{"name": "read_file", "args": "{...}"},
                {"name": "→tool_result", "args": "export RELAY_TRUST_TOKEN=..."}],
 "ok": true}
```
真机验证事件流（部署误标修复后）：
```
'ui'  'hi'                         ← 带 X-Run-Id 的请求（ScrewShell UI）→ entry=ui
'api' 'read the config file for me' ← opencode → entry=api
'api' 'hi'                         ← opencode → entry=api
```

---

## 3. 已交付（本次构建 + 部署）

**3.1 一站式观测台 `screwshell/ui/app.py`（commit `3fcf869`）**
- 左右分栏：**左 = 对话控制台，右 = 仪表盘**。
- 右栏含：① 独立**状态块**（phase + "已 Ns 生成中"，从对话气泡里抽出，模块级 `_UI_STATE` 供 2s timer 读）；② **GPU 时序折线图** `gr.LinePlot`（同时画 VRAM% 和 利用率%）；③ **解码速度时序折线图** `gr.LinePlot`（tok/s）；④ 指标 / LoRA 轨迹 / 工具流 / 活动流 / 证据卡 / 权限审计 / 计划。
- GPU 与吞吐的时序 = **UI 侧 `deque(maxlen=180)` ring-buffer**，每 2s 轮询 relay 的 `/v1/observ/gpu` + 取 recent events 的 `decode_tps` 累积。**不加任何后端依赖、纯离线**。

**3.2 误标修复 `d21f08a`（已包含在部署中）**
- `orchestrator` 每次会话生成 `run_id`，下传给 `engine.chat(run_id=...)` → `MoLLlamaCpp` 转成 `X-Run-Id` 头 → relay 读到后把事件标 `entry="ui"`。
- 修复前：UI 自己的请求不带 `run_id` → 被误标 `[opencode]`（Turn 2 用户实测 5 条全标错）。
- 已用 live 请求验证：`entry='ui'`（UI）/ `'api'`（opencode）区分生效。

**3.3 部署（实例 `36.150.116.206:31010`，UI `:7860`）**
- scp `app.py` + `orchestrator.py` 到 `/workspace/persistent/screwshell_run/screwshell/...`，杀旧 UI、用**与现网完全相同的环境**重拉起。
- 验证：UI `:7860` **HTTP 200**，ui.log 零报错（timer 多次刷新 `gr.LinePlot` 无异常）；relay `/v1/observ/gpu` 返回真实数据（`used 29.3/51.5 GB`，`ok:true`）。

---

## 4. 已知缺口 / 待 DeepSeek 评估的点（诚实列出）

> 这些不是"bug"，是设计边界或未做的增强。DeepSeek 接手时请重点评估 G1 / G2。

- **G1 · 证据卡 / 权限审计 / 计划对 opencode 仍为空（by design）**。
  要不要让 opencode 也出现在这些面板？两条路：
  - 小改：明确把这些面板标注为"ScrewShell 会话内部"，接受"活动流覆盖所有前端"的定位。
  - 大改（架构级）：让 **relay 也为外部前端请求合成结构化事件**（证据/审计/计划推导），UI 统一消费。这才算"真正统一"的观测，但是 backend 改动，不是补丁。
- **G2 · GPU 时序是 UI 侧 ring-buffer，不是后端历史**。
  relay 的 `/v1/observ/gpu` 现在**只返回即时值**（3s 缓存），`RequestEvent` 无 GPU 字段、observ store 不存 GPU 时间序列。当前方案靠 UI 每 2s 轮询累积，实例重启即丢历史、且多卡不支持。若要多卡 / 更长历史，需在 relay 加 ring-buffer 采样。
- **G3 · 图表用 `gr.LinePlot`（基于 Altair）**。实例离线可用；但若要悬浮/缩放/更花哨，需换 Chart.js（CDN 离线挂）或 Plotly（需 pip 装，实例可能离线装不了）。
- **G4 · 刷新机制**：状态块/面板靠 `gr.Timer(2.0)` + `respond` 生成器双写同一批组件，可能有轻微闪烁，目前未见功能 bug。
- **G5 · 部署未 push**：`3fcf869` + `d21f08a` + `d6b0fd1` 三个提交本地领先 `origin/main`，未 push。
- **G6 · 重启勿误用旧脚本**：实例上有 `_run_ui.sh`（指向 `:8080` 直连 llama-server）和 `_run_ui_gw.sh`（指向 `:18080` llama-swap），**都不是现网 relay `:18090`**。重启必须用下面"命令速查"里的环境，否则破坏 relay 集成。
- **G7 · gradio 版本陷阱**：实例 venv 是 **gradio 6.22.0**（不是 `requirements.txt` 写的 `>=4.44`）。**gradio 6 删掉了 `Chatbot(type=...)` 参数**——本次首版因此 `TypeError` 崩，去掉后才起得来。后续改 UI 注意。

---

## 5. 给 DeepSeek 的建议切入点

1. **想要"真正统一"的观测（含 opencode 的证据/审计）→ 从 relay 入手**（G1 大改路线）：让外部请求也产出结构化事件，UI 统一消费。这是架构级改善，比在 UI 上打补丁更根治。
2. **或接受现状定位**：relay 是 SSOT、活动流覆盖所有前端；证据/审计明确标注为"ScrewShell 会话内部"。这是最小改动、最稳。
3. **GPU 图表若要"生产级"**（G2）：在 relay 侧加 GPU 采样 ring-buffer（`observ/store.py` 或 coordinator），UI 改为消费后端历史；同时支持多卡。
4. 任何改动请保持**离线可用、零新重依赖**的约束（用户明确偏好）。

---

## 6. 文件与命令速查

**关键文件**
- `screwshell/ui/app.py` — 观测台（本次主要改动，`3fcf869`）
- `screwshell/core/orchestrator.py` — `run_id` 生成/下传（`d21f08a`）
- `screwshell/gateway/relay.py` — `/v1/observ/*` 端点
- `screwshell/observ/event.py` — `RequestEvent`
- `HANDOFF_MACHINE_SWITCH.md` — 换机部署流程（§2 实测链路、§2.5 opencode 配置）

**实例（36.150.116.206:31010）UI 重启命令（环境照抄，勿用旧脚本）**
```bash
cd /workspace/persistent/screwshell_run
export MOL_BACKEND=llamacpp
export MOL_LLAMACPP_URL=http://127.0.0.1:18090
export MOL_RELAY_MODE=1
export RELAY_TRUST_TOKEN=screwshell-relay-devtoken
nohup /opt/venv/bin/python -m screwshell.ui.app \
  --workspace /workspace/persistent/screwshell_run/demo_workspace \
  --base /workspace/persistent/screwshell_run/models/Qwen3.6-27B-Q4_K_M.gguf \
  --port 7860 --no-rag > ui.log 2>&1 &
```

**本地验证（经 SSH 隧道）**
- UI：`curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:7860/`
- relay GPU：`curl -s -H "X-Relay-Token: screwshell-relay-devtoken" http://127.0.0.1:18090/v1/observ/gpu`
- relay 活动流：`curl -s -H "X-Relay-Token: screwshell-relay-devtoken" "http://127.0.0.1:18090/v1/observ/events?n=5"`

**opencode 侧配置（本机 `C:\Users\djb\.config\opencode\opencode.json`）**
- provider `screwshell`：`baseURL=http://127.0.0.1:18090/v1`，`apiKey` + `X-Relay-Token` 头，模型 id `screwshell-base`（**不是** 旧的 `m`）。
