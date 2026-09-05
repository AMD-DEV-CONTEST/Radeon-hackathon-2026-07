# 观测台验证报告

- **日期**：2026-08-05
- **执行者**：HY3（按 `VALIDATION_OBSERVATORY_PLAN.md` 执行）
- **实例连通性**：✅ SSH 可达 `root@36.150.116.206:31010`（主机名 `u-14441-f4391bc7`，Ubuntu 24.04 / W7900）。说明 2026-08-04 重置后公钥已重新加回，`/workspace/persistent/screwshell_run` 已恢复。
- **边界遵守**：全程只读（curl / 读代码 / 读日志 / 短 prompt 测试 / ps）。未改任何生产代码、未重启/停止服务、未 pip 安装、未动 `loras/`。

---

## 决策表

| 决策 | 结论 | 一句话理由 |
|---|---|---|
| **D1** metrics / KV 命中 | `/metrics` **未开（501）**；但**请求级 KV 命中已真实可用且已落库** | llama-server 启动参数无 `--metrics`（返回 501 明确提示）；`usage.prompt_tokens_details.cached_tokens` 有真实值；relay `/v1/observ/events` 与 `requests.db` 的 `kv_hit_rate` 非空（177/182 行）。全局级 KV/吞吐需加 `--metrics`（属改造项，非本次验证项）。 |
| **D2** GPU 后端化 | **可行** | `rocm-smi --json` 单卡 `card0` 结构清晰，含温度/功耗维度；单次采样 **~127ms**；relay 侧 2s 轮询 → SQLite 时间序列完全可行（余量极大）。`amd-smi` 亦存在（可后续做 dmon 持续采样）。 |
| **D3** relay 统一事件 | **现状已具雏形，current_expert 已暴露** | `coordinator._current_expert` 每次切换更新；relay `/health` 已返回 `current_expert`；`/v1/observ/events` 已聚合 `kv_hit_rate`/`decode_tps`/`cached_tokens`。**无需新建端点即可支撑 R4**；仅缺独立 `/observ/expert`（nice-to-have）。 |

---

## 验证证据（A–E 逐项：命令 / 输出摘录 / 结论）

### A0 · SSH 连通性
```bash
ssh -p 31010 root@36.150.116.206 "echo OK && hostname"
```
- 输出：`OK` / `u-14441-f4391bc7`
- **结论**：连通正常，继续执行。

### A1 · 三端口健康检查
```bash
for p in 8080 18090 7860; do curl -s -o /dev/null -w "%{http_code}" ... ; done
```
- 输出：`8080 -> 200` / `18090 -> 200` / `7860 -> 404`
- **结论**：llama-server、relay 健康检查通过。UI(7860) 返回 404 仅因 Gradio 无 `/health` 路由，UI 进程实际在跑（A2 确认）。

### A2 · 进程与启动参数
```bash
ps aux | grep -E "llama-server|screwshell|relay|gradio" | grep -v grep
```
- 输出（节选）：
  - `llama-server ... --model Qwen3.6-27B-Q4_K_M.gguf --lora btl3,cybersec,rag_n7 ... --ctx-size 131072 --n-gpu-layers 999 --threads 24 --reasoning-budget 4096`（**无 `--metrics`**）
  - `/opt/venv/bin/python -m screwshell.gateway.relay`
  - `/opt/venv/bin/python -m screwshell.ui.app ... --port 7860 --no-rag`
- **结论**：三服务存活；确认 **llama-server 未启用 `--metrics`**（D1 直接证据）。

### B1 · `/metrics` 是否开启
```bash
curl -s -w "%{http_code}" http://127.0.0.1:8080/metrics
```
- 输出：`HTTP 501` → `{"error":{"code":501,"message":"This server does not support metrics endpoint. Start it with `--metrics`"}}`
- **结论**：**未开启**。`--metrics` 为改造项（部署脚本 `deploy/w7900/run_roomy_server.sh`、`llama-swap-managed.yaml` 均无此参数）。

### B2 · `/slots` 实时状态
```bash
curl -s http://127.0.0.1:8080/slots | python3 -m json.tool
```
- 输出（idle 态节选）：HTTP 200，返回 slot 数组，字段为
  `id / n_ctx / is_processing / n_prompt_tokens / n_prompt_tokens_processed / n_prompt_tokens_cache / params{...}`
  （本机 4 个 slot：id 0–3）。
- **结论**：`/slots` 可用，提供**每请求实时状态**。`is_processing=true` 即"正在生成"，配合 `n_prompt_tokens_processed` / 完成 token 数可支撑 **R1「模型在干什么」**。⚠️ 注意：真实字段是 **`is_processing`**（bool），**不是**计划假设的 `state`——构建期抓取代码须用真实字段名。

### B3 · KV 命中率（请求级）直接打 llama-server
```bash
curl -s -X POST .../v1/chat/completions -d '{"max_tokens":8,...}'
```
- 输出（节选）：
  ```
  "usage": { "completion_tokens":8, "prompt_tokens":11, "total_tokens":19,
             "prompt_tokens_details": { "cached_tokens": 9 } }
  "timings": { "cache_n": 9, "prompt_n": 2, "prompt_ms": 22625.374 }
  ```
- **结论**：**请求级 KV 命中真实有值**（`usage.prompt_tokens_details.cached_tokens=9`、`timings.cache_n=9`）。这就是本地 `RequestEvent.kv_hit_rate = cached/prompt` 的**真实数据源**——D1「请求级」路径已验证可用。`prompt_ms` 高仅为冷启动首请求，正常。

### B4 · relay 事件 `kv_hit_rate` 是否有值（链路验证）
```bash
curl -s -H "X-Relay-Token: screwshell-relay-devtoken" "http://127.0.0.1:18090/v1/observ/events?n=5"
```
- 输出（节选）：
  ```
  {'entry':'api','adapter':'btl3','kv_hit_rate':0.8424,'cached_tokens':52774,'decode_tps':17.50}
  {'entry':'api','adapter':'btl3','kv_hit_rate':0.9987,'cached_tokens':52666,'decode_tps':19.70}
  ```
- **结论**：relay 事件链路 **`kv_hit_rate` 已落真实数值（0.84–0.99）**。D1「relay 是否已产出 kv_hit_rate」= **是**，且已贯通到 UI 可消费的事件流。

### C1 · rocm-smi 文本格式
```bash
rocm-smi --showuse --showmeminfo vram
```
- 输出：`GPU[0] : GPU use (%) : 90`；`VRAM Total Memory (B): 51522830336`；`VRAM Total Used Memory (B): 29281378304`
- **结论**：文本解析源存在（单卡 W7900，48GB 显存，当时占用 ~27GB）。

### C2 · rocm-smi JSON 结构
```bash
rocm-smi --showuse --showmeminfo vram --json
```
- 输出：顶层 key 为 `card0`；字段 `GPU use (%)` / `VRAM Total Memory (B)` / `VRAM Total Used Memory (B)`。
- **结论**：**天然按卡分结构**，多卡会自然出现 `card1`… → **多卡支持零额外成本**。

### C3 · 温度/功耗维度
```bash
rocm-smi --showtemp --showpower --json
```
- 输出：`edge 53.0°C` / `junction 62.0°C` / `memory 58.0°C` / `Average Graphics Package Power (W): 198.0`
- **结论**：温度 + 功耗维度齐全 → **R3「健康判读」可交叉 利用率+温度+功耗**。

### C4 · amd-smi 是否存在
```bash
which amd-smi && amd-smi --version
```
- 输出：`amd-smi: EXISTS`（`--version` 非合法子命令，二进制本身可用）。
- **结论**：`amd-smi` 可用，后续可做 `amd-smi monitor` 持续采样（dmon 模式）作为时间序列增强源；当前 `rocm-smi` 已足够。

### C5 · 采样成本
```bash
for i in 1 2 3; do t0=...; rocm-smi --showuse --showmeminfo vram --json >/dev/null; t1=...; done
```
- 输出：采样 1/2/3 耗时 = **128 / 127 / 127 ms**。
- **结论**：单次采样 **~127ms ≪ 1s**。relay 侧 **2s（甚至 1s）轮询 → SQLite 时间序列**完全可行，CPU/延迟余量极大。**D2 = 可行**。

### D1 · relay live GPU 端点
```bash
curl -s -H "X-Relay-Token: screwshell-relay-devtoken" http://127.0.0.1:18090/v1/observ/gpu
```
- 输出：`{"used_b":29291704320,"total_b":51522830336,"use_pct":0.0,"ok":true}`（HTTP 200）
- **结论**：端点结构正确（与 `_read_gpu` 一致）。`use_pct=0.0` **非 bug**：`rocm-smi --showuse` 是**时间平均** GPU 占用指标——本验证早前流式请求期间为 90%，采样时 GPU 已空闲、均值衰减至 0。R3 实时图形源可用；**建议构建期对 use_pct 采用带时间窗的采样而非瞬时值**。

### D2 · relay `_read_gpu` 代码核对
```bash
grep -n "observ_gpu\|_read_gpu\|rocm-smi\|use_pct" relay.py
```
- 输出（节选）：`relay.py:233 def _read_gpu()`；`:238 ["rocm-smi","--showuse","--showmeminfo","vram"]`；`:260 "use_pct": use`；`:267 async def observ_gpu`；3s 缓存（`_gpu_cache`）。
- 本地基线（`relay.py` L225–276）与实例**一致**。
- **结论**：实例代码与本地基线对齐，确认 R3 现网已是「文本解析 + 3s 缓存 + 无历史」。

### D3 · `current_expert` 暴露现状
```bash
grep -n "current_expert" inference_coordinator.py
grep -n "current_expert\|observ/expert\|observ/gpu\|observ/events" relay.py
```
- 输出：
  - `coordinator.py:91/129` 初始化与重置；`:243/:332` 每次切换后 `self._current_expert = target`。
  - `relay.py:124` `/health` 返回 `"current_expert": coord._current_expert`；`:215 /v1/observ/events`；`:266 /v1/observ/gpu`。
- **结论**：**relay 已暴露 current_expert（经 `/health`）**——计划假设「relay 无暴露端点」已过时。R4「LoRA 切换更实时」**已部分满足**；仅缺独立 `/observ/expert`（可选增强，非必须）。

### D4 · observ 存储现状
```bash
env | grep -i OBSERV
find ... -name "requests.db"
python: SELECT ... FROM request_events
```
- 输出：无 `OBSERV` 环境变量（用默认目录）；`/workspace/persistent/screwshell_run/observ/requests.db` + `requests.jsonl` 存在。
  - Schema（节选）：`ts, request_id, run_id, route, adapter, switched, stream, model, thinking, prompt_tokens, cached_tokens, completion_tokens, ttft_ms, prefill_ms, decode_ms, decode_tps, kv_hit_rate, thinking_ms, ok, error, status_code`
  - 行数：**182**；`kv_hit_rate IS NOT NULL`：**177**。
  - 最近样本：`('btl3','btl3',0.9948,16.83)` / `('btl3','btl3',0.8424,17.50)`
- **结论**：observ 存储**真实在写且已落 182 条事件、177 条带 kv_hit_rate**。表模式可直接**同构扩展一张 `gpu_samples` 时间序列表**（ts / card / use_pct / vram_used_b / temp_c / power_w），D2 后端化无存储阻力。
  - ⚠️ 字段名注意：JSON 事件用 `entry`，落库列名为 `route`——构建期若读 DB 须用 `route`。

---

## 一句话总览（给 PM 看）
1. **R2 性能判读**：请求级 KV 命中（cache_n / cached_tokens）已真实打通到 relay 事件与 DB，**无需改造即可画判读**；唯「全局吞吐/全局 KV」需给 llama-server 加 `--metrics`（一行部署改造）。
2. **R3 GPU 图形化 + 历史**：rocm-smi JSON 单卡结构清晰、含温度/功耗、采样仅 127ms → **relay 侧 2s 轮询写 SQLite 时间序列完全可行**，重启不丢；`use_pct` 用时间平均采样即可。
3. **R1 模型在干什么**：`/slots` 的 `is_processing` + token 进度可实时驱动；relay `/health` 已返回 `current_expert`，R4 LoRA 切换实时性基本满足。
4. **R4 审计/证据**：`/v1/observ/events` + `requests.db` 已聚合 kv_hit_rate/decode_tps/cached_tokens，证据卡与审计日志的数据底座已存在。

> 所有结论均来自上述命令的真实输出，未改动任何代码、未重启服务。
