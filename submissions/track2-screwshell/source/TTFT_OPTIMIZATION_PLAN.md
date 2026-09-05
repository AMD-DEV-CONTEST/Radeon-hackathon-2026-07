# 观测台 P0.5 + P1 — schema 迁移修复 + TTFT 参数调优 任务书（执行 Agent 专用）

> 执行者：HY3。自包含文档。前置：`TTFT_BREAKDOWN_REPORT.md`（P0 结论：长尾巨 prompt prefill 主导 27s 均值；DB 缺 queue/switch 列）。
> 生成：2026-08-05。

---

## 0. 背景与目标

**P0 结论**（已审阅）：TTFT 中位 1.66s 健康，长尾（p90 88.8s / max 172s）由少数巨 prompt（≤63k token）的 prefill 主导（占 ~97%）。杠杆 = 让长 prompt prefill 变快。

**本任务两步**：
- **P0.5（先做，P1 回测的前提）**：修 `store.py` 无 schema 迁移的 bug——实例 `request_events` 表缺 `queue_wait_ms`/`switch_ms` 列（PRAGMA 已确认），`_COLS` 演进后旧表缺列 → `record()` INSERT 列数不匹配**静默失败** → 新事件不落库（只进内存 ring、重启丢）。不修它，P1 重启后的回测无数据。
- **P1（后做）**：llama-server 参数调优（`-fa` + KV q8_0 + ctx 收敛 + parallel 降）→ llama-bench sweep 选参 → **一次性重启** → 用同款大 prompt 回测长尾 TTFT 收敛。

## 1. 硬约束

- 只改：`screwshell/observ/store.py`（迁移）、部署脚本（`deploy/w7900/run_roomy_server.sh` / `llama-swap-managed.yaml` / `run_gateway.sh`）、新增/更新测试。
- **不动**：`coordinator` / `orchestrator` / `event.py` / `relay.py` / 路由。schema 迁移只在 store 层。
- **llama-server 只重启一次**（P1 那次，低峰期，保留原命令快照回滚）。
- 零新依赖（stdlib 够）；实例离线禁 pip；测试本机受管 venv 跑（重定向文件，勿管道）。

---

## 2. P0.5 · store schema 迁移修复

### 2.1 代码（`screwshell/observ/store.py`，`_open` 内 L76 后、L77 预热前插入）

```python
# ---- schema migration: older DBs lack columns added after table creation ----
# CREATE TABLE IF NOT EXISTS never alters an existing table, so a DB created
# before a _COLS addition stays missing that column and every record() INSERT
# fails silently (best-effort try/except). Diff expected vs actual and add the
# missing columns so events persist again. Generic: any future _COLS column
# is auto-migrated, no hardcoding.
existing = {r[1] for r in
            self._conn.execute("PRAGMA table_info(request_events)")}
for c in _COLS:
    if c not in existing:
        t = ("TEXT" if c in ("request_id", "run_id", "route", "adapter",
                             "model", "error") else "REAL")
        try:
            self._conn.execute(
                f"ALTER TABLE request_events ADD COLUMN {c} {t}")
        except Exception:  # noqa: BLE001 - best-effort migration
            log.warning("schema migration failed for column %s", c)
self._conn.commit()
```

> ⚠️ SQLite `ADD COLUMN` 对已有行填 NULL——旧行的新列值为 NULL，`recent()`/`summarize()` 的 `_avg` 会跳过 None，不破坏旧数据。`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 需要 SQLite ≥3.35（Python 3.13 自带满足），但用 PRAGMA diff 写法更稳（兼容旧 SQLite）。

### 2.2 测试（`tests/test_observ_gpu.py` 追加或新增 `tests/test_store_migration.py`）

- **旧 schema 迁移**：手工 `CREATE TABLE request_events`（**故意缺 `switch_ms`**，用 20 列旧版）→ `_open` → PRAGMA 确认 `switch_ms` 已加 → `record()` 一个带 `switch_ms` 的事件 → SQLite 里查到该行且 `switch_ms` 有值。
- **幂等**：对已迁移的 DB 再 `_open` 一次不报错、不加重复列。
- **不回归**：现有 18 个（test_switch_ms ×6 + test_observ_gpu ×12）全过；全量 ≥257。

### 2.3 实例核实 + 部署（先于 P1）

```bash
ssh -p 31010 root@36.150.116.206 "
  python3 -c \"import sqlite3;c=sqlite3.connect('/workspace/persistent/screwshell_run/observ/requests.db');print('max_ts',c.execute('SELECT max(ts) FROM request_events').fetchone());print('count',c.execute('SELECT count(*) FROM request_events').fetchone())\"
  "
```
- 记录 `max(ts)` 与当前时间对比：若停在 V2 部署前 → **INSERT 静默失败已生效**（写进报告）；若在 V2 后仍在增长 → 说明实例 DB 是 V2 后新建的（那缺列另有原因，也写进报告）。
- scp `store.py`（+ 测试）到实例 → 重启 relay（环境变量照 HANDOFF §6）→ 发一个真实请求 → `SELECT count(*)` 增长 + 新行含 `switch_ms` 非空 → **P1 回测的数据管道就绪**。

---

## 3. P1 · llama-server 参数调优（一次重启）

### 3.1 第一步：llama-bench sweep（实例，选参不拍脑袋）

```bash
LLAMA=/opt/llama.cpp/build/bin/llama-bench
# 基线（现状：无 -fa、FP16 KV）vs 目标（-fa + q8_0 KV），ubatch 扫描
$LLAMA -m /workspace/persistent/screwshell_run/models/Qwen3.6-27B-Q4_K_M.gguf \
  -p 2048 -n 128 -ngl 999 -b 1024 \
  -ub 128 256 512 1024 -ctk f16 -ctv f16          # 基线
$LLAMA -m ... -p 2048 -n 128 -ngl 999 -b 1024 \
  -ub 128 256 512 1024 -ctk q8_0 -ctv q8_0 -fa on # 目标
```
- 读 `prompt_per_second`（prefill 吞吐）与 `tokens_per_second`（decode），两轮对比 → 选出 ubatch 最优值 + 确认 `-fa`/q8_0 收益。
- 若实例 `llama-bench` 不存在（路径变了），`find /opt -name llama-bench` 找；实在没有就跳过 sweep，参数按已知安全值（-fa + q8_0 + ub 512），并在报告注明"未 sweep"。

### 3.2 第二步：参数变更（3 个部署脚本 + 现网 llama-server 命令同步）

| 参数 | 现值 | 改为 | 理由（P0 报告） |
|---|---|---|---|
| `--flash-attn` | 未开 | **`on`** | 长 prompt prefill 降 30–50%，直接削 Q1 长尾 |
| `--cache-type-k/v` | 默认 f16 | **`q8_0`** | KV 显存减半、困惑度 +0.05 忽略不计，给 prefill 腾显存 |
| `--ctx-size` | 131072 | **98304** | 真实 max=63k，留 35k 余量；次要杠杆 |
| `--parallel` | 4 | **2** | coordinator 串行锁实际单请求，4 slot KV 显存浪费；留 2 保 slots 面板 |
| 保留 | | `--reasoning-budget 4096`、`--threads 24`、`--n-gpu-layers 999`、`--lora 预载`、`--jinja`、`--metrics` | reasoning 决策（P0 阶段已定保持现状） |

> ⚠️ 部署脚本与现网 llama-server **必须一致**（改脚本是给下次重启用的，本次重启可以直接带新参数起，也可以 scp 脚本后按脚本起——选一种并保证一致）。**保存原启动命令快照**（`cp` 一份原脚本或记下原 argv）回滚用。

### 3.3 第三步：重启 + 回测

1. 低峰期重启 llama-server（2–3 分钟加载 + 全 KV 失效，期间 opencode/UI 不可推理）。
2. `/metrics` 仍 200（`--metrics` 保留，别丢）。
3. **长尾回测**：用 P0 里 TTFT 最长的同款大 prompt（30k–63k token，可从 `bench/ttft_dump.json` 或 DB 里挑 max 样本的 prompt 特征重现——重发 3–5 个 30k+ 的请求）：
   ```bash
   curl -s -X POST http://127.0.0.1:8080/v1/chat/completions -H "Content-Type: application/json" \
     -d '{"model":"m","messages":[{"role":"user","content":"<30k+ token 长文>"}],"max_tokens":16,"stream":true}' \
     | grep -o "ttft_ms[^,]*\|prompt_ms[^,]*" | head
   ```
   - 对比优化前后：TTFT / prefill_ms 的 p50/p90/max（**修复 schema 后事件带 prefill_ms/ttft_ms，可直接从 DB 取**）。
4. 顺带确认：`kv_hit_rate` 是否变化（q8_0 KV + cache 行为）、decode_tps 无回退（≥20 阈值不误报）。

---

## 4. 输出与验收

### 4.1 交付物
- `TTFT_OPTIMIZATION_REPORT.md`（仓库根 + 实例各一份）：
  - P0.5：max(ts) 核实结论、迁移代码、测试结果、修复后新事件落库证据
  - P1：llama-bench 对比表、参数变更清单（改动前后）、重启后长尾回测对比（同 prompt 前后 TTFT p50/p90/max）、decode 无回退确认
  - 明确写：如果 `-fa` 不可用/收益不达预期（llama-bench 数据说话），参数保持或回滚，报告注明原因
- 代码改动（store.py 迁移 + 测试）+ 部署脚本改动
- TRUTH.md §3 基线 + **v17** changelog（测试数 257 → 257+N）

### 4.2 验收清单
- [ ] P0.5：本地旧-schema 迁移测试过 + 幂等 + 18 个既有测试不回归 + 全量 ≥257
- [ ] 实例：max(ts) 核实结论已记录；修复后真实请求事件落库且含 `switch_ms` 非空
- [ ] P1：llama-bench 数据表（或注明未 sweep 原因）；一次重启完成；`/metrics` 200 保留
- [ ] 长尾回测：同款大 prompt 前后 TTFT 对比有数据（有改善或注明未改善）
- [ ] decode 无回退（中位 ≥20 不误报）；`--reasoning-budget 4096` 保留
- [ ] 三道闸：本机全量 pytest（重定向文件）+ `verify_bugfixes.py` EXIT=0 + `git fsck` 无 missing
- [ ] TRUTH v17 已更新；全程零新依赖、未动 coordinator/orchestrator/event/relay

---

## 5. 边界与风险

- **P1 重启是唯一中断点**：挑低峰期；原命令快照在手；任何异常立即用原命令回滚（只影响 llama-server，不影响 relay/UI/代码）。
- **`-fa` 在 ROCm/W7900 的支持**：llama-bench 先验证，不支持就只上 q8_0 KV（收益仍大），报告注明。
- **`--cache-reuse` 本轮不上**（P0 报告明确：Qwen3.6 hybrid 冲突、先受控验证）——P1 只做上表 4 项。
- **回测用真实长 prompt**：别用短 prompt 测（那本来就健康），长尾不收敛就是没效果，诚实写。
- 实例 SSH 不可达 → 第一道门先测，连不上立即回报（参照前任务 A0 流程）。

## 6. 附：关键行号

- `store.py`：`_open` L58–98（迁移插 L76 后）；`_COLS` L29–35；`record` L130–161。
- 部署脚本：`run_roomy_server.sh`（llama-server 段）、`llama-swap-managed.yaml`（L38–42 命令段）、`run_gateway.sh`（cli `--metrics` 已有，参数在 config 侧）。
- 测试：`tests/test_observ_gpu.py`（追加）或新 `tests/test_store_migration.py`。
