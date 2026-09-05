# TTFT_OPTIMIZATION 续做任务书（HY3 接手版）

> 你上次执行 `TTFT_OPTIMIZATION_PLAN.md` 时**卡在 P1 重启**：停了 llama-server 后新进程没起来（ps 无进程、8080 无监听、relay 转发全 502），导致全栈推理中断。**已由主会话救火恢复**。本文档 = 状态快照 + 剩余步骤 + 重启安全流程（吸取教训）。完整计划细节见 `TTFT_OPTIMIZATION_PLAN.md`。
> 生成：2026-08-05 03:16。

---

## 0. 当前状态快照（执行前必读）

| 项 | 状态 |
|---|---|
| llama-server | ✅ **已恢复**：PID 52559，命令 = `_llama_cmd_metrics.sh`（V2 生产版：`--metrics`、alias screwshell-base、ctx 131072、**无 -fa / 无 KV 量化**）。8080 /health=200、relay /health ok。**勿重复启动** |
| relay / ui | ✅ 在跑（全程未挂），relay 转发已随 llama-server 恢复 |
| P0.5 代码 | ✅ **已写好未部署**：`store.py` 通用 schema 迁移（PRAGMA diff → `ALTER TABLE ADD COLUMN`）+ 命名列 INSERT + `_COLS` 补 `queue_wait_ms`；`tests/test_store_migration.py`（本地 **4 passed**） |
| P1 | ❌ 未开始：llama-bench 没跑、参数未改 |

---

## 1. P0.5 剩余（部署 + 核实，先做）

1. scp `screwshell/observ/store.py` + `tests/test_store_migration.py` 到实例：
   ```bash
   scp -P 31010 screwshell/observ/store.py root@36.150.116.206:/workspace/persistent/screwshell_run/screwshell/observ/
   scp -P 31010 tests/test_store_migration.py root@36.150.116.206:/workspace/persistent/screwshell_run/tests/
   ```
2. **核实 max(ts)**（确认 INSERT 静默失败是否曾生效）：
   ```bash
   ssh -p 31010 root@36.150.116.206 "python3 -c \"
   import sqlite3, datetime
   c = sqlite3.connect('/workspace/persistent/screwshell_run/observ/requests.db')
   m = c.execute('SELECT max(ts) FROM request_events').fetchone()[0]
   print('max_ts =', m, '=', datetime.datetime.fromtimestamp(m))
   print('count =', c.execute('SELECT count(*) FROM request_events').fetchone()[0])
   \"" 
   ```
   结论写进报告：max_ts 是否停在 V2 部署前（是 → INSERT 曾静默失败；否 → 实例 DB 是 V2 后新建）。
3. 重启 relay（环境照 HANDOFF_OBSERVATORY.md §6：`MOL_BACKEND=llamacpp MOL_LLAMACPP_URL=http://127.0.0.1:18090 MOL_RELAY_MODE=1 RELAY_TRUST_TOKEN=screwshell-relay-devtoken OBSERV_DIR=/workspace/persistent/screwshell_run/observ`，`nohup /opt/venv/bin/python -m screwshell.gateway.relay > relay.log 2>&1 &`）。
4. 发一个真实请求（短 prompt）→ `SELECT count(*)` 增长 + 新行 `switch_ms`/`queue_wait_ms` 非空 → 数据管道就绪。
5. 实例跑迁移测试：`/opt/venv/bin/python -m pytest tests/test_store_migration.py -q`（`--basetemp=/tmp/...` 避开清理坑）。

---

## 2. P1（llama-server 唯一一次重启）

### 2.1 llama-bench sweep（选参，先跑）
```bash
LLAMA=/opt/llama.cpp/build/bin/llama-bench
$LLAMA -m /workspace/persistent/screwshell_run/models/Qwen3.6-27B-Q4_K_M.gguf \
  -p 2048 -n 128 -ngl 999 -b 1024 -ub 128 256 512 1024 -ctk f16 -ctv f16
$LLAMA -m ... -p 2048 -n 128 -ngl 999 -b 1024 -ub 128 256 512 1024 \
  -ctk q8_0 -ctv q8_0 -fa on
```
- 读 `prompt_per_second`（prefill 吞吐）对比 → 定 ubatch + 确认 `-fa`/q8_0 收益。llama-bench 找不到就 `find /opt -name llama-bench`；真没有 → 跳过 sweep 用安全值（-fa + q8_0 + ub 512）并在报告注明。
- **llama-bench 可能跑几分钟，务必后台/nohup + 等输出**，别前台挂死。

### 2.2 参数变更（4 项，改 `_llama_cmd_metrics.sh` + `deploy/w7900/` 3 个脚本保持一致）
| 参数 | 改为 |
|---|---|
| `--flash-attn on` | 加 |
| `--cache-type-k q8_0 --cache-type-v q8_0` | 加 |
| `--ctx-size 131072` | → `98304` |
| `--parallel`（默认 4） | → `2` |
| 保留 | `--reasoning-budget 4096 --threads 24 --n-gpu-layers 999 --lora 预载 --jinja --metrics --alias screwshell-base --host 127.0.0.1 --port 8080` |

### 2.3 ⚠️ 重启安全流程（上次卡点的教训，逐字遵守）
```bash
cd /workspace/persistent/screwshell_run
cp _llama_cmd_metrics.sh _llama_cmd_backup.sh          # 1) 快照（回滚用）
pkill -f 'llama-server --model' ; sleep 3
ps aux | grep llama-server | grep -v grep | wc -l        # 2) 必须输出 0，确认旧进程没了
nohup bash _llama_cmd_metrics.sh > llama_server.log 2>&1 &  # 3) 用【已改好新参数】的脚本启动
sleep 3
ps aux | grep llama-server | grep -v grep | wc -l        # 4) 必须 ≥1，确认新进程起来了
for i in 1 2 3 4 5 6; do                                 # 5) 轮询 /health（27B 加载 1-3 分钟）
  code=$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/health)
  echo "attempt $i: $code"; [ "$code" = "200" ] && break; sleep 30
done
curl -s -m 5 -o /dev/null -w 'metrics=%{http_code}\n' http://127.0.0.1:8080/metrics  # 6) 必须 200（--metrics 保留）
```
- **第 2 步没到 0 → 别启动新进程**；**第 4 步没到 ≥1 → 立即看 llama_server.log 排障**；**轮询 6 次没 200 → 用备份命令恢复**（`bash _llama_cmd_backup.sh`）。任何一步失败都**立即回报主会话**，不要自己反复试。

### 2.4 回测长尾（重启后）
- 从 `bench/ttft_dump.json` 或 DB 挑 max-ttft 样本的 prompt 特征，重发 3–5 个 **30k+ token** 长 prompt（`max_tokens:16`，流式），从 relay 事件（修复 schema 后落库）取 `prefill_ms`/`ttft_ms` → 与 P0 报告的长尾对比。
- 顺带确认 decode_tps ≥20 不误报（阈值 floor-only ≥20 别动）。

---

## 3. 交付物（收尾）

1. `TTFT_OPTIMIZATION_REPORT.md`（仓库根 + 实例）：P0.5 核实结论 + 迁移测试结果 + 修复后落库证据；P1 bench 对比表 + 参数变更前后 + 长尾回测对比 + decode 确认。
2. TRUTH.md：§3 基线更新（257 → 257+N）+ **v17** changelog。
3. 三道闸：本机全量 pytest（重定向文件、`--basetemp=/tmp/`）+ `verify_bugfixes.py` EXIT=0 + `git fsck` 无 missing。
4. 回复主会话：卡点已解除的证据 + 各步输出摘录。

---

## 4. 边界（再次强调）

- **别碰工作区的 V3 并行任务文件**：`BUILD_OBSERVATORY_V3.md`、`screwshell/ui/thresholds.py`、`tests/test_{ab_windows,config_snapshot,gov_events,percentile,thresholds,ui_build,ui_layout}.py`、以及 orchestrator/relay/app.py 里 V3 相关改动——**不是你的任务，别改别提交**。
- 只改：`store.py`（已改完）、部署脚本/`_llama_cmd_metrics.sh`、测试（已写完的迁移测试 + 若需）、报告。
- 不动：coordinator / orchestrator 核心 / event.py 语义 / 路由。
- llama-server **只重启一次**（2.3 那步）；本次已恢复的服务（PID 52559）在重启前保持运行。
- 零新依赖；实例离线禁 pip；测试本机受管 venv。
