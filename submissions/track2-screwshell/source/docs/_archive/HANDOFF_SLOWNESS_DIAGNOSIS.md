# HANDOFF — screwshell 后端"反应慢 / 像卡死"诊断

> 自包含交接文档。给 DeepSeek / HY3 / 后续 Agent 接手用。
> **状态：只读诊断，未改代码、未重启、未动 loras。** 修复待拍板（见 §6）。

---

## §0 背景

### 实例与部署
- 实例：`root@36.150.116.206 -p 31010`（AMD W7900 / Ubuntu 24.04，128 核 503G）。SSH 公钥已重新加回，当前**可达**。
- 工作目录：`/workspace/persistent/screwshell_run`
- 本地看走 SSH 隧道：`-L 7860:127.0.0.1:7860 -L 18090:127.0.0.1:18090 -p 31010`
- 三进程（ps 实测）：
  - llama-server (PID 41991)：`--model .../Qwen3.6-27B-Q4_K_M.gguf --lora btl3,cybersec,rag_n7 --host 127.0.0.1 --port 8080 --ctx-size 131072 --n-gpu-layers 999 --threads 24 --reasoning-budget 4096`
  - relay (PID 42125)：`python -m screwshell.gateway.relay`
  - ui (PID 45687)：`python -m screwshell.ui.app --workspace .../demo_workspace --base .../Qwen3.6-27B-Q4_K_M.gguf --port 7860 --no-rag`
- 端口均绑 `127.0.0.1`（不在公网），故从本机 `curl 36.150.116.206:8080` 必然不通——**这不是故障**，必须 SSH 进实例或走隧道才能探。

### 请求链路
```
浏览器(你) ──SSH隧道──> UI :7860 (Gradio)
                         └─ orchestrator.run() ─> mol_engine (relay_mode)
                              └─ POST /v1/chat/completions + X-Expert + X-Relay-Token
                                 └─ relay :18090 (InferenceCoordinator: 全局锁 + 串行切 LoRA)
                                    └─ llama-server :8080
```
关键点：relay 持有全局 LoRA 切换权（`POST /lora-adapters`），UI 不直接切。

---

## §1 用户问题陈述
- 原话："后端实例运行的模型好像又卡死了。"
- 复核后实为：**模型不卡死，但反应慢，且 UI 在等待期间没有任何"运行中"提示，看起来像卡死。**
- 另一个 Agent 并行发现：autotune 模块（L1/L2/L3）与 UI 完全脱节（已核实，见 §5）。

---

## §2 真机调查结论（live 证据）
所有结论均在实例上实测，非推测。

### 2.1 实例健康，模型快
- `rocm-smi --showuse` → GPU[0] busy **93%**（正常推理负载，非死循环）。
- 直连 8080 小生成（max_tokens=8）：`http=200 time=2.187s`。
- 直连 8080 真实问答（不限 max）：`http=200 time=1.008s`，content 30 字。
- `/slots`：4 个 slot 全部 `is_processing=False` → **无卡死 / 无死锁请求**。

### 2.2 "慢"的来源 = 间歇性延迟尖峰
| 请求路径 | 条件 | 实测耗时 |
|---|---|---|
| 直连 8080 | max_tokens=8 | 2.19s |
| relay + 带 token + X-Expert | 信任路径 | **0.47s** |
| relay + 无 token（被 SkillRouter 重路由 → base） | 偶发触发切专家 + 推理 | **12.17s**（另一次 0.43s，取决于当时是否需切专家）|
| relay + 真实问答 | 简单 prompt | 1.01s |

→ 延迟尖峰与"是否触发全局 LoRA 切换 + 是否跑长推理"强相关，**不是恒定慢**。

### 2.3 token 校验：UI 行为正常（重要纠正）
- relay 进程 env：`RELAY_TRUST_TOKEN=screwshell-relay-devtoken`
- UI 进程 env：`RELAY_TRUST_TOKEN=screwshell-relay-devtoken`  ← **两进程一致**
- 引擎确实带认证头：`mol_engine_llamacpp.py:642-644`
  ```python
  _tok = os.getenv("RELAY_TRUST_TOKEN", "")
  if _tok:
      req_headers["X-Relay-Token"] = _tok
  ```
  且 `mol_engine_llamacpp.py:637` 带 `req_headers["X-Expert"] = self.active_adapter`。
- token 默认来源：`gateway/cli.py:37` `os.getenv("RELAY_TRUST_TOKEN", "screwshell-relay-devtoken")` —— cli 默认注入；启动脚本 `_run_ui_gw.sh` 等虽未 export，但 cli 默认值补上了，所以两进程都有。
- relay.log 里的 `X-Expert ignored: missing/invalid X-Relay-Token` 警告，**来自缺 token 的请求**（本 Agent 手动 curl、以及外部调用 opencode/pi），**不是 UI 发的**。

### 2.4 "像卡死" = 反馈真空
- UI 主气泡仅在流式文本到达后更新：`ui/app.py:271` `f"{phase}\n\n⏱ {elapsed}s · generating…"` —— 该计时**只在流式期**。
- 提交时 `ui/app.py:475` 设 `phase="thinking"`，但**切专家 / 连模型的首 token 前真空期没有任何"切换中 / 连接中"提示**。
- 已有 `lora_switch` 事件（`orchestrator.py:270` 发出，`ui/app.py:419` 接收），但只进右栏"LoRA 轨迹"列表，**未映射为主状态**。

---

## §3 已排除的误判
- ❌ "UI 没发 token → 每条请求被重路由 → 每轮切专家所以慢"：**推翻**。引擎确实发 token，两进程 token 一致，ignored 警告来自外部调用。
- ❌ "实例挂了 / SSH 不通"：本机 `/dev/tcp` 探测误报 CLOSED（沙箱里 `/dev/tcp` 不可靠），真实 SSH 31010 可登。**务必用真实 SSH 探，别信 `/dev/tcp`**。
- ❌ "端口 22/8080 公网不通 = 故障"：这些端口本就不该从公网通（8080 绑 127.0.0.1），属设计。

---

## §4 根因（架构级，非 bug）
1. **每步切 LoRA（主因）**：`orchestrator.py:5` "每一步 SkillRouter 选专家 → mount → ReAct"；`:268`/`:587` 每步 `route()` 决策并切全局 LoRA（串行锁 + KV 失效重建，每次数秒）。一次提问 = 多步 = 多次切换 + 多次生成。
   - 幂等声明在 `:233`（同专家不重切），且有 `:279` "Reorder steps to minimize expert swaps" 优化——但实测仍有切换尖峰，**值得复核该优化是否真生效**。
   - 切换模式：roomy（热切换 scale toggle，应 ~0.65ms）vs tight（重启 llama-server，4–5s/次，`orchestrator.py:20`）。部署用预载 `--lora` 应走 roomy，但尖峰提示可能走了重路径，**需核实**。
2. **reasoning-budget 4096（次因）**：启动参数让模型先跑一段隐藏"思考"再出可见文本，期间 UI 气泡静止。
3. **反馈真空（体验主因）**：见 §2.4。

---

## §5 另一个 Agent 的发现（已核实属实）
- `screwshell/autotune/` 模块**完整存在**：`hardware.py / skillpack.py / planner.py / doctor.py / governor.py / tuner.py / __init__.py / __main__.py`（注：该 Agent 提到的 `capacity.py` 在本仓 Glob 未命中，可能改名或并入他处，接手时确认）。
- `screwshell/ui/app.py` grep `autotune` → **零命中**：UI 完全没 import autotune。
- 脱节内容：L1 技能包扫描结果、L2 四维评分（显存/速度/质量/覆盖）+ 降级阶梯、L3 Governor 治理动作（上下文档位、关思考、KV 量化触发）均未在 UI 右栏呈现。
- 这是**独立功能缺口**，不是本次"慢"的原因。

---

## §6 修复清单（未执行，等拍板）
**P0 — 直接解决"慢 + 像卡死"**
- **P0-1 UI 运行态指示（止血"像卡死"）**：`ui/app.py` 提交即进入"正在切换专家 / 连接中"相位；把 `lora_switch` 事件（`:419`）映射进主状态区，覆盖首 token 前真空期。
- **P0-2 砍延迟**：部署脚本把 `--reasoning-budget 4096` 调小 / 按需关闭；核实 llama-server 实际走 roomy 热切换还是 tight 重启切换（决定单次切换是 0.65ms 还是 4–5s）。
- **P0-3 复核每步路由幂等**：`orchestrator.py:233/279` 的"同专家不重切 / 重排减切"是否真生效（加一个 switch 计数日志即可验证）。

**P1 — 功能缺口（另一个 Agent 的发现）**
- **P1-1** 把 `autotune` 的 L1/L2/L3 观测接入 `ui/app.py` 右栏（需先确认 autotune 的运行时输出如何暴露——可能要走 relay observ 或新端点）。

---

## §7 给外部 AI 的切入点
- 从 **relay / InferenceCoordinator** 入手最值：它是全局 LoRA 切换与串行队列的唯一 owner（`screwshell/gateway/relay.py`、`screwshell/core/inference_coordinator.py`）。切换耗时、是否走 roomy 热切换，在这里一目了然。
- 延迟真因验证最小成本做法：在 relay 里给每次请求记 `switch_ms`（切换耗时）和 `queue_ms`（排队耗时），落 `requests.db`，直接分清"慢在切专家"还是"慢在生成"。
- UI 真空期修复是纯前端，改 `ui/app.py` 即可，不影响后端。

---

## §8 文件 / 命令速查
- 实例 SSH：`ssh -p 31010 root@36.150.116.206`
- 本地探端口（必须走实例内或隧道，勿用公网）：`ssh -p 31010 root@36.150.116.206 "curl -s -m 8 http://127.0.0.1:8080/health"`
- 直连测速：`curl -s -m 30 -X POST http://127.0.0.1:8080/v1/chat/completions -d '{"model":"screwshell-base","messages":[{"role":"user","content":"ping"}],"max_tokens":8}'`
- relay 测速（带 token）：同上但 `-H "X-Relay-Token: screwshell-relay-devtoken" -H "X-Expert: <专家>"`
- 看进程 / 端口：`ps aux | grep -E "llama|relay|ui.app"`；`ss -ltnp | grep -E ":8080|:7860|:18090"`
- 关键源码：`screwshell/core/mol_engine_llamacpp.py`(642-644,637)、`screwshell/core/orchestrator.py`(5,233,268,279,587)、`screwshell/ui/app.py`(271,419,475)、`screwshell/gateway/relay.py`(52)、`screwshell/gateway/cli.py`(37)
- 日志：`/workspace/persistent/screwshell_run/{relay.log,ui.log,llama_server.log}`

---
决策状态：本次**只读诊断，未改代码、未重启、未动 loras**。修复待用户拍板（P0/P1 见 §6）。
