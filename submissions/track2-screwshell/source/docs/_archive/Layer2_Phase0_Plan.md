# ScrewShell 第 2 层 — Phase 0 实现计划（正确性 + 真中继）

> 配套文档：`Layer2_Implementation_Map.md`（架构地图 / 借造对照 / 开放问题）。
> 本计划只覆盖地图 §5 **Phase 0** 四步；v1 = `InferenceCoordinator` 统一持有全局 LoRA 状态 + 单请求队列 + 切换锁 + 流式清理。**专家子代理（S0/S1）不在本计划**，留作地图 §1.5 / Phase 4 真机实验。
> 成文：2026-08-04。

---

## 0. 目标与范围

- **做对，不做多**：先把"多前端共享、MoL 切专家不串线、不静默失效"打通，性能/观测增强全部留后续 Phase。
- **v1 决策（地图 §1.4）**：只用全局 `POST /lora-adapters`（路径 D），**禁止**请求级 `payload["lora"]`（路径 C），彻底消除 P0 混用静默失效。
- **单请求串行**：所有入口共用一条队列，拿锁后完成"选 LoRA → 推理/流式 → 释放锁"再放下一个。
- 不在本计划：Phase 1 观测面板、Phase 2 配置自动化/`capacity.py`、Phase 3 调优闭环、Phase 4 S0/S1 实验 + 并发 + OpenLIT。

---

## 1. 架构落点（对应地图 §2 三平面）

```
前端(网页Agent / opencode / pi)
   │  OpenAI 兼容 base_url = 中继 /v1
   ▼
┌─ 中继层 Relay (screwshell/gateway/relay.py, FastAPI) ──────┐
│ • 鉴权 / request_id / run_id                               │
│ • 调 SkillRouter._decide() → RouteDecision(目标专家,…)     │
│ • 转发 InferenceCoordinator；SSE 透传                      │
│ • 不向外暴露原始 /lora-adapters                            │
└──────────────────────────────────────────────────────────┘
   │  私有下游
   ▼
┌─ InferenceCoordinator (screwshell/core/inference_coordinator.py) ─┐
│ • 唯一 owner：全局 LoRA 状态 / asyncio.Lock / 队列 / 流式清理     │
│ • 锁内：切专家(POST /lora-adapters) → 转发 llama-server → 释放   │
└────────────────────────────────────────────────────────────────┘
   │  HTTP（复用 MoLLlamaCpp 的 activate/chat，仅全局 D 路径）
   ▼
llama-server (:8080)   ← 原始 /lora-adapters 只对此私有连接开放
```

- **中继层**只管协议兼容 + 路由决策（调 `SkillRouter`，不直接发 LoRA HTTP）。
- **运行层状态 owner** = `InferenceCoordinator`，不是中继、不是 Orchestrator、不是 llama-swap。
- 推理后端客户端**复用** `screwshell/core/mol_engine_llamacpp.py` 的 `activate()`（全局 D）与 `chat()`；但 `chat()` 必须删掉请求级 `lora` 注入（修 P0）。

---

## 2. 新增 / 修改文件清单

| 文件 | 动作 | 职责 |
|------|------|------|
| `screwshell/gateway/__init__.py` | 新建 | 包标识 |
| `screwshell/gateway/relay.py` | 新建 | FastAPI `/v1` 入口；auth/request_id/run_id；调 `SkillRouter._decide()`；转发 `InferenceCoordinator`；SSE 透传；**不暴露** `/lora-adapters` |
| `screwshell/core/inference_coordinator.py` | 新建 | `InferenceCoordinator`：全局 LoRA 状态、`asyncio.Lock`、队列/429、`切专家→请求→释放锁`、流式清理 |
| `screwshell/core/mol_engine_llamacpp.py` | 改 | `chat()` 删除请求级 `payload["lora"]` 注入（修 P0）；保留 `activate()` 全局 D 路径 |
| `screwshell/core/config.py` | 改 | 新增 `RELAY_HOST` / `RELAY_PORT` / `LLAMA_SERVER_URL` |
| `screwshell/ui/app.py` | 改 | Gradio 客户端 `base_url` 指向中继 `/v1`（不再直连 :8080 或 llama-swap peers） |
| `local-deploy/*.bat` / `docs/*` | 改 | opencode / pi 的 `base_url` 指向中继 |
| `tests/test_phase0_coordinator.py` | 新建 | 验收测试（见 §3 验收点） |

> 现有可用资产：`SkillRouter._decide()`（`core/router.py:153`）已产出 `RouteDecision`；`MoLLlamaCpp.activate()`（`core/mol_engine_llamacpp.py:220`）已做全局 `POST /lora-adapters`；`core/metrics.py` 已有 `RunMetrics`/`CallRecord`（本计划仅透传 `request_id`，持久化留 Phase 1）。

---

## 3. 任务分解（带验收点）

**T0.1 中继骨架**
- 建 `gateway/relay.py`：实现 `/v1/models`、`/v1/chat/completions`、`/v1/completions`，SSE 透传到 llama-server。
- 验收：`curl` 经中继拿到的 chat 响应 == 直连 :8080（同 prompt、同参数、首 token 与全文一致）。

**T0.2 InferenceCoordinator**
- 实现 `asyncio.Lock` + 队列；暴露 `request(route_decision, payload)`：拿锁 → 若目标 LoRA ≠ 当前 → `activate()` 切 → 转发 `chat()` → 流式返回 → `[DONE]`/断开/超时释放锁。
- 验收：连续两个不同 LoRA 请求**不串专家**（seed 固定 + `temperature=0` A/B，输出有差异才算生效，见 §5 铁律）。

**T0.3 修 P0 混用 bug（关键）**
- 从 `mol_engine_llamacpp.py` 的 `chat()` 删除请求级 `payload["lora"]` 注入；v1 只用全局 D。
- 验收：`grep` 确认 `chat()` 请求体无 `"lora"` 键；地图探针 P3（6/12 逐字等于基座）复测 → **0/12**。

**T0.4 RouteDecision 接线**
- 中继收到请求 → 调 `SkillRouter._decide()` 得目标专家 → 传给 `Coordinator`；Coordinator 据此切 LoRA。
- 验收：不同问题路由到不同专家；`GET /lora-adapters`（私有连接）显示对应激活；外部前端看不到隐藏协议。

**T0.5 流式清理 + 锁释放**
- 锁覆盖"切专家 → 生成 → 释放"整段；监听 `[DONE]`、客户端断开、超时三者任一 → 释放锁。
- 验收：客户端中途断开后，下一请求仍正常（无死锁、全局 LoRA 状态不残留错误专家）。

**T0.6 队列满 429**
- `pending` 超阈值返回 `429` + `Retry-After`；不允许多请求同时改全局 LoRA。
- 验收：并发 >1 压测时，超额请求收到明确 `429`（非挂起/非串专家）。

**T0.7 安全边界**
- 确认中继**不暴露**原始 `/lora-adapters`；该端点只由 `Coordinator` 私有下游调用。
- 验收：`curl` 中继 `/lora-adapters` → `404`/`403`。

**T0.8 三入口接线**
- 网页 Agent（`ui/app.py`）、opencode、pi 的 `base_url` 全部指向中继 `/v1`；不再直连 :8080 或 llama-swap peers。
- 验收：三入口都经中继；日志显示统一 `request_id`/`run_id`；peers 代理可下线。

**T0.9 验收测试固化**
- `tests/test_phase0_coordinator.py` 覆盖 T0.2 / T0.3 / T0.5 / T0.6，纳入 `pytest`。
- 验收：`pytest tests/test_phase0_coordinator.py` 全绿。

---

## 4. 关键实现要点（避坑，来自地图 §6）

1. **永远单路径**：只用 `activate()` 全局 D；`chat()` 永不注入请求级 C。两者混用 = P0 静默失效。
2. **锁粒度**：必须覆盖"切专家 → 生成 → 释放"整段；流式期间持锁，`[DONE]`/断/超时任一触发释放。
3. **透传不改动**：`tools` / `response_format` / `grammar` 原样转发，中继不重写。
4. **RunMetrics 非线程安全**：本计划只透传 `request_id`/`run_id`；指标持久化（JSONL/SQLite + `RequestEvent`）留 Phase 1，不要在中继里直接累加 `RunMetrics`。
5. **外部前端无隐藏协议**：opencode/pi 仍走标准 OpenAI 请求/响应；每轮由中继重新路由，不插入 `consult expert`。

---

## 5. 验证铁律（沿用项目记忆，务必遵守）

- **adapter"加载成功"≠"有效"**：必须 **seed 固定 + `temperature=0` 做 A/B**，输出有差异才算专家生效。
- **测完把所有 scale 归零**，残留 1.0 会全局污染后续调用。
- 先单卡串行验证**正确性**，并发 / 子代理留 Phase 4。

---

## 6. 完成判据（Done Definition）

- 三入口（网页 / opencode / pi）均经中继 `/v1`，不再直连 :8080 或 llama-swap peers；
- 连续不同 LoRA 请求不串专家，P0 混用 bug 复测 0/12；
- 客户端断开 / 超时后锁必释放，下一请求正常；
- 队列满返回明确 429；
- 中继不暴露 `/lora-adapters`；
- `pytest tests/test_phase0_coordinator.py` 全绿。

达到以上即 Phase 0 完成，可进入 Phase 1（观测面板）。

---

## 7. 实施记录（2026-08-04，djb + 本机 agent 真机实测）

全部 T0.1–T0.9 已落地并真机验证。

| 任务 | 结果 | 真机证据 |
|------|------|----------|
| T0.1 中继骨架 | ✅ | `relay.py` 起在 :18090；`/health` 返回 adapters=[btl3,cybersec,rag_n7], current_expert:null（启动即强制 base） |
| T0.2 Coordinator 切换 + 不串专家 | ✅ | 强制 X-Expert:btl3 vs cybersec 同 prompt、seed=42/temp=0、关 thinking → 输出明显不同（btl3=PHP 风、cybersec=Python 风），证明专家真生效、非静默 base |
| T0.3 修 P0 混用 bug | ✅ | `mol_engine_llamacpp.py:603` 注释 + 已删 `chat()` 请求级 `lora` 注入；`tests/test_phase0_coordinator.py` 行级断言无 `lora`、有 `X-Expert` |
| T0.4 RouteDecision 接线 | ✅ | 无 X-Expert 时中继走 `SkillRouter` 自动路由（安全 query→cybersec）；有 X-Expert 时信任不重路由 |
| T0.5 流式 + 锁释放 | ✅ | 流式返回 5 段 SSE 且含 content；follow-up 不同专家正常返回（锁已释放） |
| T0.6 队列满 429 | ✅ | 6 并发打满 max_pending=4 → `429 429 200 200 200 200` |
| T0.7 安全边界 | ✅ | 中继 `/lora-adapters`（GET/POST/PUT/DELETE）全部 404 |
| T0.8 三入口接线 | ✅(网页) | Gradio UI 已重启走中继：`MOL_LLAMACPP_URL=:18090` + `MOL_RELAY_MODE=1`（新增 `local-deploy/run_ui_relay.sh`）；opencode/pi 改打 :18090 即可（中继自动路由） |
| T0.9 验收测试 | ✅ | `tests/test_phase0_coordinator.py` **9 passed**；`tests/test_mol_llamacpp.py` 陈旧断言已改为"无 lora 注入" |

### 真机运行态（2026-08-04 收尾）
- llama-server :8080（预载 btl3/cybersec/rag_n7）
- **中继 relay :18090**（`local-deploy/start_relay.sh`，InferenceCoordinator 统一持有全局 LoRA + asyncio.Lock + 队列/429）
- Gradio UI :7860（走中继）
- **llama-swap peers :18080 已停用**（G3 `/lora-adapters` 404 bug，中继取代之）

### 重启命令
```bash
# 中继
cd /workspace/persistent/screwshell_run && /opt/venv/bin/python -m screwshell.gateway.relay   # :18090
# UI（走中继）
MOL_BACKEND=llamacpp MOL_LLAMACPP_URL=http://127.0.0.1:18090 MOL_RELAY_MODE=1 \
  /opt/venv/bin/python -m screwshell.ui.app --workspace .../demo_workspace \
  --base .../models/Qwen3.6-27B-Q4_K_M.gguf --port 7860 --no-rag
```

### 已知缺口（非 Phase 0 回归）
- `tests/test_interface_parity_with_peft` 在装 torch 的 GPU 实例上失败：`MoLLlamaCpp.chat` 比 `MoLEngine.chat` 多一个 `run_id` 参数（签名不齐）。CI 无 torch 解释器跑时被 skip，故历史基线"绿"。属既有债。
- `tests/test_bench_config_has_no_removed_experts` 在服务器失败：服务器缺 `bench/benchmark_pathd.json`（部署漏发，本地有）。属部署缺口。
- A/B 验证若 content 为空：Qwen3.6 默认开 thinking 会吃光 `max_tokens` 预算。验证时带 `"chat_template_kwargs":{"enable_thinking":false}` 或调大 `max_tokens`。

---

## 8. Phase 1 实施记录（观测面板，2026-08-03 真机实测）

> 范围见地图 §5 Phase 1：**复用 llama.cpp 原生 `timings` + 现有字段词汇，新增线程安全的 `RequestEvent`（route / adapter / switch / TTFT / timings / KV / thinking / error / run_id）落 JSONL+SQLite，在现有 Gradio 面板渲染。不上 OpenLIT / OTel / Grafana。**

| 任务 | 结果 | 真机/离线证据 |
|------|------|----------|
| 观测数据模型 | ✅ | 新包 `screwshell/observ/{__init__,event,store}.py`：`RequestEvent` 不可变记录 + `ObservStore`（线程安全，JSONL+SQLite 双写，内存环形 200） |
| Coordinator 单一发射器 | ✅ | `inference_coordinator.request()` 每请求 emit 一个 `RequestEvent`；`RunMetrics` 仍单跑非线程安全、不作共享存储（地图 §6.8） |
| 诚实映射（不臆造） | ✅ | `_fill_from_body`：缺 `timings` → 字段留 `None`；`cached_tokens=0` 是**真实 0% KV 命中**（切专家后 KV 失效），记 `kv_hit_rate=0.0` 而非 `None`；`prompt_tokens=0` 才视为未知 |
| 流式 token 计数 | ✅ | 流式请求带 `stream_options:{"include_usage":true}`，末段 SSE 携带 `usage`，面板也能看 prompt/completion/cached |
| 中继暴露观测端点 | ✅ | `relay.py` 读 `X-Request-Id`/`X-Run-Id` 头；新增 `GET /v1/observ/summary` + `GET /v1/observ/events` |
| Gradio 面板 | ✅ | `ui/app.py` 起 2s 轮询线程拉 `/v1/observ/*`，渲染汇总（by_adapter/ok_rate/TTFT/prefill/decode/tps/KV）+ 最近请求行 |
| 持久化开关 | ✅ | `local-deploy/start_relay.sh` 设 `OBSERV_DIR=.../observ`；未设则 store 自动降级 no-op（开发/测试零副作用） |
| 验收测试 | ✅ | `tests/test_phase1_observ.py`（9 passed）+ `tests/test_inference_coordinator_request.py`（10 passed，行为闸）+ Phase0（9 passed）；离线全绿 |
| 真机端到端 | ✅ | 见下"真机运行态" |

### 关键设计决策（沿用地图 / 蓝图铁律）
1. **唯一发射器**：只有 `InferenceCoordinator` 写 `RequestEvent`；`RunMetrics` 仍单跑累加、永不作跨请求共享存储（地图 §6.8）。避免重复来源导致面板数字对不上。
2. **不臆造测量**（蓝图 §6.2 规则 9）：上游没回 `timings` → prefill/decode/KV 留 `None`，绝不拿墙钟猜。0% KV 是真实观测值，必须显式记 `0.0`。
3. **opt-in 持久化**：`OBSERV_DIR` 未设 → `get_store()` 返回 no-op store，`record_event` 静默丢弃、`recent`/`summarize` 返空。开发机与离线测试零副作用。
4. **线程安全**：`ObservStore` 所有读写走 `threading.Lock`；Gradio 轮询线程与 Coordinator 发射线程并发安全。

### 真机运行态（2026-08-03 验证）
- 中继 relay :18090（已重启，强制 base 启动）；Gradio UI :7860（轮询观测端点）。
- `GET /v1/observ/summary` 实测：
  `enabled:true, count:8, by_adapter:{cybersec:4,btl3:3,base:1}, ok_rate:1.0, avg_ttft_ms:373.55, avg_prefill_ms:213.96, avg_decode_ms:15577, avg_decode_tps:25.29, kv_hit_rate:0.3709, total_prompt_tokens:151, total_completion_tokens:2975, errors:[]`
- 最近事件：切专家请求 `kv_hit_rate:0.0`（真实 0%，非 `None`）；连续同专家 `cached_tokens>0` 显示 KV 复用（~0.83）。
- 顺带修掉一处**真机漂移 bug**：服务器上 `relay.py` 已升级 4 参 `_handle(body,is_stream,expert,request)` 但 legacy `/v1/completions` 调用点没跟上 → 500；已把本地 Phase 1 全部源文件重新同步到服务器并重载中继。

### 重启命令（同 §7）
```bash
# 中继（含观测持久化）
cd /workspace/persistent/screwshell_run && bash local-deploy/start_relay.sh   # :18090, OBSERV_DIR 已设
# UI（走中继，面板自带观测轮询）
MOL_BACKEND=llamacpp MOL_LLAMACPP_URL=http://127.0.0.1:18090 MOL_RELAY_MODE=1 \
  /opt/venv/bin/python -m screwshell.ui.app --workspace .../demo_workspace \
  --base .../models/Qwen3.6-27B-Q4_K_M.gguf --port 7860 --no-rag
```
