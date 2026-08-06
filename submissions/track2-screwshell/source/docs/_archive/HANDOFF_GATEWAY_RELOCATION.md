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

## 1. 产品重定位决策（已与用户确认）

ScrewShell 从"自带 ReAct agent + Gradio UI"**重定位为**：
**llama.cpp 前面的「网关 + 可观测 + e2e 性能优化器」**，agent 智能交给成熟前端
（opencode / pi）。硬性要求：**必须兼容原生 OpenAI `tools` 协议，让 opencode/pi 零改造接入。**

- 自带的脆弱文本格式 ReAct orchestrator（screwshell/core/orchestrator.py）**不再是重点**，
  但 Toolkit（screwshell/tools/toolkit.py 的 6 个工具 + 权限门禁）和 metrics /
  autotune / router 的 LoRA 热切逻辑**可复用**。
- 方案待定（见 §4 的 X/Y 分叉），需下一个 agent 在调查 §3 结论后拍板。

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

- [ ] **A. 确认构建是否支持 tools**：
  - 查 `/opt/llama.cpp` 构建时是否带 tool/function-calling（看 build 目录、CMake cache，
    或该 commit 035cd8f9a 是否较老——官方 llama.cpp 的 `/v1/chat/completions` tools 支持
    是较后期才稳的）。考虑 `git -C /opt/llama.cpp log -1` 看日期。
  - 升级到较新官方 llama.cpp 重 build（ROCm/HIP），确认 `/v1/models` 出现 `tools` capability。
- [ ] **B. 确认 Qwen3.6 GGUF 的 chat template**：
  - 不要跑 `llama-cli`（27B 会真推理卡死）。改用 `llama-gguf` / `python -c` 读 gguf 元数据，
    或直接查该模型来源是否带 jinja chat_template。
  - 若 template 缺失，server 无法生成 function-calling 所需的 tool 注入格式——这是官方
    llama.cpp 跑 qwen tool 能成、本实例不成的常见差异点。
- [ ] **C. 对齐启动参数**：用 `_run_roomy_server.sh` 的真正意图重启 llama-server
  （挂 LoRA / ctx-size / gpu-layers），并补 tool 相关启动开关（如需要）。重启后用
  `curl` 重测 §3.2 的 tools 请求，看是否产出 `tool_calls`。
- [ ] **D. 用本机 opencode 实测**（隧道已通）：把 opencode 模型 base_url 指向
  `http://127.0.0.1:8080/v1`，model = gguf 路径，实际发一个需要 tool 的任务，验证
  opencode 的 tool/MCP 调用是否恢复。这是对"官方能成、本实例不成"假设的最终验证。
- [ ] **E. 竞品对照**：确认官方 llama.cpp + Qwen3.6 在 opencode 里 tool 正常的先决条件
  （构建版本 / 启动参数 / template），列出本实例与之的差异清单。

## 4. 网关方案分叉（调查出结论后再定）

- **方案 X（纯转发网关）**：gateway 只转发 `/v1` + 按请求自动挂 LoRA + 全链路埋点 +
  出 e2e 报表。前端 tool 调用由前端自己完成。但 §3 表明裸 llama-server 不回 tool_calls，
  所以此方案下前端工具能力仍可能残。
- **方案 Y（gateway 兼做 tool 编排）**：gateway 实现完整 OpenAI `tools` 兼容，前端零改造
  拿到工具能力；tool 循环复用现有 Toolkit + Router，把脆弱文本格式升级为 grammar /
  json_schema 强制约束（mol_engine_llamacpp.chat 已支持 `grammar` / `json_schema` 参数，
  可复用）。
- 倾向：Y 才能真正让 "opencode/pi + 本地模型" 获得现代 agent 体验；X 只是更透明的聊天后端。
- 待确认：LoRA 自动路由是否对**所有**进来的请求生效（不限于 screwshell 自有 skill 体系）。

## 5. 已沉淀/已修正文档

- 实例：`/workspace/persistent/screwshell_run/SSH_AND_STARTUP_NOTES.md`
- 本机（已提交并 push 失败，本地 commit 就绪）：`docs/SSH_AND_STARTUP_NOTES.md`
  - 修正：llama.cpp 路径 `.new` → `/opt/llama.cpp`；llama-server 跑 `:8080` 绑 127.0.0.1；
    gradio 丢失项标记 `[x] 已修复`。
  - 注：本机 `git push` 因 https 无 credential helper 失败，需用户手动 push。

## 6. 坑位速查

- llama.cpp 真实路径 `/opt/llama.cpp`（非 `.new`）。
- llama-server 端口 `--port`，非 `-p`；当前实际跑 `:8080`。
- 后台启动用 `nohup bash -c "..." < /dev/null > /dev/null 2>&1 &` 或 `nohup bash _run_ui.sh`；
  勿用 setsid+长 sleep（平台 SSH 回收整条命令）。
- `llama-cli` 加载 27B 会真推理，别拿它查 metadata（卡死）；改用 gguf 元数据读取。
- 实例 SSH 隧道已在本机后台起（转 7860+8080），别重复起以免端口冲突。
