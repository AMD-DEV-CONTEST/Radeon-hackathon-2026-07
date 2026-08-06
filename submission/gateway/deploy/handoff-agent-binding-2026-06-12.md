# ECS 部署 Handoff — Agent Binding Contract 上线

> 日期：2026-06-12 | 来源：Reasonix（接手小寇任务） | 目标：老何 / 运维

## 背景

本次改动把 UAS 的 Agent 绑定机制从 "硬编码 switch-default → claude run" 升级为 Lark CLI 风格的 `config → bind → doctor → consume` 模式。核心变化：

- 新增 `internal/agent/binding.go` — 正式运行时注册表（reasonix / claude_code / codex / opencode / hermes）
- `generic` 和 `shell` 从 DB 约束、后端注册、前端入口三处彻底封死
- 未知 agent_type 不再静默 fallback 到 `claude run`，返回结构化错误给 OB
- Daemon 启动时自检 binding + doctor，注册时上报 `binding_status`

## 变更文件清单

| 文件 | 类型 |
|---|---|
| `internal/agent/binding.go` | **新增** |
| `cmd/ils/daemon.go` | 修改 |
| `internal/models/agent.go` | 修改（加字段） |
| `internal/orchestrator/handler_agents.go` | 修改（加字段+查询） |
| `deploy/schema.sql` | 修改（DDL） |

## 部署步骤

### Step 1: 代码同步 + 编译

```bash
cd /root/unionagents-go
git fetch origin
git checkout go-migration
git pull origin go-migration

# 编译全部
go build -o bin/orchestrator ./cmd/orchestrator
go build -o bin/gateway ./cmd/gateway
go build -o bin/ils ./cmd/ils
```

### Step 2: DB Migration（必须先跑，否则 orchestrator 报 column 不存在）

连 PostgreSQL 执行：

```sql
-- 新增 binding_status 列
ALTER TABLE public.agents ADD COLUMN IF NOT EXISTS binding_status text;

-- 更新 agent_type CHECK 约束（加 hermes，删 generic 和 codewhile）
ALTER TABLE public.agents DROP CONSTRAINT IF EXISTS agents_agent_type_check;
ALTER TABLE public.agents ADD CONSTRAINT agents_agent_type_check
  CHECK ((agent_type = ANY (ARRAY['claude_code'::text, 'codex'::text, 'reasonix'::text, 'opencode'::text, 'hermes'::text])));

-- 把现有 generic 类型的 agent 改成 hermes（如果存在）
-- 先查一下有哪些 generic：
-- SELECT id, name, agent_type FROM agents WHERE agent_type = 'generic';

-- 如果 JD-ECS 上的"老何"是 generic，改掉它：
-- UPDATE agents SET agent_type = 'hermes', binding_status = 'degraded' WHERE agent_type = 'generic';
```

### Step 3: 重启 Orchestrator + Gateway

```bash
systemctl restart ua-orchestrator
# Gateway 如果是 systemd 管理的也重启（可能名为 ua-gateway 或 unionagents-gateway）
systemctl restart ua-gateway 2>/dev/null || true
```

验证：
```bash
curl -s http://localhost:8000/health | jq .status
curl -s http://localhost:8001/health | jq .status
```

### Step 4: 更新 JD-ECS 上的 ILS Daemon

JD-ECS 上有三个 service：
- `hermes-gateway.service` → Hermes 本体（Python，不动）
- `unionagents-agent-scc.service` → SCC Claude Agent（不动）
- `unionagents-ils-daemon.service` → **老何连接位（需要更新）**

```bash
# 更新环境变量：AGENT_TYPE 不能再是 generic
# 如果这个 daemon 真的是"老何"（Hermes Agent），改成 hermes：
# AGENT_TYPE=hermes

# 如果这个 daemon 应该配成别的 agent，按实际改：
# AGENT_TYPE=reasonix   （如果是 Reasonix agent）
# AGENT_TYPE=claude_code（如果是 Claude Code agent）

# 编辑 service 文件
systemctl edit unionagents-ils-daemon --full
# 或直接改 /etc/systemd/system/unionagents-ils-daemon.service

# 确保 Environment 行：
# Environment="AGENT_TYPE=hermes"  （或其他正式类型）
# Environment="GATEWAY_PASSWORD=***"
# 删除 Environment="AGENT_TYPE=generic" 这行

# 重新编译 ILS（如果在 JD-ECS 本地编译）
cd /root/unionagents-go
go build -o bin/ils ./cmd/ils

# 或者把编译好的 bin/ils 从主控机 scp 过去
# scp bin/ils root@JD-ECS:/root/unionagents-go/bin/ils

# 重启
systemctl daemon-reload
systemctl restart unionagents-ils-daemon
```

### Step 5: 验证

```bash
# 检查 agent 注册状态
curl -s http://localhost:8000/agents | jq '.agents[] | {name, agent_type, binding_status, status}'

# 期望看到：
# - binding_status: "ready" 或 "degraded"（不能是 "failed" 或 null）
# - agent_type: 正式类型（hermes / reasonix / claude_code 等，不能是 generic）
# - status: "online" 或 "healthy"
```

### Step 6: OB 前端（可选）

Omima Cockpit 前端 js 改了 wizard.js 和 entry.js。如果用 Tauri dev 模式就直接生效；如果要打包成 exe 分发，需要 `npm run tauri build`。但后端部署不受前端是否更新影响——前端只影响用户看到的选项，不做也不影响通信。

## 回滚方案

如果出问题：
```bash
# 回滚 DB
ALTER TABLE public.agents DROP CONSTRAINT IF EXISTS agents_agent_type_check;
ALTER TABLE public.agents ADD CONSTRAINT agents_agent_type_check
  CHECK ((agent_type = ANY (ARRAY['claude_code'::text, 'codex'::text, 'reasonix'::text, 'codewhile'::text, 'opencode'::text, 'generic'::text])));

# 回滚代码
cd /root/unionagents-go
git checkout HEAD~1 -- internal/agent/ cmd/ils/ internal/models/ internal/orchestrator/
# 重新编译 + 重启
```

## 关键注意事项

- **DB Migration 必须先跑**：orchestrator handler 里的 SQL 已经引用 `binding_status` 列，不先加列会查崩
- **AGENT_TYPE 不能再写 generic**：daemon 现在拿到 generic 直接返回 "❌ Agent binding failed: unknown agent_type"，不会冒充 Claude
- **Hermes 的 doctor 检查**：`curl -sf http://127.0.0.1:8000/health`，如果 Hermes Gateway API 不在 8000 端口或路径不同，需要在 `internal/agent/binding.go` 里改 `DoctorArgs`
