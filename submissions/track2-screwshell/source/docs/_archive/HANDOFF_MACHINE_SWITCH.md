# HANDOFF_MACHINE_SWITCH — 换机交接（2026-08-04）

> 目的：从当前机器（Win，`C:\Users\dd`）切换到**另一台机器**，用**相同的 git 仓库**、连**相同的实例**继续开发。
> 本文件随仓库走（git 追踪），新机器 `git clone` 后直接可见。
> 所有事实经 2026-08-04 实例 + 仓库核实，非推测。

---

## 1. 核心拓扑（换机前先懂这个）

```
本地机器 ──SSH隧道──▶ 实例 root@36.150.116.206:31010
                          │
                          ├─ llama-server  :8080  (Qwen3.6-27B, --lora btl3,cybersec,rag_n7)
                          ├─ gateway.relay :18090 (ScrewShell MoL 中转网关)
                          └─ Gradio UI     :7860  (screwshell.ui.app)
```

**链路**：前端（opencode/pi/UI）→ ScrewShell 中转网关(relay :18090) → llama-server(:8080)。
**实例代码不是 git repo**，靠 scp/tar 同步，已确认 `cli.py` 与仓库 md5 一致（13a402f7...）。

---

## 2. 新机器首次要做的 5 件事

### 2.1 克隆仓库
```bash
git clone https://github.com/1105s110martin-art/screwshell.git
cd screwshell
```
> remote 是 **HTTPS**（非 SSH）。若 push 需凭据，配 credential helper 或改用 SSH remote。

### 2.2 加 SSH 公钥到实例（否则连不上）
实例 `authorized_keys` 现有 2 个 ed25519 公钥。把**新机器**的 `~/.ssh/id_ed25519.pub` 加进去：
```bash
# 新机器生成 key（若没有）
ssh-keygen -t ed25519
# 把新机器 pub key 追加到实例（用已授权的机器执行，或从新机器手动加）
ssh -p 31010 root@36.150.116.206 \
  "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '<新机器 pub key>' >> ~/.ssh/authorized_keys"
```
> 当前机器 pub key（旧）可保留。验证：`ssh -p 31010 root@36.150.116.206 "hostname"`。

### 2.3 确认实例三服务存活
```bash
ssh -p 31010 root@36.150.116.206
curl -s http://127.0.0.1:7860/ -o /dev/null -w "ui=%{http_code}\n"    # 期望 200
curl -s http://127.0.0.1:8080/health -o /dev/null -w "llama=%{http_code}\n"  # 期望 200
curl -s http://127.0.0.1:18090/health -o /dev/null -w "relay=%{http_code}\n" # 期望 200
```

### 2.4 建 SSH 隧道（看 UI / 直连 relay）
```bash
# 在你自己电脑开，保持开着
ssh -p 31010 -L 7860:127.0.0.1:7860 -L 18090:127.0.0.1:18090 root@36.150.116.206
# 然后浏览器 http://localhost:7860 看 UI
# opencode/pi 直连 http://127.0.0.1:18090/v1
```

### 2.5 本地 opencode 配置（直连用）
> ⚠️ **模型 id 陷阱（实测抓到）**：relay `/v1/models` 只暴露 **`screwshell-base`**（TRUTH v13 把 `gateway/config.py` 默认 alias 从 `m` 改为 `screwshell-base`，`m` 现在只是"未解析"哨兵）。照抄旧文档的 `m` 会连不上 relay。
> 本机 `opencode.json` 的 `screwshell` provider 已指 **:18090**（relay），模型 id 用 `screwshell-base`：
> ```json
> "baseURL": "http://127.0.0.1:18090/v1",
> "apiKey": "screwshell-relay-devtoken",
> "headers": { "X-Relay-Token": "screwshell-relay-devtoken" },
> "models": { "screwshell-base": { "name": "Qwen3.6 27B via ScrewShell relay" } }
> ```
> ⚠️ 需建隧道（2.4）后 127.0.0.1:18090 才通。新机器 `git clone` 后照抄上面即可直连；如不想带 `X-Relay-Token` header，去掉那行也行（chat 走 SkillRouter 关键词路由，不受影响）。

---

## 3. 当前状态（2026-08-04 核实）

### 3.1 仓库
- remote: `origin https://github.com/1105s110martin-art/screwshell.git`
- 分支: `main`，**全部已 push**（origin/main..HEAD 为空）
- 工作树: **clean**
- 最近提交（都含实例对应内容）：
  - `75ba3d5` fix(gateway): export OBSERV_DIR in run_gateway.sh
  - `ca70808` fix(gateway): propagate OBSERV_DIR/RELAY_TRUST_TOKEN/RELAY_LLAMA_URL
  - `6f5c987` fix(gateway): cache fit result + e2e evidence
  - `0940bbe` fix(gateway): reject invalid fit ngl + production-wired
  - `09e760c` feat(gateway): wire fit-derived ctx/ngl + run_gateway.sh

### 3.2 gateway 五层（全部落地 + 接入生产）
| 层 | 文件 | 状态 |
|---|---|---|
| 配置自动化 | `gateway/config.py` | ✅ `--jinja`/`--lora`逗号/`--reasoning-budget 4096`/ctx fit 真值 |
| 容量规划 | `gateway/capacity.py` | ✅ 优先调 `llama-fit-params`（27B+48GB→`-c 131072 -ngl 53`），失败回退 |
| 推理调度 | `gateway/thinking.py` | ✅ agentic OFF + 预算封顶 4096 |
| 可靠性 | `gateway/reliability.py` | ✅ 端口检测(/proc/net/tcp)+setsid |
| 编排 | `gateway/cli.py` | ✅ 一键 config→校验→daemon→health→relay；已接入生产 |

### 3.3 实例（root@36.150.116.206:31010）
- 代码目录：`/workspace/persistent/screwshell_run`（**是规范工作副本，实例非 git repo**）
- 三服务在跑：llama:8080 / relay:18090 / UI:7860 全 200
- **observ 已修复**：relay env 有 `OBSERV_DIR=/workspace/persistent/screwshell_run/observ`，`/v1/observ/summary` 返回 `enabled=true`，decode_tps/ttft/kv/MoL 路由实时积累
- 启动脚本：`run_gateway.sh`（经 `cli.py` 一键编排，替代手动 setsid）
- 回滚脚本：`_run_roomy_server.sh.bak2`（旧手动启动，可回滚）
- 专家：btl3 / cybersec / rag_n7 预载；teichai_plan 无权重降级 base

### 3.4 测试基线
- **230 passed / 0 failed**（GPU 实例 `/opt/venv` 实测）
- `scripts/verify_bugfixes.py` §8 机器断言 ≥200

---

## 4. 观测 / 性能数据从哪看

**UI**（隧道进 :7860）：右侧面板显示实时 decode TPS、TTFT、KV 命中、MoL 路由、GPU 占用（`rocm-smi`）。

**API 直查**：
```bash
# 摘要（性能聚合）
curl -s http://127.0.0.1:18090/v1/observ/summary -H "X-Relay-Token: screwshell-relay-devtoken"
# 最近事件（含 route/adapter/tps/kv/ttft）
curl -s "http://127.0.0.1:18090/v1/observ/events?n=20" -H "X-Relay-Token: screwshell-relay-devtoken"
# GPU 占用
curl -s http://127.0.0.1:18090/v1/observ/gpu -H "X-Relay-Token: screwshell-relay-devtoken"
```

---

## 5. 交接时已知待办 / 风险

### 已做（无需重做）
- ✅ MoL 热切换真机 PASS（中文路由 f01ce17 后）
- ✅ gateway 五层接入生产（cli 接管启动）
- ✅ observ OBSERV_DIR 修复（enabled=true）

### 待办 / 风险（换机后留意）
1. **opencode 直连已就绪**：本机 `opencode.json` 的 `screwshell` provider 已指 **:18090**（relay），模型 id 用 `screwshell-base`（见 §2.5，旧文档的 `m` 已作废）。新机器照抄 §2.5 即可，无需再改端口。
2. **`enable_thinking` 版本弃用坑**——llama.cpp 当前 9766 仍认 `chat_template_kwargs.enable_thinking`，但 ≥b8322 弃用（换 `--reasoning on/off`）。**升级 llama.cpp 前必须验证**，启动参数应固化 `--reasoning off` 未来-proof。
3. **`--fit` 只改未显式设置的参数**——设 `-ngl` 会旁路 fit。config 用 fit 输出（53），不硬编码 999。
4. **黑客松截止 2026-08-06 23:59(UTC+8)**，剩余待办（SUBMISSION_CHECKLIST）：SPEC 反向同步（173→230）、**录演示视频（须露 rocm-smi，关键路径）**、做 PPT、fork+PR。
5. **实例重启后 observ 依赖 run_gateway.sh 传 OBSERV_DIR**——别再用手动 `python -m screwshell.gateway.relay`（那会丢 OBSERV_DIR）。

---

## 6. 快速命令速查

```bash
# 连实例
ssh -p 31010 root@36.150.116.206
# 隧道（看 UI + 直连 relay）
ssh -p 31010 -L 7860:127.0.0.1:7860 -L 18090:127.0.0.1:18090 root@36.150.116.206
# 重启整栈（实例上，经 cli）
pkill -f llama-server; pkill -f gateway.relay; sleep 3
setsid bash /workspace/persistent/screwshell_run/run_gateway.sh > /tmp/gateway_restart.log 2>&1 &
# 同步仓库→实例（改代码后）
scp -P 31010 <仓库文件> root@36.150.116.206:/workspace/persistent/screwshell_run/<路径>
# 测试
cd <仓库> && pytest tests/ -q
```

---

## 7. 唯一信源提醒

- 技术真相：**`docs/TRUTH.md`**（唯一权威，已 v13 更新：gateway 五层落地 + 路由回归修复 + alias `m`→`screwshell-base` + 测试 230/observ 修复）。
- 交付物追踪：**`SUBMISSION_CHECKLIST.md`**（视频/PPT/PR 仍未做，截止 8/6）。
- 入口索引：根 `AGENT.md`。
- 代码永远是最低层事实；文档与代码冲突以代码为准。
