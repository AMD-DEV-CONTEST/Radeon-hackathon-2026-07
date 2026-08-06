# ScrewShell 观测台 — 施工计划（执行 Agent 专用）

> 执行者：HY3。本文档自包含：背景、四项施工、逐文件改动点（含行号）、测试、部署、验收、风险回滚。
> 生成：2026-08-05。前置文档：`VALIDATION_OBSERVATORY_PLAN.md`（验证）→ `VALIDATION_OBSERVATORY_REPORT.md`（结论，已确认可行性）。

---

## 0. 背景（30 秒上手）

ScrewShell = 私有本地 AI 调查员（AMD W7900 48GB / ROCm / MoL：Qwen3.6-27B 基座 + LoRA 专家）。链路：`UI(Gradio :7860) / opencode / pi → relay(:18090, SSOT) → llama-server(:8080)`。

UI 观测台四条需求，本次施工全部落地（验证报告已确认可行性）：
- **R1** 模型在干什么 → `/slots` 实时状态转发
- **R2** 性能判读 → 阈值按真机校准 + 可选 `--metrics` 全局视角
- **R3** GPU 图形化 + 历史（最在意）→ relay 后台采样落库，UI 消费后端历史（重启不丢）
- **R4** 审计/LoRA 实时 → **主需求已实现**（UI 已读 `/health` 的 `current_expert`），本次只做语义增强

## 1. 施工总览

| # | 施工项 | 改动文件 | 规模 | 风险 |
|---|---|---|---|---|
| 1 | GPU 历史后端化（R3 根治） | `store.py` + `relay.py` + `app.py` | 中 | 低 |
| 2 | `/slots` 转发 + 状态块（R1） | `relay.py` + `app.py` | 小 | 低 |
| 3 | 独立 expert 端点（R4 增强） | `relay.py` + `app.py` | 极小 | 无 |
| 4a | tok/s 阈值校准（R2） | `app.py` | 极小 | 无 |
| 4b | `--metrics` 全局视角（R2 可选） | 3 个部署脚本 + `relay.py` + `app.py` | 中 | **高（重启 llama-server）** |

**硬约束**：
- 只改：`screwshell/observ/store.py`、`screwshell/gateway/relay.py`、`screwshell/ui/app.py`、`deploy/w7900/{run_roomy_server.sh, run_gateway.sh}`、`deploy/w7900/llama-swap-managed.yaml`、新增 `tests/test_observ_gpu.py`、（若基线变）`TRUTH.md` + `scripts/verify_bugfixes.py`。
- **不动**：`event.py`、`inference_coordinator.py`、`orchestrator.py`、路由/切换逻辑、`RequestEvent` 数据模型。
- **零新依赖**（httpx / fastapi / pandas 均已存在）。实例离线，禁止 pip。
- 本机测试：受管 venv `C:/Users/djb/.workbuddy/binaries/python/envs/default/Scripts/python.exe` 跑 `pytest tests/`（**重定向到文件再 cat，勿用管道**；本机 safe-delete 会卡 pytest 统计行）。

---

## 2. 施工项 1：GPU 历史后端化（R3 根治）

### 2.1 `screwshell/observ/store.py` — 加 `gpu_samples` 表 + 采样写入/读取

**改动点**（对照现有 `request_events` 模式，全部同构）：

1. 在 `_COLS`（L29–34）附近新增 GPU 采样列常量：
```python
_GPU_COLS = ["ts", "card", "use_pct", "vram_used_b", "vram_total_b",
             "temp_c", "power_w"]
_GPU_RING_MAX = 1800   # 1h @ 2s
```
2. `__init__`（L38–46）加 `self._gpu_recent: list[dict] = []`。
3. `_open`（L49–77）里，在 `CREATE TABLE request_events` 之后追加建表：
```sql
CREATE TABLE IF NOT EXISTS gpu_samples (
  ts REAL, card TEXT, use_pct REAL, vram_used_b REAL,
  vram_total_b REAL, temp_c REAL, power_w REAL)
```
   建表后同样从磁盘预热 `_gpu_recent`（`SELECT * FROM gpu_samples ORDER BY ts DESC LIMIT ?`，逆序填充）。
4. 新增两个方法（放 `record`/`recent` 附近）：
```python
def record_gpu_sample(self, s: dict) -> None:
    """s = {ts, card, use_pct, vram_used_b, vram_total_b, temp_c, power_w}"""
    if not self.enabled:
        return
    # INSERT INTO gpu_samples VALUES (?,?,?,?,?,?,?) — 与 request_events 同样的
    # try/except 双保险（JSONL 不需要，只落 SQLite + 内存 ring）
    # self._gpu_recent.append(s); 超 _GPU_RING_MAX 时 del [0]

def recent_gpu(self, n: int = 180) -> list[dict]:
    """内存 ring 优先（热路径）；ring 为空时回查表（冷启动/UI 重启恢复）。"""
    with self._lock:
        if self._gpu_recent:
            return list(reversed(self._gpu_recent[-n:]))
        # SELECT * FROM gpu_samples ORDER BY ts DESC LIMIT n，逆序返回
```
5. 模块级便捷函数（照 `record_event`/`recent_events` L182–191 模式）：
```python
def record_gpu_sample(s: dict) -> None: ...
def recent_gpu(n: int = 180) -> list[dict]: ...
```

**验收（本地）**：`OBSERV_DIR` 指向临时目录时 `record_gpu_sample` ×3 → `recent_gpu(10)` 返回 3 条且字段齐全；关闭 store（未设 OBSERV_DIR）时静默 no-op 不抛异常。

### 2.2 `screwshell/gateway/relay.py` — 后台采样线程 + `gpu_history` 端点

1. **新增详细采样函数**（放在 `_read_gpu` L233–263 之后，**保留原 `_read_gpu` 不动**——`/v1/observ/gpu` 兼容现有 UI 旧逻辑）：
```python
def _read_gpu_detailed() -> dict:
    """rocm-smi --json（含温度/功耗）。失败返回 {"ok": False}。"""
    out = subprocess.run(
        ["rocm-smi", "--showuse", "--showmeminfo", "vram",
         "--showtemp", "--showpower", "--json"],
        capture_output=True, text=True, timeout=10).stdout
    d = json.loads(out)  # 顶层 key: card0 / card1...
    card = next((k for k in d if k.startswith("card")), "card0")
    info = d[card]
    return {
        "ts": time.time(), "card": card,
        "use_pct": float(info.get("GPU use (%)") or 0),
        "vram_used_b": int(info.get("VRAM Total Used Memory (B)") or 0),
        "vram_total_b": int(info.get("VRAM Total Memory (B)") or 0),
        "temp_c": float(info.get("temperature", {}).get("edge") or 0),
        "power_w": float(info.get("Average Graphics Package Power (W)") or 0),
        "ok": True,
    }
```
   > ⚠️ JSON 字段名以真机 `rocm-smi --showuse --showmeminfo vram --showtemp --showpower --json` 实际输出为准（验证报告 C2/C3 已见 `card0`/`GPU use (%)`/`VRAM Total Memory (B)`/`edge`/`Average Graphics Package Power (W)`）；温度/功耗键如不匹配，实施时先打印原始 JSON 再定解析键。

2. **后台采样线程**：在 `lifespan`（L77–114）的 `yield` 前启动：
```python
def _gpu_sampler_loop():
    while True:
        try:
            s = _read_gpu_detailed()
            if s.get("ok"):
                record_gpu_sample(s)
        except Exception as e:  # noqa: BLE001 - 采样失败不炸 relay
            log.warning("gpu sample failed: %s", e)
        time.sleep(2.0)

_threading.Thread(target=_gpu_sampler_loop, daemon=True).start()
```
   `record_gpu_sample` 从 `screwshell.observ` 导入（L31 那行 import 追加）。

3. **新端点**（放 `/v1/observ/gpu` L266–276 之后）：
```python
@app.get("/v1/observ/gpu_history")
async def observ_gpu_history(request: Request, n: int = 180):
    if not _observ_authorized(request):
        return JSONResponse(status_code=401, content={"error": "missing/invalid X-Relay-Token"})
    if n < 1 or n > 1800:
        n = 180
    return JSONResponse({"samples": recent_gpu(n)})
```

### 2.3 `screwshell/ui/app.py` — GPU 图改消费后端历史

1. `_poll_observ_once`（L194–228）：**GPU 段改为主拉历史、整体重建**：
```python
gh = _obs_get("/v1/observ/gpu_history?n=180")
if gh is not None and gh.get("samples"):
    _GPU_HIST.clear()
    for s in gh["samples"]:
        if isinstance(s.get("ts"), (int, float)):
            vram_pct = None
            if isinstance(s.get("vram_used_b"), (int, float)) and isinstance(
                    s.get("vram_total_b"), (int, float)) and s.get("vram_total_b"):
                vram_pct = s["vram_used_b"] / s["vram_total_b"] * 100
            _GPU_HIST.append({"ts": s["ts"], "vram_pct": vram_pct,
                              "util_pct": s.get("use_pct"),
                              "temp_c": s.get("temp_c"),
                              "power_w": s.get("power_w")})
else:
    # fallback：旧逻辑（即时值 append），relay 无历史时保底
    ...保留现有 L201-215 代码...
```
   > 效果：UI 重启后首次 poll 即从后端拉回最近 180 点 → **重启不丢历史**；`_GPU_HIST` 语义变为"后端快照镜像"，不再需要累积逻辑。
2. `_gpu_df`（L243–251）：DataFrame 列加 `temp_c`/`power_w`（仅当元素有值）。
3. **图保持 2 条线**（vram_pct / util_pct，L554–557 不动）；温度/功耗进文本块 `_fmt_gpu`（L333–346）追加一行：
```python
t = g.get("temp_c"); pw = g.get("power_w")   # 从最近一条 _GPU_HIST 取（若无则 n/a）
... temp/power 行：f"温度 {t:.0f}°C · 功耗 {pw:.0f}W"
```
   > 量纲不同（温度 50–70 vs 利用率 0–100）不宜同图，文本行展示。

**验收（本地）**：`pytest tests/test_observ_gpu.py` 绿；手测 relay：`curl :18090/v1/observ/gpu_history?n=10` 返回 samples 数组。

---

## 3. 施工项 2：`/slots` 转发 + 状态块（R1）

### 3.1 `relay.py` — 新端点（照 `/v1/models` L128–135 模式）
```python
@app.get("/v1/observ/slots")
async def observ_slots(request: Request):
    if not _observ_authorized(request):
        return JSONResponse(status_code=401, content={"error": "missing/invalid X-Relay-Token"})
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(coord.engine.server_url + "/slots")
            return JSONResponse(r.json())
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=502)
```

### 3.2 `app.py` — 状态块加推理槽位行

1. `_poll_observ_once` 加：`_obs_state["slots"] = _obs_get("/v1/observ/slots")`（L216 `/health` 附近）。
2. 新增小函数（放 `_status_block` L264–272 前）：
```python
def _slots_line(lang: str) -> str:
    sl = _obs_state.get("slots")
    if not isinstance(sl, list) or not sl:
        return ""
    busy = [s for s in sl if s.get("is_processing")]
    zh = lang == "zh"
    if busy:
        s = busy[0]
        prog = s.get("n_prompt_tokens_processed") or 0
        total = s.get("n_prompt_tokens") or 0
        return (f"推理槽: slot {s.get('id','?')} 处理中（{prog}/{total}）"
                if zh else f"slot {s.get('id','?')} processing ({prog}/{total})")
    return "推理槽: 空闲" if zh else "slot: idle"
```
3. `_status_block` 返回值末尾追加 `_slots_line(lang)`（有值才加）。
   > ⚠️ 字段名铁律：真实字段是 **`is_processing`**（bool）+ **`n_prompt_tokens_processed`** / **`n_prompt_tokens`**（验证报告 B2），**不是** `state`。实施前再 curl 一次 `/slots` 核对字段名。

**验收**：`curl :18090/v1/observ/slots` 返回 4 个 slot 数组；UI 状态块在生成时显示"处理中"、空闲显示"空闲"。

---

## 4. 施工项 3：独立 expert 端点（R4 语义增强）

> **背景修正**：验证报告 D3 确认 UI `_fmt_lora`（app.py L315–330）**已通过 `/health` 读 `current_expert`**——R4 主需求已满足。本次只把"专家状态"从无鉴权的 `/health` 挪到 observ 语义路径，5 行的事，**不做 UI 大改**。

### 4.1 `relay.py` — 新端点
```python
@app.get("/v1/observ/expert")
async def observ_expert(request: Request):
    if not _observ_authorized(request):
        return JSONResponse(status_code=401, content={"error": "missing/invalid X-Relay-Token"})
    return JSONResponse({"current_expert": coord._current_expert,
                         "adapters": list(coord.engine.adapters)})
```

### 4.2 `app.py` — `_fmt_lora` 改优先读新端点
- `_poll_observ_once` 加：`_obs_state["expert"] = _obs_get("/v1/observ/expert")`。
- `_fmt_lora`（L317）改为：`h = _obs_state.get("expert") or _obs_state.get("health") or {}`（fallback 保底）。

**验收**：`curl :18090/v1/observ/expert` 返回 `{"current_expert": "btl3"|null, "adapters": [...]}`；UI LoRA 面板无回归。

---

## 5. 施工项 4a：tok/s 阈值校准（R2）

**依据**：验证报告实测 `decode_tps` 17.5–19.7，低于现阈值 23–31 → 观测台会天天误报"⚠️"。校准窗口 **15–25 tok/s**（含实测值 + 约 20% 余量）。

### `app.py` 两处：
1. **L293**（中文指标面板）：`_ok_warn(25 <= tps <= 31)` → `_ok_warn(15 <= tps <= 25)`；文案 `正常 23–31` → `正常 15–25`。
2. **L376**（中文生成块）：`（23–31 正常）` → `（15–25 正常）`。

> 英文分支（L307–309）只显示裸数字，无需改。TTFT 阈值（<5s）不动。

**验收**：面板在 decode≈17–20 时显示 ✓ 而非 ⚠️。

---

## 6. 施工项 4b：`--metrics` 全局视角（R2 可选，⚠️ 高风险）

> ⚠️ **唯一需要重启 llama-server 的施工项**（重启 = 2–3 分钟模型加载 + 全部 KV 缓存失效 + opencode/UI 短暂不可推理）。**本项最后单独执行**，做完一项验一项。

### 6.1 部署脚本加参数（3 处）
- `deploy/w7900/run_roomy_server.sh`（llama-server 启动段）
- `deploy/w7900/run_gateway.sh`（同段）
- `deploy/w7900/llama-swap-managed.yaml`（`llama-server` 命令段）

统一在 llama-server 参数中加：`--metrics`

### 6.2 `relay.py` — 全局指标端点
```python
@app.get("/v1/observ/llama_metrics")
async def observ_llama_metrics(request: Request):
    if not _observ_authorized(request):
        return JSONResponse(status_code=401, content={"error": "missing/invalid X-Relay-Token"})
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(coord.engine.server_url + "/metrics")
        text = r.text
        counters = {}
        for key in ("cache_hits_total", "prompt_tokens_total",
                    "tokens_predicted_total", "n_busy_slots_per_decode"):
            m = re.search(rf"^llama:{key}\s+([0-9.]+)", text, re.M)
            counters[key] = float(m.group(1)) if m else None
        return JSONResponse({"ok": True, "counters": counters})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)
```
> ⚠️ **指标名铁律**：llama.cpp `/metrics` 真实指标名以**重启后真机输出为准**（当前 501 没见过内容，联网资料有 `llama:` 与 `llamacpp:` 两种说法）。实施流程：重启 llama-server → `curl :8080/metrics | grep -oE "^llama[a-z_:]*" | sort -u` → 用**枚举到的真实前缀/名字**替换上面正则。若启动后 501 依旧（llama.cpp 版本不支持），**停做 6.3/6.4，只保留部署参数**并注明。

### 6.3 `app.py` — 指标面板加"全局"行
- `_poll_observ_once` 加：`_obs_state["llama_metrics"] = _obs_get("/v1/observ/llama_metrics")`。
- `_fmt_metrics`（L290–305 中文 lines 列表）末尾追加：
```python
lm = _obs_state.get("llama_metrics") or {}
c = lm.get("counters") or {}
if c.get("prompt_tokens_total") is not None:
    lines.append(f"全局(server): KV命中+{c.get('cache_hits_total')} 总token {c.get('prompt_tokens_total',0)+c.get('tokens_predicted_total',0)}")
```
   > 全局 KV 命中率需要"缓存命中累计 / prompt 累计"计算，实施时按真实指标名定公式；拿不到就显示 `全局: n/a`。

### 6.4 回滚预案（写死）
- 保留原启动命令快照（`cp` 一份原脚本）；llama-server 起不来/异常 → 用原命令重启，撤 relay/app 改动中 6.2/6.3 相关行。
- 4b 任何一步失败**只回滚 4b**，不影响施工项 1–3 已部署部分。

---

## 7. 测试与基线维护（项目铁律）

1. **新增 `tests/test_observ_gpu.py`**（本机 pytest，可离线跑）：
   - `ObservStore` 临时目录：`record_gpu_sample` ×3 → `recent_gpu(10)` 返回 3 条、字段齐全、顺序正确（新在前）。
   - 未设 `OBSERV_DIR` → no-op 不抛异常。
   - relay 端点（httpx ASGI / TestClient）：`/v1/observ/gpu_history` 鉴权 401（无 token 且有 RELAY_TRUST_TOKEN 时）、正常返回 samples；`/v1/observ/slots` 模拟 upstream 返回 slot 数组；`/v1/observ/expert` 返回 current_expert；`/v1/observ/llama_metrics` 用 monkeypatch 伪造 `/metrics` 文本（含 `llama:cache_hits_total 4096` 等）验证解析。
2. **基线同步（必做）**：`pytest tests/` 全量（重定向文件再 cat）→ 通过数 ≥ 原 185 → 更新 `TRUTH.md` §3 基线为 `185+N`，并同步 `scripts/verify_bugfixes.py` §8 阈值（若断言写死 180 则不必动，若写 185 则 bump）。
3. 三道闸全绿：① pytest 全量 ② `scripts/verify_bugfixes.py` 退出码 0 ③ `git fsck` 无 missing。

---

## 8. 部署（实例 `36.150.116.206:31010`）

**顺序（严格）**：relay → UI → 观察 → 4b（llama-server，最后单独）。

```bash
# 1) scp 改动文件到实例
scp -P 31010 screwshell/observ/store.py screwshell/gateway/relay.py \
    root@36.150.116.206:/workspace/persistent/screwshell_run/screwshell/observ/
# ... 注意目录：relay.py 进 gateway/，app.py 进 ui/
# 2) 重启 relay（照 HANDOFF_OBSERVATORY.md §6 环境变量，勿用旧脚本）
#    export MOL_BACKEND=llamacpp MOL_LLAMACPP_URL=http://127.0.0.1:18090
#    export MOL_RELAY_MODE=1 RELAY_TRUST_TOKEN=screwshell-relay-devtoken
#    export OBSERV_DIR=/workspace/persistent/screwshell_run/observ
#    nohup /opt/venv/bin/python -m screwshell.gateway.relay > relay.log 2>&1 &
# 3) 重启 UI（同一组环境变量 + --workspace --base --port 7860 --no-rag）
# 4) 等 5s+，验证（本地经 SSH 隧道）：
curl -s -H "X-Relay-Token: screwshell-relay-devtoken" \
  "http://127.0.0.1:18090/v1/observ/gpu_history?n=10"
curl -s -H "X-Relay-Token: screwshell-relay-devtoken" \
  http://127.0.0.1:18090/v1/observ/slots
curl -s -H "X-Relay-Token: screwshell-relay-devtoken" \
  http://127.0.0.1:18090/v1/observ/expert
# UI :7860 HTTP 200 + GPU 图出现历史折线 + 状态块显示槽位
# 5) 最后做 4b：改部署脚本加 --metrics → 重启 llama-server → curl :8080/metrics 枚举指标名
```

**验证注意事项**：
- relay/UI 重启用 HANDOFF §6 命令（`/opt/venv/bin/python`），**禁用实例上的 `_run_ui.sh`/`_run_ui_gw.sh`**（指向 8080/18080，非 relay）。
- gradio 6.22.0 陷阱：`Chatbot(type=...)` 参数不存在——本次**不改 Chatbot 定义**，只动 LinePlot value 数据源与 Markdown 文本，避开。
- `use_pct` 是时间平均指标，采样线程记录原值即可，**不要**在 relay 侧做二次平均（2s 间隔本身就是时间窗）。

---

## 9. 验收清单（全部通过才算完工）

- [ ] pytest 全量绿（基线 ≥185+N）、verify_bugfixes.py 退出码 0、TRUTH.md §3 已同步
- [ ] relay `/v1/observ/gpu_history` 返回时间序列，2 个采样周期后 ≥4 条样本
- [ ] relay 重启后 `gpu_history` 仍能回查（SQLite 持久）——UI 重启后 GPU 图有历史线
- [ ] `/v1/observ/slots` 返回 4 slot；生成期间状态块显示"处理中"，空闲显示"空闲"
- [ ] `/v1/observ/expert` 返回 current_expert；LoRA 面板无回归
- [ ] 面板 decode≈17–20 显示 ✓（阈值已校准 15–25）
- [ ] 4b：llama-server 带 `--metrics` 启动，`/metrics` 200；`/v1/observ/llama_metrics` 返回 counters（或注明 n/a 原因）
- [ ] 实例全程未动 `loras/`、未装任何包、未改 coordinator/orchestrator/event.py

## 10. 交付物

- 代码改动（本仓库 3 个源文件 + 部署脚本 + 测试文件）
- 实例部署完成 + 上述验收逐条证据
- 简短施工报告：每项改动摘要 + 验收输出摘录 + 遗留问题（若有）

---

## 附：本地代码基线速查（改动点行号）

- `store.py`：`_COLS` L29–34；`__init__` L38–46；`_open` L49–77（建表处）；`record` L80–100；`recent` L103–105；模块级包装 L182–191。
- `relay.py`：`LLAMA_SERVER_URL` L35；`lifespan` L77–114（采样线程启动点）；`/health` L122–125；`/v1/models` L128–135（slots/llama_metrics 端点模板）；`_read_gpu` L233–263；`observ_gpu` L266–276；`__main__` L279–282。
- `app.py`：`_RELAY_BASE` L160；ring buffers L169–170；`_obs_get` L184–191；`_poll_observ_once` L194–228（GPU 历史改造点）；`_start_observ_poller` L231–236；`_gpu_df` L243–251；`_status_block` L264–272；`_fmt_metrics` L276–312（阈值 L293 / 全局行加在此 lines 列表）；`_fmt_lora` L315–330；`_fmt_gpu` L333–346；LinePlot L554–561；timer L584–592。
