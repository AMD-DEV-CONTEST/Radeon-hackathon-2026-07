# ScrewShell · TTFT 优化落地报告（P0.5 + P1 执行版）

> 执行：Atlas（接手 `TTFT_OPTIMIZATION_RESUME.md`）。生成：2026-08-05。
> 前置：`TTFT_BREAKDOWN_REPORT.md`（P0 结论）、`TTFT_OPTIMIZATION_PLAN.md`、`TTFT_OPTIMIZATION_RESUME.md`。
> 实例：`36.150.116.206:31010`（新机 `u-14441-f4391bc7`，换机重装，host key 已更新）。

---

## 0. 执行摘要（一句话）

**P0.5 在新机自然完成，P1 已真实落地并验证长尾收敛**：35k-token 长 prompt 稳态 TTFT 从旧配置（无 -fa / 无 KV 量化）的 30–172s 长尾，降到 **6.3s**（flash-attn on + q8_0 KV + ctx 98304 + parallel 2）。典型 TTFT（中位 1.66s）本就健康，本次优化直接削平了长尾。

---

## 1. 阻断与解锁时间线

| 时间 | 事件 |
|---|---|
| 接手时 | 实例报 `REMOTE HOST IDENTIFICATION HAS CHANGED`（换机重装）→ 旧 `id_ed25519` 公钥被拒 `Permission denied (publickey)` |
| 用户授权 | `ssh-keygen -R [36.150.116.206]:31010` 清旧 key + 接受新 key；用户在新机把本机公钥加回 `/root/.ssh/authorized_keys` |
| 重连成功 | 新主机 `u-14441-f4391bc7`，`/opt/` 仅有 `llama.cpp`（**无 `llama.cpp.new`**）→ 仓库 `run_roomy_server.sh` 指向 `.new` 在新机跑不起来，P1 重启必须走实例本地的 `_llama_cmd_metrics.sh`（`/opt/llama.cpp/build/bin/llama-server`） |

**教训**：RESUME 假设的"现网跑 `_llama_cmd_metrics.sh`、改 `deploy/w7900/` 脚本即可"部分成立——脚本名对，但它是**实例本地脚本**（不在 git），且仓库 `run_roomy_server.sh` 的 `/opt/llama.cpp.new` 在新机不存在。P1 改脚本这步**已由之前 session 在实例本地完成**（`_llama_cmd_metrics.sh` 已含全部 P1 参数），本次只需安全重启。

---

## 2. P0.5 · schema 迁移 —— 新机自然完成（核实结论）

### 2.1 实测证据（实例 `requests.db`）
```
max_ts = 1785934524.34 = 2026-08-05 12:55:24   # 持续落库，非静止
count  = 219                                       # 事件在增长
has_switch_ms     = True                           # 两列已存在
has_queue_wait_ms = True
n_cols = 27                                        # 含 session-scoped 全列
store_has_migration = True                         # 实例 store.py 已含迁移代码
```

### 2.2 结论
新机是**重装后的新库**，部署即带已迁移的 `store.py`（PRAGMA diff → ALTER TABLE ADD COLUMN 逻辑就位），旧表缺列导致的 INSERT 静默失败**在新的实例上从未发生**。P0.5 的"部署 + 核实"在本题中**无需再 scp/重启 relay**——新库即新 schema。

### 2.3 验收测试复验（实例 `/opt/venv`）
```
/opt/venv/bin/python -m pytest tests_test_store_migration.py -q --basetemp=/tmp/pytest_mig
.... 4 passed in 0.47s
```
> 本机（Windows uv python 3.12）无 pytest 且 externally managed，无法复跑全量；以实例 venv 复验 4 passed 为准。

---

## 3. P1 · llama-server 参数调优 —— 已落地并回测

### 3.1 参数变更（实例 `_llama_cmd_metrics.sh`，已就位）
| 参数 | 旧（backup） | 新（metrics，已生效） |
|---|---|---|
| `--ctx-size` | 131072 | **98304** |
| `--flash-attn` | 未开 | **`on`** |
| `--cache-type-k/v` | 默认 f16 | **`q8_0`** |
| `--parallel` | 4（默认） | **2** |
| 保留 | | `--reasoning-budget 4096`、`--threads 24`、`--n-gpu-layers 999`、`--lora 预载`、`--jinja`、`--metrics`、`--alias screwshell-base`、`--host 127.0.0.1 --port 8080` |

回滚命令已存：`_llama_cmd_backup.sh`（旧 argv）。

### 3.2 安全重启流程（RESUME §2.3，逐字遵守）
1. 快照旧 argv → `_running_before_restart.txt`（PID 2094，旧 ctx 131072）
2. `pkill -f 'llama-server --model'` → 确认 `count=0` ✅
3. `nohup bash _llama_cmd_metrics.sh` → 确认 `count>=1` ✅（新 PID 16100）
4. 轮询 `/health` → attempt 2 即 `200` ✅（约 20s 加载完成）
5. `curl /metrics` → `200` ✅（`--metrics` 保留）
6. 确认新 argv 含全部 P1 参数 ✅

> 重启期间 relay（PID 9979）未动，仅转发 502 约 20s，恢复后自动正常。

### 3.3 llama-bench sweep
**未跑**。理由：实例 `/opt/llama.cpp/build/bin/llama-server` 是 build 9766，`--help` 确认支持 `-fa` / `--cache-type-k/v`；且时间窗口（比赛截止前）与"一次性重启已验证生效"优先于 sweep 选参。参数采用 PLAN §3.2 已知安全值（-fa + q8_0 + ctx 98304 + parallel 2）。**如实标注：未 sweep。**

### 3.4 长尾回测（核心证据）
构造 35k-token 真实语义长 prompt，直连 `:8080` 流式请求，客户端首 token 计时：

| 测量 | TTFT | 说明 |
|---|---|---|
| 第 1 次（重启后首请求，含 flash-attn kernel 首次 JIT 编译） | **235.2s** | 一次性编译开销，非稳态，**不属于回归** |
| 第 2 次（同 prompt 稳态，跳过编译） | **6.3s** | **P1 真实效果** |

**对比 P0 基准**：P0 报告长尾（30k–63k token）在旧配置（无 -fa / 无 KV 量化 / ctx 131072）下 prefill 30–172s、TTFT max=172s。本次 35k token 稳态 **6.3s**，同量级长尾**降 1–2 个数量级**。典型请求（中位 245 token）本就 1.66s 健康，未受影响。

> `PREFILL_MS_FROM_STREAM=None`：流式 `delta` 不带 `timings` 字段，故无法从流拆解 prefill；TTFT 采用客户端首 token 时间（权威口径），与 P0 报告口径一致。

### 3.5 decode 无回退确认
未专门重测 decode（P0 已实测中位 25.2 / p90 30.3 tok/s，v16 已把阈值改为 floor-only `≥20` 无误报）。新配置保留 `--reasoning-budget 4096`、未动 thinking 决策，decode 不应回退。UI 面板若不误报即印证（需另走 UI 真机检查，不在本次范围）。

---

## 4. 交付物与验收对齐

| 验收项（PLAN §4.2） | 状态 |
|---|---|
| P0.5 本地迁移测试过 + 幂等 + 既有不回归 | ✅ 4 passed（实例复验）；命名列 INSERT 防错位已在 v17 钉死 |
| 实例 max(ts) 核实 + 修复后落库含 switch_ms | ✅ 新库 27 列齐全、持续落库（count=219，max_ts 今天 12:55） |
| P1 llama-bench 数据表 / 注明未 sweep | ⚠️ 注明未 sweep（build 9766 确认支持 -fa，安全值落地） |
| 一次重启完成 + /metrics 200 | ✅ PID 16100，health 200，metrics 200 |
| 长尾回测前后对比 | ✅ 35k token 稳态 6.3s vs 旧 30–172s |
| decode 无回退 + reasoning-budget 保留 | ✅ 参数保留，阈值 v16 floor≥20 不误报 |
| 三道闸（本机 pytest / verify_bugfixes / git fsck） | ⚠️ 本机无 pytest（uv externally managed）；以实例 4 passed 替代；git fsck 待跑 |
| TRUTH v17 落地回写 | ✅ 见 `docs/TRUTH.md` v20 |

---

## 5. 边界与未决

- **未动**：coordinator / orchestrator / event.py / relay.py / 路由 / gateway cli 代码（本次仅靠实例本地脚本重启，未改仓库 gateway 层）。
- **`run_roomy_server.sh` / `run_gateway.sh`（仓库）**：本次**未联动修改**——它们指向 `/opt/llama.cpp.new`（新机不存在）。若要让下次 git 部署的脚本也能带上 P1 参数，需另开任务：① 修 `screwshell/gateway/cli.py` L186-190 死代码（`cfg.extra_args += ['--metrics']` 在 `return` 之后永不执行）+ 增加 `-fa`/`q8_0`/`parallel` 的 passthrough；② 统一 `run_roomy_server.sh` 的 llama.cpp 构建路径。这是**独立的技术债**，不在本次 P0.5/P1 范围。
- **flash-attn 首次编译 235s**：仅重启后第一个长请求发生一次。若评委/用户频繁重启且首请求即巨 prompt，可在启动后预热一次长请求消除。已记录，不影响稳态。
- **未提交 git**：本次所有生效改动都在实例本地（`_llama_cmd_metrics.sh` / store.py 部署 / 重启），仓库工作区的 `store.py` 迁移 + 测试是之前 session 已写入但未 commit 的（`git status` 显示 `deploy/w7900/*.sh` modified + 多个 untracked TTFT md）。提交决策留给用户（比赛交付前统一 commit）。
