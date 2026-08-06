# ScrewShell 观测台 — 验证施工计划（执行 Agent 专用）

> 执行者：HY3。本文档自包含：背景、目标、边界、分步命令、验收标准、交付物。
> 生成：2026-08-05。关联文档：`HANDOFF_OBSERVATORY.md`（需求与架构基线）。

---

## 0. 背景（30 秒上手）

ScrewShell 是私有、本地、隐私优先的 AI 调查员，跑在单台 AMD Radeon PRO W7900 48GB / ROCm 上，用 MoL（Mixture-of-LoRA）：冻结基座 `Qwen3.6-27B` GGUF + 热切换 LoRA 专家。请求链路：

```
UI(Gradio :7860) ─┐
opencode          ├─► relay(:18090, SSOT) ─► llama-server(:8080)
pi                ┘    全局单 LoRA 串行锁
```

UI 观测台有四条需求（R1–R4）：
- **R1** 模型在干什么（实时状态，非静态"调查中…"）
- **R2** 性能判读（TTFT<5s、解码 23–31 tok/s、KV 命中>80%，带正常/异常标注）
- **R3** GPU 图形化 + 随时间变化的图表（用户最在意；现为 UI 侧 ring-buffer，重启即丢）
- **R4** 权限/审计日志、证据卡、LoRA 切换更实时

已联网调研出三个**候选数据源**（此前未接入），本次验证它们是否在真机可用：

| 候选数据源 | 预期支撑 | 现状 |
|---|---|---|
| llama-server `--metrics` → `/metrics` | R2 的 KV 命中/全局吞吐，**独立于请求** | 部署脚本未见 `--metrics` 参数 |
| llama-server `/slots` | R1 每请求实时状态（processing/idle + token 数） | 未使用 |
| rocm-smi / amd-smi JSON | R3 GPU 历史采样原料（含温度/功耗维度） | relay 现用**文本解析**即时值 |

---

## 1. 目标

**只验证、不改代码。** 输出一份带命令证据的验证报告，回答三个决策点：

- **D1**：llama-server 是否已开 `--metrics`？KV 命中率数据源现状（请求级 vs 全局级）？
- **D2**：GPU 历史后端化（relay 侧采样 → SQLite 时间序列）可行性？单次采样成本？
- **D3**：relay 合成结构化事件（统一观测 opencode 的证据/审计）的代码位置与现状？

## 2. 边界（必须遵守）

- ✅ 允许：只读 curl、读代码、读日志、发短 prompt 测试请求、`ps`/`ss`/`which` 查进程
- ❌ 禁止：改任何生产代码、重启/停服务、pip 安装、删除/移动文件、动 `loras/`
- 测试请求一律**短 prompt（<50 token）**、`max_tokens` 小（≤8），避免长推理
- 实例大概率离线：**不得依赖外网**
- 每执行一步先记录命令与输出，最后统一汇总

## 3. 环境

- 实例：`root@36.150.116.206 -p 31010`（Ubuntu 24.04 / W7900）
- 端口：llama-server `127.0.0.1:8080`、relay `127.0.0.1:18090`、UI `127.0.0.1:7860`
- relay 信任令牌（已在现网）：`X-Relay-Token: screwshell-relay-devtoken`
- ⚠️ **前置风险**：SSH host key 可能已变化、publickey 可能被拒（服务端 `authorized_keys` 曾还原出厂）。先做 A0 连通性检查；**连不上立即回报，不要反复重试、不要尝试改服务端配置**。

---

## 4. 验证步骤

### A. 前置：连通性与服务存活

**A0 · SSH 连通性**
```bash
ssh -o ConnectTimeout=10 -p 31010 root@36.150.116.206 "echo OK && hostname"
```
> 失败即停，回报用户处理（需重新加公钥）。

**A1 · 三端口健康检查**（在实例上）
```bash
for p in 8080 18090 7860; do
  echo -n "port $p: "
  curl -s -o /dev/null -w "%{http_code}\n" --max-time 5 "http://127.0.0.1:$p/health" || \
  curl -s -o /dev/null -w "%{http_code}\n" --max-time 5 "http://127.0.0.1:$p/"
done
```
> 预期：8080/18090/7860 各自返回 200 或可接受重定向码；记录实际值。

**A2 · 记录进程与启动参数**
```bash
ps aux | grep -E "llama-server|screwshell" | grep -v grep
```
> 重点记录 llama-server 命令行里**是否含 `--metrics`**；以及 relay/UI 进程的完整命令。

### B. llama.cpp 数据源（D1 直接证据）

**B1 · `/metrics` 是否开启**
```bash
curl -s -o /tmp/metrics_probe.txt -w "%{http_code}\n" --max-time 5 http://127.0.0.1:8080/metrics
head -5 /tmp/metrics_probe.txt
```
- 若 **404**：未开 `--metrics` → 结论"需改启动参数（改造项，非验证项）"，跳到 B2。
- 若 **200**：提取关键指标名：
```bash
grep -oE "^llama[a-z_:]*" /tmp/metrics_probe.txt | sort -u
grep -E "cache_hit|prompt_tokens_total|tokens_predicted_total|n_busy" /tmp/metrics_probe.txt | head -10
```
> 预期指标（若开）：`llama:cache_hits_total`、`llama:prompt_tokens_total`、`llama:tokens_predicted_total`、`llama:n_busy_slots_per_decode` 等。

**B2 · `/slots` 实时状态**
```bash
curl -s --max-time 5 http://127.0.0.1:8080/slots | python3 -m json.tool | head -40
```
> 记录每个 slot 的字段（`id` / `state` / `n_past` / `prompt_tokens` / `predicted_tokens`）。若 `state=idle`，可另开一条流式请求（见 B3）同时再 curl `/slots`，验证 `state=processing` 的形态。判断：能否支撑 R1"正在生成第 N 个请求、已吐 M token"。

**B3 · KV 命中率数据源（请求级）——直接打 llama-server 隔离验证**
```bash
curl -s -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"m","messages":[{"role":"user","content":"hi"}],"max_tokens":8,"stream":false}' \
  | python3 -m json.tool | grep -A5 -i "usage\|prompt_tokens"
```
> 关键看 `usage` 里是否有 `prompt_tokens_details.cached_tokens`（KV 缓存命中数）→ 这决定本地 `RequestEvent.kv_hit_rate` 的数据来源是否真实有值。字段缺失也如实记录（可能 llama.cpp 版本较老）。

**B4 · relay 事件里 `kv_hit_rate` 是否有值（链路验证）**
```bash
curl -s -H "X-Relay-Token: screwshell-relay-devtoken" \
  "http://127.0.0.1:18090/v1/observ/events?n=10" | python3 -m json.tool
```
> 若上一步 B3 请求走了 relay 链路（或等 UI 有一次真实请求后），检查事件 JSON 中 `kv_hit_rate` / `cached_tokens` 字段是否非空。记录最近 3 条事件的 `entry` / `adapter` / `kv_hit_rate`。

### C. AMD GPU 数据源（D2 直接证据）

**C1 · relay 现用格式（文本）**
```bash
rocm-smi --showuse --showmeminfo vram
```
> 记录原始输出（VRAM Total/Used、GPU use %）。

**C2 · JSON 格式（是否 per-card、字段名）**
```bash
rocm-smi --showuse --showmeminfo vram --json
```
> 记录 JSON 结构：是否按 `card0`/`card1` 分卡、字段名（`GPU use (%)`、`VRAM Total Memory (B)` 等）。这决定"多卡支持"是否天然可得。

**C3 · 温度/功耗维度**
```bash
rocm-smi --showtemp --showpower --json
```
> 记录是否返回温度/功耗字段（R3"健康判读"需要交叉利用率+温度+功耗）。

**C4 · 新版 amd-smi 是否存在**
```bash
which amd-smi && amd-smi --version
```
- 存在 → 试 `amd-smi metric --usage --json` 与 `amd-smi monitor --help`（dmon 持续输出模式，时间序列原料）。
- 不存在 → 记录"仅 rocm-smi 可用"，不安装。

**C5 · 采样成本（2s 轮询可行性）**
```bash
for i in 1 2 3; do time rocm-smi --showuse --showmeminfo vram --json >/dev/null; done
```
> 记录每次耗时。若稳定 <1s，说明 relay 侧后端采样（甚至 2s 间隔）可行；若 >2s，说明只能低频采样或走 amd-smi dmon。

### D. relay / observ 现状（代码 + live 对照，D3 依据）

**D1 · live 验证 GPU 端点**
```bash
curl -s -H "X-Relay-Token: screwshell-relay-devtoken" http://127.0.0.1:18090/v1/observ/gpu
```
> 预期结构（与本地代码 `_read_gpu` 一致）：`{used_b, total_b, use_pct, ok}`。

**D2 · 读实例代码确认（与本地基线对比）**
```bash
grep -n "observ_gpu\|_read_gpu\|rocm-smi" /workspace/persistent/screwshell_run/screwshell/gateway/relay.py | head -20
```
> 确认实例与本地基线一致（本地基线：relay.py 225–276 行，`rocm-smi --showuse --showmeminfo vram` 文本解析 + 3s 缓存 + 无历史）。

**D3 · 是否暴露"当前全局专家"端点（R4 小补丁可行性）**
```bash
grep -rn "current_expert" /workspace/persistent/screwshell_run/screwshell/core/inference_coordinator.py | head -5
grep -rn "current_expert\|observ/expert" /workspace/persistent/screwshell_run/screwshell/gateway/relay.py | head -5
```
> 预期：coordinator 有 `_current_expert`（请求切换时更新），但 relay **无**暴露端点 → 记录"小补丁位置：relay 加只读端点读 coordinator 状态"。

**D4 · observ 存储现状**
```bash
env | grep -i OBSERV
ls -la /workspace/persistent/screwshell_run/observ* 2>/dev/null || find /workspace/persistent/screwshell_run -maxdepth 2 -name "requests.db" 2>/dev/null
```
> 若找到 `requests.db`：`sqlite3 requests.db ".schema"` 与 `SELECT count(*) FROM request_events;`（sqlite3 无则跳过，不安装）。记录表结构与行数 → 判断"GPU 时间序列表"可否按同模式扩展。

### E. 汇总报告（交付）

在实例上写 `/workspace/persistent/screwshell_run/VALIDATION_OBSERVATORY_REPORT.md`（也可 scp 回本地），结构如下：

```markdown
# 观测台验证报告
日期 / 执行者 / 实例连通性结论

## 决策表
| 决策 | 结论 | 一句话理由 |
|---|---|---|
| D1 metrics/KV 命中 | 未开(404) / 已开(200)… | ... |
| D2 GPU 后端化 | 可行 / 有条件可行 / 不可行 | 采样成本 Xms + JSON 结构… |
| D3 relay 统一事件 | 现状… 小补丁位置… | ... |

## 验证证据（A–E 每项）
### B1 /metrics  → 输出摘录 → 结论
### B2 /slots    → 输出摘录 → 结论
...（每项一行：命令/输出摘录/结论）
```

---

## 5. 验收标准

1. A–E 全部覆盖，每项有**命令 + 输出摘录 + 结论**。
2. 未改任何生产代码、未重启/停止服务。
3. 报告明确回答 D1/D2/D3，且每条结论可追溯回证据。
4. 若 SSH 连不上（A0 失败），**只回报用户，不尝试修复**。

## 6. 交付物

- 验证报告：`/workspace/persistent/screwshell_run/VALIDATION_OBSERVATORY_REPORT.md`（并在回复中给出关键结论摘要）
- 如 A0 失败：回复连通性失败详情，等待用户处理公钥后再执行。

---

## 附：本地对照代码基线（供读代码时对齐）

- `screwshell/gateway/relay.py` L225–276：`_read_gpu()` 用 `rocm-smi --showuse --showmeminfo vram` 文本解析 → `{used_b,total_b,use_pct,ok}`；`/v1/observ/gpu` 3s 缓存。
- `screwshell/observ/event.py`：`RequestEvent` 已有 `cached_tokens`、`kv_hit_rate`（=cached/prompt）、`decode_tps` 等字段；`entry` = `ui`(有 run_id) / `api`。
- `screwshell/observ/store.py`：JSONL + SQLite（`request_events` 表含 `kv_hit_rate` 列），`OBSERV_DIR` 未设则 no-op；`summarize()` 已聚合 `kv_hit_rate`。
- `screwshell/core/inference_coordinator.py` L91/L129/L243/L332：`_current_expert` 在每次切换后更新，无外部读取端点。
- 部署脚本（`deploy/w7900/run_roomy_server.sh`、`run_gateway.sh`、`llama-swap-managed.yaml`）：llama-server 启动参数**均无 `--metrics`**。
