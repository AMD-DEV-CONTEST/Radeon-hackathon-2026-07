# 交接：ScrewShell 重定位 + llama.cpp tool 调用失效调查（2026-08-03）

## 0. 当前实例实时状态（u-14441-f4391bc7 @ 36.150.116.206:31010）

- SSH 通（passwordless，BatchMode 已验证）。
- llama-server：PID 1223，`/opt/llama.cpp/build/bin/llama-server`（注意：真实路径是
  `/opt/llama.cpp`，**不是** `/opt/llama.cpp.new`——之前笔记记错，已修正并提交本机
  `docs/SSH_AND_STARTUP_NOTES.md`）。
- 监听 `127.0.0.1:8080`，OpenAI 兼容 `/v1`。
- Gradio UI：PID 1820，`/opt/venv/bin/python -m screwshell.ui.app`，监听 `:7860`，
  运行正常（HTTP 200），后端连 `:8080`。
- venv：`/opt/venv`，gradio 已从丢失状态重装（gradio 6.22.0，2026-08-03 修复）。
- 本机已起**后台常驻 SSH 隧道**（7860+8080 转 localhost），本机访问：
  - UI → http://localhost:7860
  - llama-server → http://127.0.0.1:8080/v1

## 1. 产品定位决策（已与用户确认，2026-08-03）

ScrewShell **保留自研网页对话 agent**（Gradio UI → 自研 ReAct orchestrator），同时
**兼容成熟前端**（opencode / pi）零改造接入。硬性要求：**必须兼容原生
OpenAI `tools` 协议**。注意：按 2026-08-03 最终决策，opencode/pi **不直接连 llama-server**，
而是连 **ScrewShell 中转网关**（ScrewShell 暴露同一 `/v1` 接口，处理后转发给 llama-server）；
§3 的 D 项是"直连 llama-server 验证模型能力可达"的**调查证据**，证明可行性，不代表最终部署拓扑
（最终拓扑见 §1：前端 → ScrewShell 中继 → llama-server）。

- 自研 orchestrator（screwshell/core/orchestrator.py）**继续作为核心能力之一保留**，
  Toolkit（screwshell/tools/toolkit.py 的 6 个工具 + 权限门禁）、metrics / autotune / router
  的 LoRA 热切逻辑**可复用**。
- **规划中的统一观测/调优层**（gateway 五层，见 §4）目标是让自研 UI 与 opencode/pi
  **两种入口共享同一套可观测信号与调优旋钮**——此层**尚未实现，属计划态**（与 `docs/TRUTH.md` §1.7 一致）。
- 方案收敛于 §4 两方向（gateway 自动化配置/可观测 + UI 等价对话驱动 e2e 优化），待实现。

## 2. 用户体感与根因初步判断

用户："ScrewShell 没法调用工具，不像现代 agent（至少得像 pi）。"
实测核验结论（2026-08-03）：
- ScrewShell **有完整 tool layer**（rag_search/read_file/list_dir/grep/shell_readonly/rocm_smi
  + PermissionGate + 审计），不是"不能调工具"，而是它**自写 ReAct + 把 tool schema 塞进
  prompt 文本靠正则解析**，对模型输出格式极脆弱。
- 体感"调不动工具"的真正根因在**部署端**，见 §3。

## 3. 🔴 核心待调查：llama.cpp + Qwen3.6-27B 在 opencode 里 tool/MCP 调用失效

用户记忆：官方版 llama.cpp + Qwen3.6-27B **本应能**在 opencode 里正常调工具和 MCP。
当前实例跑不起来，怀疑是**部署配置问题，非模型/架构问题**。需下一个 agent 调查。

### 已采集的硬证据（2026-08-03，实例上实测）

1. **`/v1/models` 返回的 `capabilities` 只有 `["completion"]`**
   —— llama.cpp 启用 tool 支持且 chat template 正确时，会暴露 `tools` capability。
   当前构建（version 9766 / commit 035cd8f9a）**没有 `tools` 能力标记**，是首要嫌疑。
   可能原因：
   (a) 该 llama.cpp 构建**未编译 tool/function-calling 支持**；
   (b) Qwen3.6-27B GGUF **chat template 缺失/不对**，server 无法识别 function-calling；
   (c) 启动参数缺 `--reasoning-budget` / jinja template 相关开关。

2. **实测发带 `tools:[{function:test}]` 的 `/v1/chat/completions` 请求**：
   - 不带 tool_choice：模型直接走 `reasoning_content`（thinking 开启），吐 reasoning 后
     `finish_reason:"length"`，**返回里无 `tool_calls` 字段**。
   - 说明 enable_thinking 默认开，模型跑去"思考"而非产出 tool_call；且 server 没把
     tools 编进 prompt / 没要求结构化输出。

3. **启动参数与脚本不一致（关键矛盾）**：
   - `_run_roomy_server.sh` 写的是：
     `--lora btl3,cybersec,rag_n7 --alias m --host 127.0.0.1 --port 8080 --ctx-size 8192 --n-gpu-layers 999 --threads 24`
   - **实际运行进程 PID 1223 的 cmdline 只有**：
     `--model ... --host 127.0.0.1 --port 8080`
   - 即：当前跑的 llama-server **没挂任何 LoRA、没设 ctx-size、没设 n-gpu-layers**，
     是裸 base。这是之前某次手动/重启拉起留下的，与脚本严重不一致。
   - 后果：外部前端调进来时连 MoL 路由都触发不了（router 在 screwshell orchestrator
     里，且 LoRA 没挂），只看到裸 base。

4. **路径记错**：笔记里 llama.cpp 写成 `/opt/llama.cpp.new`，真实是 `/opt/llama.cpp`
   （`.new` 目录不存在）。`/opt/llama.cpp/build/bin/llama-server` 才是真身。

### 下一个 agent 的调查清单（按顺序）

- [x] **A. 确认构建是否支持 tools**（2026-08-03 已查）：
  - 构建 `version 9766 (035cd8f9a)`，command-line tool calling 支持（PR #9639）早已合入，
    **无需重 build**。当前 `/v1/models` 无 `tools` capability 的根因是**启动没加 `--jinja`**，
    不是构建缺失。
- [x] **B. 确认 Qwen3.6 GGUF 的 chat template**（2026-08-03 已查）：
  - 用二进制扫描 GGUF 元数据（不跑推理，避免 27B 卡死），确认 GGUF **自带完整 Qwen3.6
    tool-use chat template**（含 `tools` 渲染宏 + `<tool_call>` 格式 + tool 回包解析），
    **无需额外 `--chat-template-file`**。即官方 llama.cpp + 此 GGUF 本应能回 `tool_calls`。
- [x] **C. 对齐启动参数并重启验证**（2026-08-03 **已做**）：kill 原裸 base PID 1223，用修正后的
  `start_llama.sh`（base + `--jinja` + ctx/gpu-layers/threads）重启，新 PID 2536。
  - 实测 §3.2 的 tools 请求 → **`finish_reason: tool_calls`**，`tool_calls=[{name:get_weather,
    arguments:{"location":"Paris"}}]`，标准 OpenAI 格式。**根因彻底坐实：之前就是缺 `--jinja`**。
  - ⚠️ 注意：本版本 llama.cpp 的 `/v1/models` **`capabilities` 字段恒为 `["completion"]`**，
    **不反映 tools 真实支持度**——别再被这个字段误导（见 §8）。判断 tools 是否生效请直接发
    tools 请求看是否回 `tool_calls`。
- [x] **D. 用本机 opencode 实测**（2026-08-03 **已做**，等效验证）：隧道转 8080→localhost 已通，
  本机 `opencode.json` 的 `llama-local` provider（baseURL `http://127.0.0.1:8080/v1`，
  model `qwen3.6-27b-q4_k_m`）已就位。本机经隧道发**带 `tools` 字段 + system 非首条**的请求
  （正是 opencode issue #1890 会崩的场景）→ 稳定回 `finish_reason: tool_calls` +
    `tool_calls=[{name:list_dir, arguments:{"path":"."}}]`，无 500。**结论：opencode 配置链路
    完全通，本地模型已能获得现代 agent 工具能力**。（完整交互式 opencode 会话待用户本机跑。）
    ⚠️ 此处的 baseURL 直连 `:8080`（llama-server）是**验证模型能力可达**的手段；最终部署拓扑
    按 §1 决策改为 opencode → ScrewShell 中转网关 → llama-server，opencode 的 baseURL 应指向
    ScrewShell 暴露的端口而非裸 llama-server。
- [ ] **E. 竞品对照**：确认官方 llama.cpp + Qwen3.6 在 opencode 里 tool 正常的先决条件
  （构建版本 / 启动参数 / template），列出本实例与之的差异清单。

### 互联网调研结论（2026-08-03，下一个 agent 必读）

正常情况下 **llama.cpp + opencode/pi 完全能调工具**，前提是启动加 `--jinja`：
- 官方 `docs/function-calling.md`：function calling 靠 `llama-server --jinja` 启用 Jinja
  chat template；Qwen 系列在**原生支持列表**；返回标准 `finish_reason:"tool"` +
  `message.tool_calls`，opencode/pi 直接解析。
- 真实案例：Qwen3.5-27B + llama.cpp + opencode 实测 agentic coding/tool calls/skills 全正常
  （启动项 `--jinja --chat-template-kwargs '{"enable_thinking":true}'`）；Qwen30B + opencode
  "handles tool calls extremely well"；GLM-4.7-Flash + llama.cpp + opencode 也跑通。
- **失败根因几乎全是没 `--jinja` / template 错**：opencode issue #1890 显示不带 `--jinja`
  时 llama.cpp 直接拒 `tools` 参数（`tools param requires --jinja flag`）；带 `--jinja` 但
  Qwen template 缺 filter 会 500。这**强力支撑**交接里"根因在部署端、非模型/架构"的判断。
- 对照本实例三重缺失：① 没 `--jinja`（致命）② 裸 base 无 template 应用 ③ 没按脚本挂
  LoRA/ctx/gpu-layers。`capabilities:["completion"]` 正是没开 jinja tool 支持的直接信号。
- [ ] **D. 用本机 opencode 实测**（隧道已通）：把 opencode 模型 base_url 指向
  `http://127.0.0.1:8080/v1`，model = gguf 路径，实际发一个需要 tool 的任务，验证
  opencode 的 tool/MCP 调用是否恢复。这是对"官方能成、本实例不成"假设的最终验证。
- [ ] **E. 竞品对照**：确认官方 llama.cpp + Qwen3.6 在 opencode 里 tool 正常的先决条件
  （构建版本 / 启动参数 / template），列出本实例与之的差异清单。

## 4. 后续方向（已与用户拍板，2026-08-03）

§3 实测结论已定：**原生 llama-server + 正确配置（`--jinja` + 合适 ctx-size + `--reasoning-budget`）
已能让 opencode/pi 零改造拿到完整 tools 能力**。由此方案分叉收敛为以下两个既定方向，
不再纠结 X/Y：

### 方向 1：gateway 做「自动化的、可观测的、不会踩坑的」本地模型配置层

gateway 不是"补前端工具缺口"（那已是部署配置本该兜住的），而是把本次手调踩过的坑
**自动化掉**。覆盖五层（即"部署配置黑洞"，每个都有真实踩坑证据）：

1. **部署配置层**：按模型/硬件自动生成最优启动参数（路径、LoRA 路由、`--jinja`、
   ctx-size、gpu-layers、threads），不再依赖易错的手写 shell 脚本（踩坑：裸 base PID 1223
   漏 `--jinja` + 没挂 LoRA，工具调不动）。
2. **可观测层**：暴露**真实**健康信号——tools 实际可用性（发 tools 请求探活，不是看
   `capabilities` 假字段）、首 token 延迟、思考耗时占比、KV 占用（踩坑：`capabilities`
   恒为 `["completion"]` 误导判断）。
3. **容量规划层**：按 W7900 48GB 自动算 ctx-size 上限，e2e 报表用真实数据（踩坑：8K→32K→
   128K 逐级放大才够 opencode 用）。
4. **推理调度层**：非 agentic 请求关 thinking 换快 ack，agentic 请求给合理 `--reasoning-budget`
   （踩坑：默认 budget 无限，一个 "hi" 卡 133s+）。
5. **可靠性层**：进程守护（setsid 脱离 SSH，勿裸 nohup）+ 启动前配置校验（端口占用、二进制
   路径、模型存在），避免静默退出（踩坑：`nohup` 被回收 / 端口未释放 `couldnt bind`）。

gateway 复用现有 `mol_engine_llamacpp.chat` 的 `grammar` / `json_schema` 参数做脆弱格式
强制约束（可选增强，非必需）。

### 方向 2：UI 对话 == opencode 接口对话，UI 提供可观测面板驱动 e2e 优化

- **等价性**：shell 网页 UI（`screwshell.ui.app` :7860）走的和 opencode 走的是**同一个
  llama-server 接口**（同一个 `/v1`，同一个模型，同一套配置）。UI 不是另一个后端，是同一
  后端的另一个前端。
- **UI 的可观测职责**：在网页 UI 上展示方向 1 的可观测信号（思考耗时、tool_calls 明细、
  首 token 延迟、KV 占用、LoRA 路由命中），让"用 UI 对话"同时成为"采集 e2e 优化数据"的入口。
- **闭环**：UI 对话体感差（卡/无工具/上下文爆）→ 可观测面板定位是哪一层（配置?容量?调度?）
  → 改 gateway 配置层自动修正 → 下一轮对话验证。这就是项目的 e2e 优化闭环。

### 待确认（保留）
- LoRA 自动路由是否对**所有**进来的请求生效（不限于 screwshell 自有 skill 体系）——决定
  方向 1 的"部署配置层"是否要接管 MoL 路由，还是交给前端/screwshell orchestrator。

### 5.4 脚本文件状态（2026-08-03 注）

- 本文与 `docs/SSH_AND_STARTUP_NOTES.md` 引用的 `start_llama.sh`（base-only + `--jinja` 调试版）是**实例侧脚本**（`/workspace/persistent/screwshell_run/start_llama.sh`），**本 Git 仓库根目录未纳入此文件**（本地仓库仅有 `_run_roomy_server.sh` 与 `_run_ui.sh`）。若需本地复现，按 §5.5 的参数手拼或从实例同步，勿假定本机 `git pull` 后有 `start_llama.sh`。

## 5. 已沉淀/已修正文档

- 实例：`/workspace/persistent/screwshell_run/SSH_AND_STARTUP_NOTES.md`
- 本机（已提交并 push 失败，本地 commit 就绪）：`docs/SSH_AND_STARTUP_NOTES.md`
  - 修正：llama.cpp 路径 `.new` → `/opt/llama.cpp`；llama-server 跑 `:8080` 绑 127.0.0.1；
    gradio 丢失项标记 `[x] 已修复`。
  - 注：本机 `git push` 因 https 无 credential helper 失败，需用户手动 push。

## 5.5 已完成的实例侧修复（2026-08-03）

无需重 build / 无需额外 template 文件——根因是启动开关缺失，已直接修脚本：

- **`_run_roomy_server.sh`**（实例）：路径 `.new`→`/opt/llama.cpp`、**加 `--jinja`**，
  保留 `--lora btl3,cybersec,rag_n7 --alias m --ctx-size 8192 --n-gpu-layers 999 --threads 24`
  原意图。原文件备份 `_run_roomy_server.sh.bak`。
- **`start_llama.sh`**（实例）：同样修路径 + 加 `--jinja`（base-only，无 LoRA，用于调试）。
  原文件备份 `start_llama.sh.bak`。
- **`SSH_AND_STARTUP_NOTES.md`**（实例）：路径引用 `.new`→`/opt/llama.cpp` 已修正。
- **已重启**（2026-08-03，用户授权）：kill 裸 base PID 1223，用 `start_llama.sh`（base+jinja）
  重启，新 PID 2536 在跑（含 `--jinja --ctx-size 8192 --n-gpu-layers 999 --threads 24`）。
  §3 C/D 实测已通过（见 §3 C/D 勾选项）。
- **ctx-size 调整**（2026-08-03）：8K 对 agentic tool 循环太小 → 先提到 32K → 用户实测
  opencode 仍上下文不足，**最终拉到 128K（131072）**。两脚本 `--ctx-size` 均为 131072。
  模型训练上下文 262144；128K 在 W7900 48GB 实测能加载、不 OOM（KV cache 全 GPU 但仍装得下，
  因 base Q4 ~16.8GB + 128K KV 余量够）。tools 在 128K 下无回归。
  - ⚠️ **启动必须用 `setsid` 脱离 SSH 会话**：之前用 `nohup ... &` 后台起，SSH 会话结束被平台
    回收整条命令导致 server 静默退出（日志见 `cleaning up before exit`）。正确姿势：
    `setsid bash -c "nohup <llama-server cmd> > llama_server.log 2>&1 &"`。

### 验证命令（已执行，留作回归）

```bash
# 1) /v1/models 的 capabilities 字段本版本恒为 ["completion"]，不可信，跳过
# 2) 直接发 tools 请求看是否回 tool_calls（标准判定方式）
curl -s http://127.0.0.1:8080/v1/chat/completions -d '{
  "model":"...gguf","tools":[{"type":"function","function":{"name":"get_weather",
  "description":"get weather","parameters":{"type":"object","properties":{"location":{"type":"string"}},"required":["location"]}}}],
  "messages":[{"role":"user","content":"weather in Paris?"}]}'
# 实测结果（2026-08-03）：finish_reason:"tool_calls"，tool_calls 非空 ✓
```

## 8. 关键认知修正（避免下一个 agent 踩坑）

- **`/v1/models` 的 `capabilities` 字段本版本恒为 `["completion"]`，不反映 tools 真实支持**。
  之前把这个字段当"tool 支持缺失"的证据是**误判**——真正开关是启动 `--jinja`。判断 tool 是否
  生效请直接发 tools 请求看是否回 `tool_calls`，别再看 capabilities 字段。
- **根因一句话**：llama.cpp + Qwen3.6 GGUF 本就支持 OpenAI tools 协议，只需启动加 `--jinja`
  （GGUF 自带 tool-use 模板，无需额外 template 文件、无需重 build）。原 PID 1223 裸 base 漏了
  `--jinja` 且没按脚本挂 LoRA/ctx/gpu-layers，导致 opencode/pi 拿不到工具能力。
- **§4 方案分叉可收敛**：既然原生 llama-server + `--jinja` 已能让前端零改造获得 tools，
  **方案 Y（gateway 兼做 tool 编排）的"前端拿不到工具"前提已不成立**；X（纯转发网关）在此
  基础上是可行基线。Y 的价值转为"grammar/json_schema 强制约束脆弱格式 + 复用现有 Toolkit
  Router 做 MoL 路由"，而非"补前端工具能力缺口"。待用户拍板。

## 6. 坑位速查

- llama.cpp 真实路径 `/opt/llama.cpp`（非 `.new`）。
- llama-server 端口 `--port`，非 `-p`；当前实际跑 `:8080`，ctx **131072（128K）**，带 `--jinja`。
- **后台启动必须用 `setsid`** 脱离 SSH 会话，否则会话结束 server 被平台静默回收：
  `setsid bash -c "nohup /opt/llama.cpp/build/bin/llama-server --model ... --jinja --ctx-size 131072 --n-gpu-layers 999 --threads 24 --reasoning-budget 4096 > llama_server.log 2>&1 &"`
  （旧笔记"勿用 setsid"是错的——裸 `nohup ... &` 才会被回收，见 §5.5。）
- ⚠️ **必须加 `--reasoning-budget N`（如 4096），绝不能用默认 -1（无限）**：Qwen3.6 默认
  `thinking=1`，opencode 发请求时不关 thinking 会导致 reasoning budget 无限（日志
  `reasoning-budget: activated, budget=2147483647`），一个 "hi" 都卡 130s+ 疯狂 prefill 26K
  token 不输出。加 `--reasoning-budget 4096` 后 "hi" 5s 正常返回。若要彻底关思考用
  `--reasoning off`（agentic JSON tool-call 场景 README 也建议关 thinking 换快 ack）。
- **重启前先 `pkill -9 -f "llama-server.*8080"` 并确认端口释放**（sleep 4 + 检查 `ss -ltn|grep
  8080`），否则新进程 `couldnt bind port 8080` 直接退出、旧进程还在跑旧配置。
- `llama-cli` 加载 27B 会真推理，别拿它查 metadata（卡死）；改用 gguf 元数据读取。
- 实例 SSH 隧道已在本机后台起（转 7860+8080），别重复起以免端口冲突。
- `/v1/models` 的 `capabilities` 字段恒为 `["completion"]`，**不反映 tools 真实支持**，别被误导。
