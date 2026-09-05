# ScrewShell · TTFT 数据拆解（P0 分析任务书）— 执行 Agent 专用

> 执行者：HY3。本文档自包含：决策溯源、5 问目标、数据源、执行流程（A0→D，含实例命令/SQL 草稿）、统计口径、交付物、约束。
> 生成：2026-08-05（用户 02:00 拍板「先做 P0」，任务书交 HY3）。
> 前置结论（V2 真机，2026-08-05 01:55）：**decode ~30 tok/s 健康，真慢因是 TTFT≈27s**（131072 ctx prefill + 换帽 reprefill + 排队）。本任务＝用已有 observ 数据把这 27s **拆开看构成**，不直接改码。
> 关联：`docs/E2E_OPTIMIZATION.md` §8 ②（TTFT 零优化叙事盲点）；`bench/kv_reprefill_report.md`（T10：换帽 100% 毁 KV +2.35s）。

---

## 0. 决策溯源（为什么是「分析」不是「加埋点」）

- 01:55 联网研究已确认：observ DB **已有** `ttft_ms / queue_wait_ms / switch_ms / prefill_ms / decode_tps / kv_hit_rate / prompt_tokens` 字段 → **SQL 零成本拆解 27s 构成**，无需先写新埋点（那是后续观测台增强，非 P0）。
- 用户 02:00 拍板：**先做 P0（数据拆解）→ 产出本报告任务书 → 执行出 `TTFT_BREAKDOWN_REPORT.md`**，再据结论决定 P1 参数调优（ctx/batch/KV 量化/cache-reuse）。
- ⚠️ 本文件**不是**代码施工方案。若日后要做「观测台实时分解面板（prefill_client_ms + overhead_ms 端到端分量）」，那是单独的 `TTFT_INSTRUMENTATION_PLAN.md`，不在本次范围。

---

## 1. 目标与 5 问

用实例真实请求数据，直答 5 问（看**分布** p50/p90，不看单条极端值）：

| # | 问题 | 直接产出 | 决定什么 |
|---|---|---|---|
| Q1 | TTFT 构成：排队 / 切换 / Prefill(服务端) / 残留(传输开销) 各占多少？ | 四分量均值+p90 占比 | 27s 到底卡在哪一环 |
| Q2 | 换帽代价：switched=true vs false 的 `prefill_ms` 对比 | 两组 prefill 均值/中位差 | 验证 T10（+2.35s re-prefill）；是否该减切换 |
| Q3 | `prompt_tokens` p50/p90/max | 真实 prompt 分布 | 131072 ctx 是否过度 → ctx 收敛目标 |
| Q4 | `kv_hit_rate` 分布（按请求/按 switched 分组） | 命中率直方图 | `--cache-reuse` 收益评估 |
| Q5 | decode 矛盾：真机 ~30 vs 旧 17.5–19.7 的场景差异 | 场景归因 + 阈值建议 | 阈值已改 ≥20（v16），确认是否够 |

---

## 2. 数据源与前置

- **唯一真实数据源**：实例 `/workspace/persistent/screwshell_run/observ/requests.db`（SQLite，`request_events` 表）。
- 本机无 `OBSERV_DIR` → 无真实数据，**必须上实例查**。
- ⚠️ **SSH 前置（第一道门）**：实例 2026-08-04 被重置 → **host key 变 + publickey 被拒**。需先把本机 `~/.ssh/id_ed25519.pub`（注释 `djb-radeon-hackathon`）重新加回服务端 `~/.ssh/authorized_keys`，否则连不上。连不上立即回报，不要硬试。
- 实例环境：`/opt/venv/bin/python`（Python 3.x，含 stdlib `sqlite3`/`statistics`，**禁 pip**）。

---

## 3. 执行流程（A0 → D）

### A0. SSH 连通性（第一道门）
```bash
# 本机试连（先清掉旧 host key 缓存避免 mismatch 阻断）
ssh-keygen -R "[36.150.116.206]:31010" 2>/dev/null
ssh -p 31010 -o ConnectTimeout=8 root@36.150.116.206 'echo OK; hostname'
```
- 不通 → 回报「SSH 不可达，需先恢复公钥信任」并**停在此步**，不要猜。
- 通 → 进入 B。

### B. 实例侧 dump（stdlib，零依赖）
```bash
ssh -p 31010 root@36.150.116.206 'cat > /tmp/ttft_dump.py <<"PY"
import sqlite3, json, statistics as st
from pathlib import Path
db = "/workspace/persistent/screwshell_run/observ/requests.db"
if not Path(db).exists():
    print(json.dumps({"error": "no requests.db"})); raise SystemExit
con = sqlite3.connect(db); con.row_factory = sqlite3.Row
rows = con.execute("SELECT ts, route, adapter, switched, ok, error, "
    "ttft_ms, queue_wait_ms, switch_ms, prefill_ms, decode_ms, "
    "decode_tps, kv_hit_rate, prompt_tokens, cached_tokens, "
    "completion_tokens FROM request_events").fetchall()
def pct(xs, p):
    xs = sorted(x for x in xs if x is not None)
    if not xs: return None
    k = max(0, min(len(xs)-1, int(round((p/100)*(len(xs)-1)))))
    return xs[k]
def stat(name, xs):
    xs = [x for x in xs if x is not None]
    if not xs: return {name: None}
    return {name: {"n": len(xs), "mean": round(st.mean(xs),2),
                   "median": round(st.median(xs),2),
                   "p90": pct(xs,90), "max": round(max(xs),2)}}
out = {"total_rows": len(rows)}
# Q1: TTFT 构成
ttft=[r["ttft_ms"] for r in rows]
qw=[r["queue_wait_ms"] for r in rows]
sw=[r["switch_ms"] for r in rows]
pf=[r["prefill_ms"] for r in rows]
out["Q1_ttft_composition"] = {
    **stat("ttft_ms", ttft), **stat("queue_wait_ms", qw),
    **stat("switch_ms", sw), **stat("prefill_ms", pf),
    "residual_mean_ms": round((st.mean(ttft)-st.mean(qw)-st.mean(sw)-st.mean(pf)),2)
        if ttft and qw and sw and pf else None}
# Q2: 换帽代价
sw_on=[r["prefill_ms"] for r in rows if r["switched"] and r["prefill_ms"] is not None]
sw_off=[r["prefill_ms"] for r in rows if (not r["switched"]) and r["prefill_ms"] is not None]
out["Q2_switch_cost"] = {**stat("prefill_ms_switched_on", sw_on),
                         **stat("prefill_ms_switched_off", sw_off),
                         "delta_mean_ms": round(st.mean(sw_on)-st.mean(sw_off),2)
                             if sw_on and sw_off else None}
# Q3: prompt_tokens 分布
pt=[r["prompt_tokens"] for r in rows if r["prompt_tokens"]]
out["Q3_prompt_tokens"] = {**stat("prompt_tokens", pt), "p50": pct(pt,50)}
# Q4: kv_hit_rate 分布
kv=[r["kv_hit_rate"] for r in rows if r["kv_hit_rate"] is not None]
kv_on=[r["kv_hit_rate"] for r in rows if r["switched"] and r["kv_hit_rate"] is not None]
kv_off=[r["kv_hit_rate"] for r in rows if (not r["switched"]) and r["kv_hit_rate"] is not None]
out["Q4_kv_hit"] = {**stat("kv_all", kv), **stat("kv_switched_on", kv_on),
                    **stat("kv_switched_off", kv_off)}
# Q5: decode 分布
out["Q5_decode_tps"] = stat("decode_tps", [r["decode_tps"] for r in rows])
out["decode_contradiction_note"] = ("真机经 relay ~30 vs 旧验证 17.5-19.7："
    "差异来自长上下文/测量窗口，非稳态；阈值已改 floor-only >=20(v16)")
print(json.dumps(out, ensure_ascii=False, indent=2))
PY
/opt/venv/bin/python /tmp/ttft_dump.py'
```
- 把输出**落盘两份**：实例 `/workspace/persistent/screwshell_run/observ/ttft_dump.json` + 本机 `D:\AI\git\screwshell\bench\ttft_dump.json`（scp 拉回）。

### C. 5 问统计分析（本机或实例均可，读 json）
- 直接基于 B 的 json 解读，必要时补：`switched` 分组下 `ttft_ms` 对比、`adapter` 维度 `prefill_ms` 对比（哪个专家换帽最贵）。
- 残差 `residual = ttft − (queue+switch+prefill_server)`：正值＝relay↔llama.cpp 传输/调度/SSE 帧开销；若异常大需记一笔（指向后续 instrumentation 的 overhead 分量）。

### D. 报告落盘 + 本地副本
- 实例 + 本机各一份 `TTFT_BREAKDOWN_REPORT.md`（结构见 §5）。
- 结论必须**带数字 + 分布**，不写「大概」「可能」。

---

## 4. 统计口径（铁律）

- **看分布不看单条**：用 mean/median/p90/max，剔除 `ok=0`/`error` 行（失败请求 latency 无意义）。
- `ttft_ms` 仅流式路径有值，非流式为 `None` → 分析只用流式样本，注明样本数。
- 残差可能为负（测量抖动 / server clock vs client clock 漂移）→ 标注「±抖动」，不为负残差编故事。
- 禁 pip、禁改实例任何运行进程；只读 DB。

---

## 5. 交付物：`TTFT_BREAKDOWN_REPORT.md` 结构

1. **执行摘要**：27s 主要卡在哪一环（一句话结论）。
2. **Q1 TTFT 构成**：四分量均值/p90 占比表 + 残差解读。
3. **Q2 换帽代价**：switched on/off 的 prefill 对比 + 与 T10（+2.35s）交叉验证。
4. **Q3 prompt 分布**：p50/p90/max → ctx 收敛建议（131072 是否砍）。
5. **Q4 KV 命中**：分布 + switched 分组 → `--cache-reuse` 收益判断。
6. **Q5 decode 矛盾**：场景归因 + 阈值确认（≥20 够不够）。
7. **P1 参数建议**（基于以上）：ctx-size / batch / `--cache-type-k v q8_0` / `--cache-reuse` / `-fa` 的取舍与预期收益区间。
8. **附录**：dump json 路径、样本数、命令复现。

---

## 6. 约束与风险

- **只读、禁 pip、不动 llama-server / relay / UI 进程**。
- **SSH 是第一道门**：不可达立即回报，不猜测、不硬试（避免 lockout）。
- 实例可能已被重置清掉 `/workspace/persistent/screwshell_run`（工作记忆提示「重装很可能清掉」）→ 若 `requests.db` 不存在，回报「无历史数据」，改走**当场制造样本**（临时起 relay + 发几条请求落库）后再 dump，或标记 P0 暂不可执行。
- 不落结论到 TRUTH/代码，除非用户后续要求。

---

## 7. 验收（全部达成才算完工）

- [ ] A0 SSH 可达（或如实回报不可达并停下）
- [ ] `requests.db` 存在且 dump 成功（实例 + 本机各一份 json）
- [ ] 5 问全部有分布数字（mean/median/p90 + 样本数），无「大概」
- [ ] Q2 与 T10 交叉验证有结论；Q3 给出 ctx 收敛建议；Q4 给出 cache-reuse 收益判断
- [ ] `TTFT_BREAKDOWN_REPORT.md` 落盘（实例 + 本机）
- [ ] P1 参数建议具体（带预期收益区间，不空谈）
- [ ] 全程只读、零 pip、零进程改动
