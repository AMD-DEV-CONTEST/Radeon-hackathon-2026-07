# AIOps Agent — 大数据集群自治运维

> [English](./README.md) | **中文**
>
> **赛道2: 私有 AI Agent 开发与本地部署**
>
> 基于 LLM (Qwen 27B + ROCm) 的大数据平台自治运维 Agent，实现 24h 无人值守巡检 → 告警驱动诊断 → 安全护栏修复 → 验证恢复的全闭环。

## 架构

```
Orchestrator (master session, 常驻规则调度)
  ├── /auto 巡检 (ReAct agent, 15 轮)
  └── /fix 修复 (告警驱动抢占, ReAct agent, 15 轮)
         ├── 工具层: SSH + Prometheus (10 个工具)
         │   ├── 只读: get_service_status / get_alerts / get_metrics / read_logs / search_kb / hdfs_admin / diagnose_node
         │   └── 写操作: restart_service (SSH) / edit_remote_config (备份→改→reload) / file_ops
         ├── 安全护栏 (§21 双轴四档分级自治):
         │   ├── 轴1 AUTONOMY: supervised (人工审批) / autonomous (无人值守)
         │   ├── 轴2 tier: low / medium / recover / reversible / irreversible
         │   ├── 定级: risk_rules DB (页面可配) + classify() + fail-closed
         │   ├── recover: attempt 节流 (audit_log 派生计数) + 熔断 (类级跨会话累积)
         │   ├── reversible: 先备份 .bak.<ts> 再改再 reload
         │   └── irreversible: autonomous 模式立即拒绝 + 升级告警
         └── 事件总线 → WebSocket → Web 控制台 (实时 ReAct 循环)

LLM: llama.cpp server (Qwopus3.6-27B-v2-MTP Q4_K_M, ROCm gfx1100, 128k context)
     KV q8_0 + Flash Attention + MTP 投机解码 (n_max=1, 37.5 t/s, +30%)
DB: SQLite (sessions/events/cluster_state/audit_log/approvals/risk_rules)
Web: FastAPI + WebSocket (后端) / React + Vite + Ant Design (前端)
```

## 集群模式

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| **本地单节点直装** | AMD Cloud host 上直接安装 Hadoop/ZK/HBase/Hive/Tez/MySQL + supervisord | 评委复现 (推荐) |
| **远程 3节点 HA** | 连接远程 Docker 3节点 Hadoop HA 集群 (SSH) | 完整 HA 效果 |

> AMD Cloud JupyterLab 容器不支持 Docker-in-Docker (缺 `CAP_SYS_ADMIN`, seccomp 拦截 user namespace)。本地单节点直装模式绕过此限制。

## 快速开始

### 一键部署 (AMD Cloud)

```bash
bash scripts/setup-cloud.sh
```

脚本自动完成:
1. 编译 llama.cpp (ROCm/HIPBLAS)
2. 下载模型 + 启动 llama-server
3. 安装 Hadoop 集群 (单节点直装)
4. 安装 Python 依赖
5. 构建前端
6. 启动 Agent + Web
7. rc-tunnel 公网暴露

### 一键演示

```bash
bash scripts/inject-fault.sh
```

流程: 注入故障 (kill DataNode) → 等待 Agent 检测 → 诊断 → 修复 → 验证

### 手动分步

```bash
# 1. 编译 llama.cpp
bash scripts/build-llama.sh

# 2. 下载模型 + 启动 llama-server
bash scripts/bootstrap.sh

# 3. 安装 Hadoop 集群 (单节点直装)
bash scripts/setup-hadoop-direct.sh

# 4. 健康检查
bash scripts/healthcheck.sh

# 5. 安装 Python 依赖
pip3 install -r requirements.txt --break-system-packages

# 6. 构建前端
bash scripts/build-frontend.sh

# 7. 配置 + 启动
cp .env.example .env
source .env
python3 -m main
```

## 功能模块

| 模块 | 状态 | 说明 |
|---|---|---|
| M1 推理基座 | ✅ | llama.cpp ROCm/HIPBLAS, Qwen27B Q4_K_M, MTP 投机解码 |
| M2 工具层 | ✅ | SSH 工具层, 10 个工具 (7 只读 + restart_service + edit_remote_config + file_ops), Hadoop 集群 |
| M3 编排层 | ✅ | Orchestrator 常驻 + /auto 巡检 + /fix 抢占 + SQLite 落库 |
| §21 安全护栏 | ✅ | 双轴四档 (AUTONOMY × tier) + risk_rules DB + classify + attempt 节流 |
| M5 KB 检索 | ✅ | 混合检索: bge-small-zh 向量 + BM25 FTS5 (自动降级) |
| M6 Web 控制台 | ✅ | FastAPI+WebSocket 后端, React+Vite+AntDesign 前端 |
| M7 演示提交 | ✅ | 录屏 + 性能数据 + README 复现步骤 |

## AMD Radeon GPU 推理优化

| 优化项 | 值 | 效果 |
|--------|-----|------|
| 模型 | Qwopus3.6-27B-v2-MTP Q4_K_M | 16GB, 27B 参数, 248K vocab |
| KV cache | q8_0 量化 | VRAM 节省 ~50% |
| Flash Attention | ON | 长序列加速 |
| MTP 投机解码 | `--spec-type draft-mtp --spec-draft-n-max 1` | 37.5 t/s (baseline 28.9, +30%) |
| Prompt cache | ON (8192 MiB) | 重复 prompt 加速 |
| Context | 131072 (128k) | 支持长上下文 |
| VRAM | 21.7G / 51.5G | 充裕 |

### MTP 基准测试

| 配置 | t/s (client) | 加速比 | 接受率 |
|------|-------------|--------|--------|
| baseline (无 MTP) | 28.9 | — | — |
| **n_max=1 (最优)** | **37.5** | **+30%** | 77.4% |
| n_max=2 | 34.2 | +18% | 61.0% |
| n_max=3 | 34.0 | +18% | 53.7% |
| n_max=5 | 31.7 | +10% | 44.6% |
| n_max=8 | 29.5 | +2% | 24.0% |

## Web 控制台

- **左侧菜单**: Agent 活动台 / 审批中心 / 风险规则 (可收缩)
- **Agent 活动台**: Session 树 (master→auto/fix) + Timeline 事件流 (Markdown 渲染 + 流式输出 + 折叠 JSON)
- **审批中心**: pending 列表 + 通过/拒绝 + 风险标签 + Badge 角标
- **风险规则**: risk_rules CRUD (irreversible 档禁勾 autonomous)
- **集群状态**: 选中 master session 显示服务健康状态卡 (overall_health + per-service)

## 安全护栏 (§21 双轴四档)

| 档位 | 典型操作 | autonomous 行为 | supervised 行为 |
|------|---------|---------------|----------------|
| low / medium | 只读 / 重启非核心 | 自动执行 | 自动执行 |
| recover | 重启已 DOWN 服务 | attempt 节流 → 自动执行 | 等人工审批 |
| reversible | 改配置 (先备份) | 自动执行 (强制备份) | 等人工审批 |
| irreversible | hdfs format / rm | **立即拒绝 + 升级告警** | 等人工审批 |

定级权归规则(DB), 不归模型。fail-closed: 未知工具一律 irreversible + 不可自动。

## 文件结构

```
scripts/                    # 部署 & 演示脚本
├── setup-cloud.sh          # ★ 一键部署 (AMD Cloud)
├── setup-hadoop-direct.sh  # ★ 单节点 Hadoop 直装
├── inject-fault.sh         # ★ 一键演示 (注入故障 → 修复)
├── healthcheck.sh          # 集群健康检查 (Docker/直装双模式)
├── build-llama.sh          # 编译 llama.cpp (ROCm)
├── build-frontend.sh       # 构建前端 (生产模式)
├── download-tarballs.sh    # 下载 Hadoop tarball
├── export-cluster.sh       # 导出 Docker 镜像+数据卷
└── bootstrap.sh            # 启动 llama-server (模型下载)
main.py                     # 入口 (FastAPI + Orchestrator)
src/                        # Python 后端
├── orchestrator.py         # 常驻编排 (master session, /auto+/fix)
├── agent.py                # ReAct agent (巡检/修复, 流式输出)
├── llm_client.py           # LLM 客户端 (chat + chat_stream SSE)
├── tools.py                # 10 个工具 (SSH + Prometheus)
├── guardrails.py           # 安全护栏 (§21 双轴四档)
├── kb.py                   # 知识库 (向量 + BM25 RAG)
├── db.py                   # SQLite Store
└── web/
    └── app.py              # FastAPI (REST API + WebSocket + 静态文件)
web/                        # React + Vite + Ant Design
├── src/
│   ├── App.tsx             # 布局 (Sider+Header+面包屑+Content)
│   └── components/         # AgentActivity, ApprovalCenter, RiskRules, etc.
deploy/                     # Hadoop 集群部署
├── docker-compose.yml      # 3节点 Hadoop HA 集群 + 监控
├── image/                  # Dockerfile + supervisord 配置
├── config/                 # Hadoop/HBase/Hive/Tez/ZK/Prometheus/Grafana 配置
└── scripts/                # 集群初始化 & 守护进程重启脚本
docs/                       # 设计文档, 测试报告, TODO
├── DESIGN.md               # 详细设计文档 (英文)
├── DESIGN_ZH.md            # 详细设计文档 (中文)
├── README.md               # 项目说明 (英文)
├── README_ZH.md            # 项目说明 (中文, 本文件)
├── AGENT_TEST_REPORT.md    # Agent 自动修复测试报告
├── TEST_REPORT.md          # Hadoop 集群功能测试报告
└── TODO.md                 # 项目 Checklist
```
