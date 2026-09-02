# Stage G 持续知识与风险监控 — PRODUCT.md

## 概述

本阶段为 ProjectPack Office Agent 建立**持续知识与风险监控能力**，确保项目资料的可追溯性、风险状态的持续可见性，以及检索系统质量的可度量性。

## 用户故事

### US-G1 资料版本管控
作为项目经理，我希望每次资料更新后系统自动记录版本变更（SHA-256 + 版本号），这样我就能追溯任意文件的完整变更历史。

**验收标准：**
- 新文件首次记录：SHA-256 写入 + parse_version=1 + index_version=1
- 内容未变化：不增加版本号
- 内容变化：旧版本标记 replaced，新版本 parse_version+1 且 index_version+1
- 文件删除：is_current=0 保留审计记录
- 变更日志完整记录 old/new SHA-256 与版本号

### US-G2 增量索引
作为系统管理员，我希望资料更新后只重算真正变更的文件及关联 Chunk，避免全量重建带来的资源浪费。

**验收标准：**
- `detect_file_changes()` 对比 SHA-256 生成 new/modified/deleted/unchanged 分类
- 未变更文件不触发重新解析
- 变更文件进入增量索引流程（bump 版本号后重新解析）

### US-G3 风险规则引擎
作为项目经理，我希望系统自动根据预定义规则检测项目风险（临近截止、逾期、无证据等），并生成结构化风险记录。

**验收标准：**
- 内置 6 条风险规则：near_deadline / overdue / no_evidence / acceptance_gap / dependency_block / material_conflict
- 每条规则可独立启用/禁用、配置参数（config_json）
- 风险记录绑定到任务实体，含 severity 和 title/description
- 规则不足时支持扩展 custom 类型

### US-G4 风险去重聚合与生命周期
作为项目管理者，我希望同一风险不重复报警，且风险有完整的生命周期（active → acknowledged → resolved/dismissed/expired）。

**验收标准：**
- SHA-256 派生 dedup_hash，首次出现才入库
- 多次扫描不产生重复风险
- 风险可确认（ack）和解决（resolve）
- 按 severity/type/lifecycle 聚合统计

### US-G5 变更影响分析
作为资料维护者，我希望资料更新后系统列出受影响的关联任务和报告，以便及时调整。

**验收标准：**
- 文档 SHA-256 变更触发 `change_impact` 分析
- 查出 source_ref 或 evidence 引用该文件的任务
- 查出引用该文件的报告（run）
- 分析结果写入 `change_impact` 表

### US-G6 定时扫描（默认不外发通知）
作为项目管理员，我希望系统可定时扫描任务风险，但**默认仅创建内部风险记录，不发送外部通知**，以符合渐进式采纳原则。

**验收标准：**
- `ScannerConfig.notify_external` 默认为 False
- 扫描写入 `risk_record` + `risk_scan_run` 表
- 扫描不依赖外部服务

### US-G7 检索质量基准集
作为系统开发者，我希望能用标准化基准集评估 RAG 检索质量，包括事实题、跨文档题、无答案题和冲突题。

**验收标准：**
- 内置 12 个测试用例，覆盖 4 种类别
- factual 题测试单文档事实提取
- cross_doc 题需要跨文档推理
- no_answer 题期望系统拒答
- conflict 题检测跨文档矛盾信息

### US-G8 质量指标记录
作为模型运营者，我希望能记录每次基准评估的召回率、引用正确率、拒答率、耗时和失败率，并能比较不同运行的回退情况。

**验收标准：**
- `quality_metric` 表记录每次评估的 per-case 指标
- `evaluate_benchmark()` 产出聚合 QualityBenchmarkResult（含 per_category）
- `compare_runs()` 比较两次运行的回归情况
- 支持 historical_metrics 查询
