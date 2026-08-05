# 法律 RAG、动态案件记忆与 Case Orchestrator 执行报告

执行日期：2026-07-28；最终本机复验：2026-07-29（UTC+8）

> 2026-07-29 已完成后续 AGT-01 至 AGT-08 三类业务 Agent。为保留本报告
> 的阶段性审计记录，详细实现、测试和降级项另见
> `docs/business_agents_execution_report.md`。当前全量验收为 60 passed，
> Ruff 与 mypy 均通过。

> 2026-07-29 语料复核更正：原 50 个片段中发现 14 处截断、概括或排版性
> 非逐字摘录，另有 2 条“标准状态”题录不应进入法律索引。现已全部更正并
> 调整为 48 个 `verbatim_excerpt`；48/48 通过逐字审计，旧 50 片段版本废止。

## 1. 现有成果审计

- 目标仓库：`accident-rights-agent`
- 分支：`main`
- 开始时工作区：干净
- 已有提交：
  - `1926edc Implement case intake and evidence reconstruction`
  - `a8224ad Bootstrap AMD local inference environment`
- 已确认并保留：
  - AMD/ROCm、Qwen3-VL、loopback-only vLLM 配置与性能记录；
  - Case Intake、原始证据不可变存储、Evidence Graph、PDF/图片/视频解析；
  - 既有 `EvidenceStore` 和 per-case SQLite 数据结构。
- 开始前测试基线：25 passed、1 skipped（本机当时未安装 FastAPI extra）。

本阶段没有重建或大规模重构证据模块。

## 2. 实际完成项

### 2.1 法律 RAG

- 新增统一、版本化 Pydantic schema：
  - `LegalDocument`
  - `LegalChunk`
  - `LegalCitation`
  - `LegalConclusion`
- 建立 13 份官方来源语料清单、48 个逐字复核片段，覆盖：
  - 道路交通安全法；
  - 道路交通安全法实施条例；
  - 道路交通事故处理程序规定；
  - 民法典侵权责任及机动车交通事故责任；
  - 交通事故损害赔偿司法解释（一）；
  - 2026 年已施行的司法解释（二）；
  - 交强险条例；
  - 保险法；
  - GB 17761-2024；
  - GA 802-2019；
  - GB 7258-2017；
  - 两轮电动车属性最高法典型案例；
  - 交通事故责任最高法典型案例。
- 官方源下载工具仅允许全国人大、司法部、最高人民法院、公安标准、
  国家标准和政府机关白名单域名。
- 在线核验结果：13 份中 12 份成功；满足最低 10 份 P0 门槛。
- 新增原文审计门：42 条官方快照自动匹配、3 条官方 PDF 目视复核并锁定
  来源指纹、3 条 GA 802-2019 官方页面索引/官方交叉来源复核；摘要禁止入库。
- 语料导入在索引前强制检查官方源核验报告；不足 10 份时拒绝入库。
- 实现文本清洗、条/款/项切分、SHA256 去重和现行版本生效区间冲突检查。
- SQLite 保存可审计语料，Qdrant local mode 保存持久向量索引。
- Qdrant payload 和查询接口支持：
  - `jurisdiction`
  - `effective_date`
  - `status`
  - `document_type`
- 实现 BM25 + dense reciprocal-rank fusion Top-10，以及可插拔
  bge-reranker-v2-m3 Top-10 → Top-4。
- BGE-M3 和 reranker 只接受本地路径，拒绝远程模型 ID；设备可配置为
  `cpu` 或 ROCm PyTorch 使用的 `cuda`。
- 无引用时，确定性法律结论在 schema 层失败。

### 2.2 动态案件记忆

- Evidence Memory：沿用不可变原始证据和 Evidence Graph。
- Fact Memory：状态投影与追加式事件日志。
- Working Memory：保存每个节点的任务上下文及压缩前后 token 估算。
- Case Capsule：严格 JSON Schema、版本递增、历史版本不覆盖。
- 事实状态机：
  - `unverified`
  - `confirmed`
  - `disputed`
  - `rejected`
- 每次事实迁移保存 actor、UTC timestamp、reason 和事件版本。
- ProtectedField 覆盖：
  - 日期、法定期限、金额、责任比例；
  - 车牌/车辆标识、当事人角色；
  - Evidence ID、Fact ID、Law ID；
  - 文档版本、人工审批状态。
- 上下文构建后执行集合一致性检查，丢失任一保护字段即抛错并阻断节点。
- 每个 Agent 只接收 Case Capsule、Top-K 事实、Top-K 法律引用和保护值，
  不传完整历史。

### 2.3 Case Orchestrator

实现状态图：

```text
intake_complete
  -> evidence_ready
  -> legal_retrieval
  -> vehicle_nature
  -> liability
  -> rights_workflow
  -> verifier
  -> human_approval
```

保留并验证分支：`missing_evidence`、`legal_conflict`、`low_confidence`、
`node_failed`。

- SQLite checkpointer 使用 `thread_id` 恢复。
- 每个节点返回统一 `NodeResult`：
  `status / started_at / finished_at / inputs_hash / outputs / warnings /
  errors / retry_count / metrics`。
- JSON/schema 错误只自动修复并重试一次。
- 每个节点有明确 timeout；超时和异常进入失败状态，不无限重试。
- CLI 与 API 均可读取当前节点、进度、错误和可恢复状态。
- Verifier 检查：
  - Evidence ID 存在；
  - LegalCitation 存在、可在语料中解析、当前有效；
  - 车辆属性与赔偿路径一致；
  - 责任假设有事实和引用支撑；
  - 无“必然、保证胜诉、已提交、已发送”等危险断言；
  - ProtectedField 审计通过。
- Human Approval 前，审批状态为 `pending`，文书和任务状态只允许 `draft`。
- 一键 Demo 会创建纯合成案件，在 `evidence_ready` 人为中断，读取检查点，
  再恢复至人工审批。

## 3. 实际执行命令与结果

```bash
.venv/bin/python scripts/fetch_laws.py
```

结果：12/13 个官方页面通过域名、标题、状态码和哈希核验；1 个法院镜像
当次返回 HTTP 502，未使用二手来源替换。

```bash
EMBEDDING_PROVIDER=hash RERANKER_PROVIDER=heuristic \
  .venv/bin/python scripts/ingest_laws.py
```

结果：

```text
documents=13
chunks=48
indexed=48
qdrant_count=48
verified_quotes=48
verified_sources=12
```

```bash
.venv/bin/python benchmarks/legal_retrieval.py
```

轻量 hash + heuristic 回归结果：

```text
question_count=12
Recall@4=1.0000
MRR=0.8333
citation_completeness=1.0000
```

随后在隔离的 Python 3.12 环境下载本地权重并执行真实 BGE 验收。以下
BGE 数据来自语料修复前的 50 片段版本，只证明本地模型链路，不作为当前
48 片段的语料验收结果：

```bash
BGE_M3_MODEL_PATH=models/bge-m3 EMBEDDING_DEVICE=cpu \
  python scripts/ingest_laws.py \
  --embedding-provider bge \
  --corpus-db /private/tmp/accident-rights-bge-corpus.sqlite3 \
  --qdrant-path /private/tmp/accident-rights-bge-qdrant

BGE_M3_MODEL_PATH=models/bge-m3 \
BGE_RERANKER_MODEL_PATH=models/bge-reranker-v2-m3 \
EMBEDDING_DEVICE=cpu RERANKER_DEVICE=cpu \
  python benchmarks/legal_retrieval.py \
  --corpus-db /private/tmp/accident-rights-bge-corpus.sqlite3 \
  --qdrant-path /private/tmp/accident-rights-bge-qdrant \
  --embedding-provider bge --reranker-provider bge \
  --output benchmarks/reports/legal-retrieval-bge-full-cpu.json
```

真实本地模型结果：

```text
BGE-M3 index build: 32.17 s
documents=13
chunks/indexed/qdrant_count=50/50/50（历史，已废止语料版本）
embedding_dimension=1024

BGE-M3 + heuristic cold run: 11.87 s
Recall@4=1.0000
MRR=0.8333
citation_completeness=1.0000

BGE-M3 + bge-reranker-v2-m3 cold run: 74.81 s
Recall@4=1.0000
MRR=0.8611
citation_completeness=1.0000
reranker_degraded_reason=null
```

模型从仓库内被忽略的 `models/` 本地目录加载；运行时没有调用云
Embedding 或远程 reranker API。上述时延是 Intel Mac CPU 的冷启动验收，
不代表 Radeon ROCm 性能。隔离环境的精确版本和两个模型主权重 SHA256
已记录在 `config/mac-bge-validated-versions.txt`。

```bash
.venv/bin/python benchmarks/orchestrator.py
```

合成案件结果：

```text
interrupt_phase=101.621 ms
resume_phase=480.271 ms
context_before=26,707 estimated tokens
context_after=18,997 estimated tokens
context_reduction=28.87%
recoverable=true
high_cost_parser_reexecuted=false
verifier_passed=true
protected_fields_valid=true
approval_status=pending
document_status=draft
```

```bash
.venv/bin/pytest -q
```

最终结果：

```text
60 passed, 2 warnings
```

P0 自动验收已覆盖：

- 13 份语料入库；
- Qdrant 关闭后重启恢复；
- 12 问 Top-4 正确条文；
- LegalCitation 完整率；
- LangGraph 端到端；
- SQLite 人为中断恢复；
- 高成本证据解析不重复；
- JSON/schema 单次重试；
- ProtectedField 100% 保留与丢失阻断；
- 引用缺失时阻断确定性结论；
- 工作流 API 状态与恢复；
- Human Approval 前保持 draft/pending。

## 4. 失败、降级和限制

1. BGE-M3 与 bge-reranker-v2-m3 已在隔离的 Python 3.12 / Intel Mac CPU
   环境完成真实本地验收；主项目 Python 3.14 环境仍只用于轻量自动测试。
   Radeon Python 3.10/ROCm 需要使用同一模型目录重新记录 GPU 时延、显存
   与并发，不能把本机 CPU 数据作为 AMD 优化结论。
2. 两个本地模型目录合计约 6.4 GB，已被 `.gitignore` 排除，不进入提交。
3. GA 802-2019 的益阳交警官方正文页本轮直连因 TLS 证书链异常失败。
   公安部标准平台已核验版本状态；3 个正文片段由该官方页搜索索引及法院、
   司法行政机关的官方交叉来源复核。此项按来源可达性降级披露。
4. 本机测试有两个非阻断警告：
   - LangChain Core 的 Pydantic V1 兼容层提示不支持 Python 3.14；
   - Starlette TestClient 提示未来迁移到 httpx2。
   Radeon 目标环境为已验证的 Python 3.10，不受第一项影响。
5. 工作日工具当前排除周末，正式部署需接入中国法定节假日表，并由人工
   核对送达时间和期限起算规则。
6. 合成短案件上下文缩减为 28.87%；长案件收益需在下一阶段使用真实脱敏
   压测集测量，不以当前数值代替目标实例结论。
7. 法律快照只覆盖比赛主场景的相关条款，不替代完整法规库、鉴定或律师意见。

## 5. 安全与仓库状态

- `.env.example` 仅含本地路径和 loopback 地址，无 API key。
- 代码没有公共 Qwen、DeepSeek、OpenAI 模型端点。
- 案件、Qdrant、checkpoint、下载快照和 SQLite 运行数据均已忽略。
- 依赖已精确锁定在 `requirements.lock` 和 `pyproject.toml`；
  Radeon 基础镜像版本继续由 `config/radeon-validated-versions.txt` 管理。
- Agent 开发仓库仍为独立本地仓库，尚未绑定或推送远程。
- 已按比赛要求创建官方仓库 Fork：
  `JimchengChina/Radeon-hackathon-2026-07`。
- 已把独立提交分支 `submission/accident-rights-agent` 推送到该 Fork；
  分支当前仅同步官方基线，尚未复制未英文化的 Agent 材料，也未创建 PR。
- 最终 PR 只在英文项目说明、源码、演示材料和复现说明齐备后创建。

## 6. 下一阶段接口

1. 在 Radeon 实例放置：
   - `/persistent/models/bge-m3`
   - `/persistent/models/bge-reranker-v2-m3`
2. 复制已下载的本地 BGE 目录或在目标实例重新下载，设置 `.env` 中的
   provider、模型目录和设备；重建索引并记录 Radeon
   embedding/reranker 时延、显存和 Recall@4。
3. 用现有 Liability/Vehicle/Rights Agent 的本地 Qwen3-VL 结构化输出
   替换当前可测试的确定性节点实现，保留同一 NodeResult 和 Verifier 契约。
4. UI 直接消费：
   - `POST /cases/{case_id}/workflow`
   - `GET /workflows/{thread_id}`
   - `POST /workflows/{thread_id}/resume`
5. 加入脱敏真实案件集、节假日服务、地区规则包和人工反馈排行榜。

## 7. 2026-07-29 Rights Workflow 阶段补充

RGT-01～06、RULE-01～03、VER-01～05 已在现有图和 schema 上完成，没有
重建前述 RAG、记忆、Evidence Graph 或业务 Agent。此前“仅排除周末、仍需
接入节假日表”的限制已解除：期限工具现使用带内容哈希的 2026 年国务院
节假日/调休日历；超出该日历覆盖范围时返回
`disputed/needs_legal_review`，不做猜测。

本阶段完整架构、规则策略和验收结果分别见：

- `docs/RIGHTS_RULES_VERIFIER_ARCHITECTURE.md`
- `docs/rights_rules_verifier_execution_report.md`
- `docs/examples/rights_workflow_demo.json`

最新本地验收为：

```text
pytest: 90 passed, 2 non-blocking dependency warnings
ruff: all checks passed
mypy: success, no issues in 71 source files
compileall: passed
```

Radeon Active Instance 仍为已销毁状态，本阶段没有重新创建实例、修改持久
卷或产生新的 GPU 实测结果。
