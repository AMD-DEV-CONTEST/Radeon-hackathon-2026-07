# 现状交接 — ScrewShell × llama-swap 网关 POC

交接时间: 2026-08-03
交接人: opencode (本会话)
接收人: 执行后续计划（Phase 5 调优 / 薄适配层 / managed-model 切换）的 agent
远端: root@36.150.116.206 -p 31010 (Ubuntu 24.04, AMD W7900 48GB, ROCm)
目标: 验证 llama-swap 能否覆盖 ScrewShell 基础网关与运行管理需求（不立即自研 FastAPI 网关）

---

## 0. 结论（已定）
**选 A：保留 llama-swap 作网关/进程管理/alias/日志/metrics/健康检查入口；ScrewShell 补一层薄适配层。**
未触发 B（薄 FastAPI 重写 messages）、C（自研完整网关）、D（LiteLLM）。
理由与验收见 `evidence/POC_REPORT_FINAL.md`。

---

## 1. 当前运行态（实测，2026-08-03）

| 组件 | PID | 监听 | 状态 | 备注 |
|------|-----|------|------|------|
| llama-server (产线) | 3687 | 127.0.0.1:8080 | healthy | 未重启；参数含 --jinja --ctx-size 131072 --n-gpu-layers 999 --threads 24 --reasoning-budget 4096 |
| llama-swap 网关 | 5198 | 127.0.0.1:18080 | OK | peers 代理模式，配置 `/opt/llama-swap/poc/ls_phase2.yaml` |
| ScrewShell UI | 5563 | 0.0.0.0:7860 | 200 | 已切到网关，env `MOL_LLAMACPP_URL=http://127.0.0.1:18080` + API key 注入 + model 映射（见 §3 验收） |
| llama-cli | — | — | 已停 | 原 PID 2115 已 kill（释放 ~15GB VRAM） |

- VRAM Used: **26.71 GB / 51.52 GB (~52%)**（杀了 llama-cli 后从 81% 降到 52%）
- 启动命令（若需重启）：
  - 网关: `setsid /opt/llama-swap/poc/start_phase2.sh >/opt/llama-swap/poc/ls_phase2.log 2>&1 < /dev/null &`
    （start_phase2.sh = pkill 旧 llama-swap 后 exec llama-swap --listen 127.0.0.1:18080）
  - UI: `/workspace/persistent/screwshell_run/run_ui_gw.sh`（在 `_run_ui.sh` 基础上导出 `MOL_LLAMACPP_URL=:18080` + `MOL_LLAMACPP_API_KEY=screwshell-poc` + `MOL_LLAMACPP_MODEL='roomy//.../Qwen3.6-27B-Q4_K_M.gguf'`；本地模板 `deploy/w7900/run_ui_gw.sh` 已同步）
  - 产线 llama-server: 原 `_run_roomy_server.sh` / `start_llama.sh` 参数，PID 3687 当前在跑

---

## 2. 已落地配置（关键事实，执行计划前必读）

### 2.1 llama-swap
- 版本: **v246 (commit 22df230)**, 二进制 `/opt/llama-swap/llama-swap`，built at `2026-08-03T03:29:56Z`
- 文件大小: **23189302 bytes (~22.1 MiB)**
- 下载 SHA256 (2026-08-03 复算, P0.3 已闭环): `a80a8aad409651197564d71ea14c5b11ecc3e075753f4612b9f3ba54f14f9416`
  - 注: 原交接记录的 `92EA5C37...3352` 与现场不符，已作废；本值为 `sha256sum /opt/llama-swap/llama-swap` 实测。
  - 远端无 GitHub egress，二进制由本机拉取后 SCP 部署；正式化时应在稳定路径下重算并记录下载源 URL + 大小 + SHA256。
- 配置模式: **`peers`**（非侵入，不接管 :8080 生命周期）
- 监听: **127.0.0.1:18080**（未监听 0.0.0.0，符合约束 3）
- API key: **`screwshell-poc`**（无 key 返 401）
- peer 名: `roomy`，proxy `http://127.0.0.1:8080`
- 经网关的模型 id 格式: **`roomy//workspace/persistent/screwshell_run/models/Qwen3.6-27B-Q4_K_M.gguf`**
- 所有证据: `/workspace/persistent/screwshell_run/evidence/*.md`

### 2.2 前端切换状态
- 远端 UI: 已切到网关（env 已设，且 P0 修复后 UI 真实对话/流式/tool-call 已实测经网关成功，见 §3.2；修复前仅探针打到网关、真实请求因缺 key/model 返 401/404）
- 本地 opencode: `C:\Users\dd\.config\opencode\opencode.json` 的 `provider.llama-local` 已翻：
  - baseURL → `http://127.0.0.1:18080/v1`
  - apiKey → `screwshell-poc`
  - model id → `roomy//workspace/persistent/screwshell_run/models/Qwen3.6-27B-Q4_K_M.gguf`
  - 已 git 提交（pre-edit + edit 两次，符合 AGENTS.md 硬规则）
- 本地隧道: `ssh -N -L 18080:127.0.0.1:18080 -p 31010 root@36.150.116.206`（本机后台跑，**断开后 opencode 连不上网关**，需重开）
- `pi`: **明确移出本阶段范围 (P0.5 已决议)** — 本机未找到独立 `pi` 配置指向 :8080，且当前无 pi 调用证据；本 POC 阶段不把 pi 纳入网关验收，后续若接入 pi 再单独补 base_url=:18080/v1 + key + `roomy/` 前缀并实测。

---

## 3. 已验证能力（Phase 1-3 全过 + P0 修复闭环）

### 3.1 网关通道（curl / opencode 路径）
非流式/SSE 对话、tool_calls 透传、reasoning_content 透传、`[DONE]` 保留、上游 502 降级、客户端中断后服务不挂、API key 401、逐请求 /logs、真实 ROCm VRAM/temp/util（/metrics，解决 ScrewShell hardware.py 正则缺口）、131072 ctx 保住、tool-call→tool-result 第二轮、双会话日志隔离。

### 3.2 ScrewShell UI 真实请求经网关（P0 修复后实测，2026-08-03 复测）
- **修复**: `MoLLlamaCpp` 从 env 读 `MOL_LLAMACPP_API_KEY` / `MOL_LLAMACPP_MODEL`，所有 chat/probe 请求统一注入 `Authorization` 与网关 model id；直连 llama-server 场景（无 key, model=m）行为不变。(commit `cf4cb9a`)
- **验收**（engine.chat 直连网关 :18080 → 真实 llama-server :8080）:
  - 普通对话: `ok=True content='QA-OK'` ✅
  - 流式对话: `ok=True content='Hello! How can I help you today?'` ✅
  - tool-call: `finish_reason=tool_calls`，`tool_calls=[{get_weather,{"city":"Beijing"}}]` 透传无损 ✅
- 注: 早期空文本是因 `--reasoning-budget 4096` 把小 `max_tokens` 全耗在 thinking 上，与网关/代码无关；放大 `max_tokens` 后 content 正常返回。
- 本地代码已 `git commit cf4cb9a`；远端 `/workspace/persistent/screwshell_run/screwshell` 已同步（备份 `screwshell.bak.`），`run_ui_gw.sh` 已部署。

### 3.3 仍属条件能力（不要写成"已完成"）
- SSE 断开后网关健康 ≠ 上游推理已取消
- `/slots` 显示 131072 ≠ 真实 131K token 端到端负载通过
- 某次 tool-call 成功 ≠ 测试可稳定重放
- API key `screwshell-poc` 已写入交接与配置，正式使用前需轮换并移到密钥配置

---

## 4. 已知 GAP（非阻断，属 Phase 5 范畴，不要急着自研代码）
- [G1] peers 模式下**并发限制/429 不生效**（concurrencyLimit 仅 managed-model 模式生效）
- [G2] peers 模式模型 id 是完整 GGUF 路径（丑），无 alias（alias 仅 managed-model 模式生效）
- [G3] /lora-adapters 经网关返 404（peers 不暴露该 managed 端点）；UI 引擎已优雅处理；LoRA 状态需直查 :8080 或 /upstream

→ G1/G2 的解法：让 llama-swap **管理** llama-server 生命周期（managed-model 模式，停 :8080 → 内部端口如 18081 启动），属 restart-required 变更，需维护窗口 + 人工批准。

---

## 5. 硬约束（来自原任务，后续执行仍受约束）
1. 第一阶段禁止改 ScrewShell 产品代码（薄适配层是新增，不改既有逻辑）
2. 不得未经确认杀/重启产线 llama-server（PID 3687）
3. 网关不得监听 0.0.0.0（保持 127.0.0.1）
4. 保留 131072 ctx 基线，不得自动降到 8192
5. 网关不得接管 opencode/pi 的 agent/tool loop
6. 实验记录命令/版本/SHA/端口/结果/回滚
7. 需重启远端 → 先给维护窗口+风险，等确认

---

## 6. 后续计划入口（Phase 5，网关稳定后再做）
- doctor/hardware/planner/tuner 生成候选启动配置（managed 模式内部端口 18081）
- 配置 diff / preflight / 人工批准 / 重启 / 探活 / 失败回滚
- fast/think 模型 alias 或显式 header（managed 模式 setParamsByID）
- 不按 prompt 猜 agentic；不自动覆盖固定 --reasoning-budget
- 外部 LoRA/MoL 路由必须显式 alias/header；**当前无 LoRA，不宣称路由命中**
- restart-required 参数（ctx/jinja/metrics/lora/gpu-layers/threads/KV）视为重启变更
- 需多供应商/鉴权/预算/fallback 才评估 LiteLLM（不同时堆 llama-swap+LiteLLM）

---

## 7. 回滚命令（如需回退到切 Before 状态）
```
# 停网关（不影响 :8080/:7860）
pkill -9 -f "/opt/llama-swap/llama-swap"
# UI 回退直连 :8080
pkill -9 -f "screwshell.ui.app"; setsid bash -c "nohup /workspace/persistent/screwshell_run/_run_ui.sh >/workspace/persistent/screwshell_run/ui.log 2>&1 < /dev/null >/dev/null 2>&1 &"
# 本地 opencode 回退：把 llama-local 的 baseURL 改回 :8080/v1、apiKey 改回 sk-noauth、model id 去掉 roomy/ 前缀（已 git 跟踪，可 git revert e8b6f60）
# 关本地隧道：杀掉本机 ssh -L 18080 进程
```

---

## 8. 给执行 agent 的注意事项
- 读 `evidence/POC_REPORT_FINAL.md` 看完整验收与结论。
- 远端**无 GitHub egress**（curl github → 000）；要装/升级二进制需本机拉取后 SCP。
- 远端 `ss -ltnp` 无输出（host 工具 quirks），用 curl 探活代替。
- 本地 PowerShell 里 `curl` 是 Invoke-WebRequest 别名，真实 curl 是 `curl.exe`；变量含 `/` 时 POST 用 `--data-binary @file` 避免引号问题。
- 当前 llama-swap 是 POC 配置（在 `/opt/llama-swap/poc/`），正式化时应移到稳定路径并纳入版本管理。
- 薄适配层（request_id/run_id、RunMetrics 映射、UI 指标面板、MoL/LoRA 状态、config_revision/审计）**核心已在 `MoLLlamaCpp` 内实现**（commit `0406128`，见 §9）；UI 渲染面板为独立前端任务，不在网关适配层范围。

---

## 9. P0 修复与交接评审结论（2026-08-03 评审 gate）

评审结论: **POC PASS；产品级网关交接 FAIL/INCONCLUSIVE**（UI 真实请求契约 + 部署身份未闭环）。本会话已闭环 P0.1（UI API key + model 映射），其余 P0 项状态:

| 项 | 状态 | 说明 |
|----|------|------|
| P0.1 UI API key 注入 + model 映射 | **DONE** | commit `cf4cb9a`；§3.2 真实验收通过 |
| P0.2 真实 UI 对话/流式/tool-call 验收 | **DONE** | §3.2 |
| P0.3 部署二进制 SHA 不一致 | **DONE** | §2.1 已复算固定: SHA256=a80a8aad...f14f9416, 23189302 bytes, v246(22df230) |
| P0.5 pi 验证 | **DONE(移出)** | §2.2 pi 明确移出本阶段范围；不纳入网关验收 |

### 9.1 P1 薄适配层（DONE, commit `0406128`，远端已同步验收）
评审 P1 要求"只做适配，不重写 messages/tools/SSE/reasoning"。落点选在 `MoLLlamaCpp`（ScrewShell 推理入口），未新起 HTTP 服务（避免退化成自研网关）:
- **API key 注入** ✅（P0 已有，复用 `_auth_headers`）
- **稳定 model alias 映射** ✅（`MOL_LLAMACPP_MODEL`，P0 已有）
- **request/run ID** ✅ 每请求生成 `X-Request-Id`、透传 `X-Run-Id`；已验证该 id 到达网关 `/logs`，端到端可关联
- **请求级指标** ✅ `request_audit` 内存审计（request_id/run_id/model/gateway_mode/latency/status/config_revision），GenStats 带 request_id/run_id
- **UI 面板数据** ✅ `adapter_status()` 暴露 gateway_mode / model_alias_resolved / config_revision / LoRA 状态 / 降级标记
- **LoRA/MoL 状态和降级标记** ✅ `adapter_status()["lora_degraded"]` 等结构化字段
- **config revision 和审计** ✅ `config_revision` 常量（env 可覆盖）+ 每请求写入审计
- **未做**（评审列为 P2 或独立前端）: RunMetrics 映射聚合、外部前端 UI 面板渲染、会话关联展示、alias/429/生命周期（managed 模式）

真实验收（engine.chat 直连网关 :18080 → :8080 真实 server）: request_id 生成、run_id 串联、adapter_status 返回、网关日志命中 request_id 均通过。

 下一步优先级: P0 + P1 闭环；P2 managed 模式评估（需维护窗口，restart-required 变更）。

### 9.2 P2 managed 模式评估（2026-08-03 维护窗口执行，结论: 不采用，回滚 peers）
按授权进入维护窗口执行 cutover（concurrencyLimit=1，UI model 切 `screwshell-qwen3.6-27b`）。结果:

- **生命周期接管** ✅ llama-swap 在内部 18081 自起 llama-server，health check 通过
- **干净 alias (G2)** ✅ `/v1/models` 返回 `screwshell-qwen3.6-27b` + aliases `[m, qwen3.6-27b]`，type=model
- **concurrencyLimit (G1)** ✅ 配置生效（=1，单 GPU 串行）
- **非流式 chat** ✅ 经网关返回真实内容
- **tool-call** ✅ `finish_reason=tool_calls` 透传正常
- **流式 chat** ❌ **阻断性回归**: 经 managed 网关的 SSE 流上游断开（`recovered from upstream disconnection during streaming`，空 body）；而直连内部 18081 流式完全正常（201 chunks）。即 llama-swap v246 **managed 模式的 SSE 代理损坏**，peers 模式流式正常。

决策: 因流式是 UI 核心路径，managed 引入回归且非配置可解（llama-swap 缺陷），**回滚到 peers 模式**。生产现状: peers llama-swap(10475) + 外部 llama-server(:8080, 单实例, 131072 ctx)。UI model 保持 peer id（run_ui_gw.sh 已回退）。

待办（如需再试 managed）:
- 升级 llama-swap 或排查其 managed SSE 代理（非本仓库范围）
- 或保留 peers + 用网关 alias 映射层解决 G2（薄适配层已能做 model alias，不需 managed）
- 再次 cutover 前必须先在隔离端口验证 managed 流式

P2 总结: **评估完成，不落地**。G1/G2 的"网关内解决"目标未达成，但薄适配层(P1)已可在 peers 模式下提供 model alias，等效缓解 G2。

