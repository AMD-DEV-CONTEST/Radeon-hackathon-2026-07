# 项目 Checklist — Radeon AIOps Agent

> `[x]` 已完成 / `[ ]` 待做。详细设计见 `docs/DESIGN.md`。

---

## M1 — 推理基座

- [x] llama.cpp ROCm/HIPBLAS 编译验证（ldd 确认 ROCm 库）
- [x] Qwen27B Q4_K_M + KV q8_0 + FA + mmap + prompt-cache 跑通
- [x] tool-calling 格式验证
- [x] thinking 模型 `reasoning_content` 独立字段确认
- [x] 性能基线测量（生成 ~29 t/s、prompt 衰减曲线、VRAM 21.7G/51.5G）
- [x] MTP 投机解码启用 + 参数调优（`--spec-type draft-mtp`，基准测试 n_max=1~8，最优 n_max=1 达 37.5 t/s +30%）

## M2 — 工具层 + ReAct

- [x] `get_service_status` / `get_alerts` / `get_metrics` / `read_logs`（预压缩）/ `search_kb` / `restart_service`（SSH）/ `hdfs_admin` / `edit_remote_config`
- [x] 手写 ReAct 循环跑通故障剧本
- [x] docker-compose 3 节点 Hadoop HA 集群 — HDFS HA(2NN+3DN+3JN+ZKFC) + YARN HA(2RM+3NM+JHS) + ZK quorum, MR Pi 验证通过
- [x] Hive + HBase + MySQL — Hive 4.2.0 (2HMS/2HS2/MR 引擎, create/insert/select 全验证), HBase 2.5.15 (2HM 互备/3RS, shell 可用), MySQL 8.0 (metastore DB)
- [x] Grafana 仪表盘配置（4 面板: Cluster Overview / HDFS / YARN / HBase+ZK）
- [x] SSH 免密（容器间互信 + 宿主机可访问 2222-2224 端口）

## M3 — 编排层

- [x] Orchestrator 常驻 + master 纯规则调度
- [x] session manager（用完即焚子 session）
- [x] `/auto` 巡检 loop + `/fix` 告警抢占
- [x] SQLite 落库（sessions / events / cluster_state）
- [x] 上下文策略：一次性 context + DB 状态卡 + 工具输出预压缩
- [x] 端到端闭环验证：停 DataNode / 停 NameNode → 检测 → 诊断 → 重启 → 验证
- [x] Orchestrator 异常兜底（循环体 try/except + 5s 退避重试）

## M4 — 安全护栏

- [x] 风险分级 low/medium/recover/reversible/irreversible（双轴：AUTONOMY × tier）
- [x] `risk_rules` 表 + 迁移 + 种子（`*` 默认 fail-closed → irreversible）
- [x] `classify()`：查 `risk_rules`（TTL 缓存）+ `match_json` 命中 + fail-closed
- [x] `Guardrail` 四档分支 + `AUTONOMY` 轴（supervised/autonomous）
- [x] dry-run 预演
- [x] 审批门（console 自动 / web 等人工）
- [x] 审计日志（audit_log）
- [x] 熔断（连续失败上限 + 冷却，类级跨会话共享）
- [x] 高危尝试节流：按 `(tool,target)` 查 `audit_log` 派生计数 + 冷却 + 超限升级
- [x] 回滚机制（`edit_remote_config` 先备份 `.bak.<ts>`，替换失败自动回滚）
- [x] `AUTONOMY` 模式替换 `AUTO_APPROVE`（默认 supervised 安全）
- [x] Web API + 管理页面：`risk_rules` CRUD（irreversible 档禁勾 autonomous）
- [x] 联调：无人值守 DOWN 自动重启重试 / irreversible 拒绝并升级告警

## M5 — 知识库 + 学习闭环

- [x] `runbooks` 表 + FTS5 全文索引 + 触发器同步 (db.py)
- [x] 种子数据 6 条 runbook
- [x] `kb.py`: bge-small-zh 嵌入模型 (CPU, 懒加载) + numpy 余弦相似度向量检索
- [x] 混合检索: 向量 top-k + BM25 top-k 合并去重, 向量优先; 缺 bge 自动降级 BM25
- [x] `search_kb` 工具重写: 接入混合检索, content 截断防 context 膨胀
- [x] `write_runbook` 工具: 置信度门控 (<0.7 拒绝) + pending_review 状态 + session_id 关联
- [x] `guardrails.py`: write_runbook session_id 注入 + 低危自动执行
- [x] Web API: runbooks CRUD + `/review` 审核接口 + `/search` 检索测试 + `/stats` 统计
- [x] Web 前端: 知识库管理页面 (统计卡片 / 检索测试 / 列表 / 审核 / CRUD)
- [x] `agent.py` 学习闭环: fix 模式修复成功后自动提示回写 runbook
- [x] 测试: `tests/test_m5_kb.py` 验证 DB/FTS/CRUD/write_runbook/审核/置信度门控

## M6 — Web 控制台

- [x] 后端 FastAPI: REST API + WebSocket (/ws 事件推送)
- [x] 事件总线 EventBus: 线程安全 queue.Queue 桥接同步/异步
- [x] 前端 React + Vite + Ant Design (暗色主题)
- [x] Agent 活动台: Session 树 + Timeline 事件流 (Markdown 渲染 + 流式输出 + 折叠 JSON)
- [x] 审批中心: Table (pending/decided 分组, 风险标签, 通过/拒绝按钮)
- [x] 风险规则: risk_rules CRUD (irreversible 档禁勾 autonomous)
- [x] 集群状态卡: 选中 master session 显示服务健康状态
- [x] 流式输出: SSE + WebSocket 逐 token 推送
- [x] 智能滚动: 用户在底部才自动滚动, 向上查看历史不打断
- [x] 前端 admin 模板进一步美化

## M7 — 演示与提交

- [x] 多故障剧本跑通（DataNode 掉线 / NameNode SIGTERM / 磁盘满 / MetaStore OOM）
- [x] 端到端录屏
- [x] DESIGN.md 英文化（英文作默认主文件，中文保留 `DESIGN_ZH.md`）
- [x] **README 复现步骤 + 架构图** ← 已完成（实现全云部署，方便评委复现）
- [x] 性能数据整理（tokens/s、TTFT、VRAM、故障解决耗时）
- [x] 文档交叉引用最终核对

## 缺陷修复（评审发现并已修）

- [x] 状态卡数据结构（后端 `services` 改回对象 + `overall_health`）
- [x] 流式输出结束被截断 300 字（去掉 `[:300]`）
- [x] 审批流形同虚设（`AUTO_APPROVE` 接入 Guardrail → `AUTONOMY` 模式）
- [x] SQLite 跨线程（RLock + `store.lock`）
- [x] 轮询风暴（10s 缓存）+ 快速失败（Retry(0) + timeout 3/5）
- [x] 熔断永不触发（`_is_failed` 加 `error`/`circuit_broken`）
- [x] 单节点重启误会（tool 描述/hint 写明以服务为单位）
- [x] 静态 20 项：命令注入转义 / CORS / 审批流程 / 流式异常 / 死代码 / 前端错误处理等

## 锦上添花（按需实现）

### 推理与可用性

- [ ] **OpenAI 兼容端点备选** — 远程 llama-server 不可用时，可配置 OpenAI 格式的 `base_url` + `api_key`（如 DeepSeek / 智谱 / vLLM 等）作为推理后端兜底。`llm_client.py` 加 `provider` 分支：本地走 llama.cpp 原生 `/v1/chat/completions`，远端走 OpenAI SDK，接口一致 agent 无感知。通过环境变量 `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_BASE_URL` 切换，启动时探测连通性自动 failover
- [ ] **控制平面 Dockerfile + compose** — 将 Python 后端 + React 前端(nginx) + Orchestrator 打成 Docker 镜像，编写 `docker-compose.yml` 统一编排，一键 `docker compose up` 启动整个控制面（不含 Hadoop 集群），降低评委复现门槛
- [ ] **`/health` 端点** — FastAPI 加 `GET /health` 返回 `{status, llm_reachable, db_ok}`，供 Docker healthcheck 和负载均衡探活，LLM 不可达时标记 degraded 而非直接崩
- [ ] **Prometheus 指标导出** — 集成 `prometheus-fastapi-instrumentator`，暴露 `GET /metrics` 端点，让现有 Prometheus 采集 agent 自身的请求量/延迟/错误率，实现"agent 监自己"

### Agent 能力增强

- [x] **对话式运维 Chat Mode** — 已实现：`ChatConsole.tsx` 前端组件 + `/api/chat/sessions` CRUD + `chat_messages`/`chat_sessions` DB 表 + orchestrator 轮询 pending 消息 + `ReActAgent` chat 模式（全工具集 + 多轮历史）+ WebSocket 流式推送
- [ ] **告警聚合去重** — Alertmanager 短时间内对同一服务发多条告警（如 DataNode 重启时先 DOWN 再恢复又 GC 告警），当前每条都 spawn 一个 fix session 导致重复操作。加窗口聚合：同 `(service, node)` 在 60s 内的告警合并为一个 fix 任务，附告警时间线
- [ ] **ReAct 上下文预算** — 追踪每次 LLM 调用返回的 `usage`（prompt_tokens + completion_tokens），累计后与上下文窗口上限比较。剩余窗口低于阈值（如 4k）时主动触发摘要压缩或提前收尾，避免 context 溢出被 llama.cpp 截断导致推理质量骤降
- [ ] **并行 Fix 会话** — 当前单 GPU 串行（-np 1），但如果两条告警涉及不同服务（如 HDFS DataNode + HBase RegionServer），可并行 spawn 两个 fix session。同服务的操作加服务粒度锁串行，避免配置冲突。需确保 `audit_log` 和 `risk_rules` 并发安全
- [ ] **事后报告自动生成** — fix session 结束后（无论成功失败），自动整理 ReAct 时间线 + 根因 + 修复步骤 + 验证结果，生成 Markdown post-mortem 存入 `session_events`，Web 可查看和导出。供运维留档和评委审阅

### Web 前端增强

- [ ] **健康总览 Dashboard** — Web 首页（登录后落地页）展示：服务状态卡（绿/黄/红）、活跃告警数、最近 5 次 fix 结果、当前 AUTONOMY 模式徽章。一屏掌握全局，不用点进 Agent 活动台才能看状态
- [ ] **审批实时推送** — 部分完成：Header 已有 `Badge count={pendingCount}`（10s 轮询）。待补：WebSocket 主动推送（替代轮询）+ `Notification API` 弹系统通知 + Sider 菜单项 Badge
- [ ] **Agent 进度提示** — 会话卡片上显示"迭代 3/15"+ 已耗时（如 "2m30s"），让用户知道 agent 还在跑没卡死。上限 15 轮是 ReAct 循环的硬限制，进度条让等待过程可预期
- [ ] **工具结果友好渲染** — `read_logs` 返回的文本按日志级别着色（ERROR 红 / WARN 黄 / INFO 默认）；`get_metrics` 的 JSON 用数值卡片展示（CPU 85% / MEM 12.3G / Disk 67%），替代当前的原始 JSON 折叠块
- [ ] **Runbook 版本 Diff** — `write_runbook` 更新已有 runbook 时保留历史版本（`runbook_versions` 表），Web 管理页加 Diff 视图（类似 Git diff），方便审核 agent 回写的内容改了什么

### 工程规范与安全

- [ ] **统一 logging** — 部分完成：全部 7 个源文件已配置 `logging.getLogger(__name__)`。待补：orchestrator/agent/guardrails 仍有 ~25 个 `print()` 用于控制台 UX 输出，需替换为 logger + 文件轮转
- [ ] **工具入参 Pydantic 校验** — 每个工具的入参用 Pydantic model 定义类型/长度/正则约束（如 `service` 枚举值、`node` IP 格式、`tail_n` 上限 5000），guardrail 层二次校验。防止模型幻觉出非法参数导致 SSH 执行异常命令
- [ ] **`edit_remote_config` XML 语法校验** — 配置文件改完后用 `xmllint --noout` 校验 XML 合法性，校验失败自动回滚备份。防止改出语法错误的配置导致服务重启失败
- [ ] **一键回滚工具** — 新增 `rollback_config(node, file)` 工具，找 `.bak.<ts>` 最新备份恢复。当 `edit_remote_config` 改完后服务起不来，agent 可自动调回滚工具恢复，不用人工 SSH 进去手动 cp
- [ ] **API 速率限制** — 集成 `slowapi`，对写操作（审批/配置修改/服务重启）限流（如 10 次/分钟），防止 agent 失控或前端误操作导致短时间内大量高危请求
- [ ] **Web 默认鉴权** — `CONSOLE_TOKEN` 环境变量为空时，启动自动生成随机 token 并打印到日志，而非当前的无鉴权裸奔。生产部署必须鉴权
- [ ] **前端 API 地址可配** — 前端 API base URL 从硬编码 `localhost:8000` 改为 Vite 环境变量 `VITE_API_URL`，支持 `.env.production` 配置部署域名，不同环境不用改代码重新 build
- [ ] **requirements 固定版本** — `pip freeze > requirements.txt` 或迁移到 `pyproject.toml + uv lock`，锁定所有依赖版本。避免新机器 `pip install` 拉到不兼容新版导致运行不了

### 可观测性

- [ ] **时序指标趋势图** — 新增 SQLite 时序表定期记录 `get_metrics` 的 CPU/MEM/Disk 数值，Web 前端画 24h 趋势折线图。当前只能看瞬时快照，趋势图能发现"磁盘每天涨 5%"这类渐变问题
- [x] **一键 Demo 脚本** — `scripts/inject-fault.sh`：一键启动集群 → 等待健康 → 注入故障（kill DataNode）→ 触发 fix → 展示 Web 控制台完整闭环。评委运行一条命令即可看到完整演示效果，不用手动多步操作

## AMD Cloud 部署适配

### 已完成

- [x] **FastAPI 单端口托管前端** — `web/app.py` 加 `StaticFiles` + SPA fallback，FastAPI :8000 同时服务 API/WS/React 静态文件
- [x] **llama.cpp ROCm 编译脚本** — `scripts/build-llama.sh`，HIPBLAS + 符号链接统一路径
- [x] **Docker-in-Docker 安装脚本** — `scripts/setup-docker.sh`（实际 AMD Cloud 不支持 Docker-in-Docker，缺 CAP_SYS_ADMIN）
- [x] **tarball 下载自动化** — `scripts/download-tarballs.sh`
- [x] **前端生产构建** — `scripts/build-frontend.sh` + Vite build 配置
- [x] **.env 环境变量模板** — `.env.example`
- [x] **一键部署主脚本** — `scripts/setup-cloud.sh`，6 步串起全流程，幂等可重复
- [x] **集群导出 + 远程托管** — `scripts/export-cluster.sh` 导出镜像+数据卷，托管在 `http://8.148.228.51/repo/aiops-cluster-backup/`
- [x] **rc-tunnel 公网暴露** — `setup-cloud.sh` Step 6 自动暴露 :8000

### 已完成

- [x] **单节点 Hadoop 直装** — `scripts/setup-hadoop-direct.sh`：AMD Cloud 不支持 Docker-in-Docker（缺 CAP_SYS_ADMIN + seccomp 拦截 user namespace），改为直接在 host 上安装单节点 Hadoop + ZK + HBase + Hive + Tez + MySQL + supervisord + 3 SSH 端口。Demo 效果不变（注入故障 → Agent 检测 → 修复）
- [x] **setup-cloud.sh 适配单节点** — 当 Docker 不可用时自动 fallback 到单节点直装路径
- [x] **统一健康检查脚本** — `scripts/healthcheck.sh`：双模式兼容（Docker 3节点 HA / 单节点直装），自动检测模式，检查进程/端口/HA状态/读写
- [x] **所有脚本英文化** — 注释和 echo 输出全部改为英文，方便国际评委阅读

### 已完成（Path 2: 远程 Hadoop HA）

- [x] **远程 Hadoop HA 集群** — 在 8.148.228.51 上搭建 Docker 3 节点 Hadoop HA 集群，AMD Cloud 通过 SSH 隧道/反向代理访问。Agent 在 AMD Cloud 上跑，SSH 连远程集群节点。需要：SSH 反向隧道或 WireGuard VPN 打通网络、agent config 指向远程 IP、Prometheus 远程采集
- [x] **评委复现文档** — README 写两条路径：A) 单节点直装（简快）、B) 远程 HA 集群（完整 3 节点效果）

## 待敲定参数

- `MAX_ATTEMPTS` / `cooldown` / 观察窗口 `WINDOW`（建议 2 次 / 30–60s / 10min）
- 审批超时（现 10min）/ 巡检周期（现 5min）/ `-t` 线程（现 16）
