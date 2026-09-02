- Level: S2
- Status: implemented

# Stage G 持续知识与风险监控 — TECH.md

## 架构决策

### 选型：SQLite 持久化
所有 Stage G 数据（风险规则、风险记录、文档版本、变更日志、质量指标）均使用 SQLite，与项目现有架构一致。无需引入额外数据库。

### 模块划分

```
app/
├── schemas/
│   ├── risk_sql.py          ← DDL: risk_rule, risk_record, risk_scan_run
│   ├── doc_version_sql.py   ← DDL: document_version, document_change_log, change_impact, quality_metric, quality_bench_dataset
│   ├── stage_g_models.py    ← Pydantic models (独立文件)
│   └── models.py            ← Pydantic models (内联在模型文件底部)
├── services/
│   ├── risk_engine.py       ← 风险规则引擎 (规则注册、评估、去重、聚合)
│   ├── risk_scanner.py      ← 定时扫描器 (编排规则、写库、影响分析)
│   ├── doc_version.py       ← 文档版本管理 (SHA-256 追踪、增量索引)
│   ├── change_impact.py     ← 变更影响分析 (ImpactEntry, ImpactReport)
│   └── quality_metrics.py   ← 质量指标服务 (播种、评估、比较)
├── rag/
│   └── quality_bench.py     ← 检索质量基准集 & 评估方法
└── observability/
    └── error_codes.py       ← 新增 7 个 Stage G 错误码
```

### 关键数据表

**risk_rule** — 配置的检测规则
- rule_id (PK), rule_type, config_json, enabled

**risk_record** — 检测到的风险
- record_id (PK), risk_type, entity_type, entity_id, severity, lifecycle, dedup_hash

**risk_scan_run** — 扫描运行元数据
- scan_id (PK), scan_type, total_rules, new_risks

**document_version** — 文件版本追踪
- project_id, relative_path, sha256, parse_version, index_version, is_current, replaced_by

**document_change_log** — 变更历史
- project_id, relative_path, change_type, old/new SHA-256 和版本号

**change_impact** — 影响分析记录
- project_id, relative_path, affected_entity_type, affected_entity_id

**quality_bench_dataset** — 基准测试用例
- test_case_id (PK), category, question, expected_relevant, should_refuse

**quality_metric** — 质量指标记录
- per-case recall rate, citation accuracy, refusal rate, latency, failure rate

### 去重策略

使用 SHA-256(project_id|rule_id|entity_id|status) 生成 dedup_hash。
首次出现的风险入库，重复的自动跳过。每个风险只有一条 active 记录。

### 风险生命周期

```
active → acknowledged → resolved
active → dismissed
active → expired (TBD scheduler)
```

### 默认行为

- `ScannerConfig.notify_external = False` — 默认不外发通知
- 风险扫描结果仅写入内部表，不触发邮件/IM
- 后续阶段可在 `notify_external=True` 时接入通知渠道

### 增量索引策略

1. `detect_file_changes()` 对比文件系统与 `document_version` 表
2. SHA-256 未变 → 跳过
3. SHA-256 变更 → bump parse_version 和 index_version，记录 change_log
4. 外层 indexer 仅对变更文件执行解析和嵌入

### 质量基准评估

`evaluate_single_query()` 依赖注入 `retrieve_fn(query: str) -> dict`，解耦评估逻辑与具体检索实现。benchmark 数据集通过 `seed_benchmark_dataset()` 播种到 SQLite。

## 依赖

- 无新增外部依赖。所有功能使用标准库 + 已有依赖实现。
- 测试依赖 `pytest`（已在 optional-dependencies 中）
