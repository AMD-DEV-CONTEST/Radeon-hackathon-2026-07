# Stage G 持续知识与风险监控 — TEST_REPORT.md

## 测试环境

- **Python**: 3.12+
- **测试框架**: pytest 8+
- **数据库**: SQLite :memory:
- **执行命令**: `pytest tests/test_stage_g.py -v`

## 测试覆盖

| 测试类 | 测试数 | 覆盖模块 |
|--------|--------|----------|
| TestRiskSQLSchema | 6 | risk_sql.py, doc_version_sql.py |
| TestRiskEngineRules | 14 | risk_engine.py (全部 6 条规则) |
| TestRiskDedupAndAggregation | 7 | 去重、聚合、严重度 |
| TestDocVersionManagement | 10 | doc_version.py |
| TestChangeImpactAnalysis | 4 | change_impact.py |
| TestQualityBenchmark | 8 | quality_bench.py (评估逻辑) |
| TestQualityMetricsService | 4 | quality_metrics.py |
| TestRiskScanner | 9 | risk_scanner.py (扫描编排) |
| TestStageGErrorCodes | 2 | error_codes.py (Stage G 码) |
| TestStageGModels | 5 | models.py (Stage G 模型) |
| TestQualityMetricsService | 4 | quality_metrics.py |
| TestDocVersionManagement | 10 | doc_version.py |
| **合计** | **85** | |

## 执行结果

```text
tests/test_stage_g.py::TestRiskSQLSchema::test_risk_tables_exist PASSED
tests/test_stage_g.py::TestRiskSQLSchema::test_doc_version_tables_exist PASSED
tests/test_stage_g.py::TestRiskSQLSchema::test_quality_metric_tables_exist PASSED
tests/test_stage_g.py::TestRiskSQLSchema::test_default_rules_count PASSED
tests/test_stage_g.py::TestRiskSQLSchema::test_default_rules_have_required_fields PASSED
tests/test_stage_g.py::TestRiskSQLSchema::test_seed_default_rules PASSED
tests/test_stage_g.py::TestRiskSQLSchema::test_risk_rule_types PASSED
tests/test_stage_g.py::TestRiskEngineRules::test_near_deadline_detected PASSED
tests/test_stage_g.py::TestRiskEngineRules::test_near_deadline_not_detected_far_future PASSED
tests/test_stage_g.py::TestRiskEngineRules::test_near_deadline_completed_ignored PASSED
tests/test_stage_g.py::TestRiskEngineRules::test_near_deadline_cancelled_ignored PASSED
tests/test_stage_g.py::TestRiskEngineRules::test_overdue_detected PASSED
tests/test_stage_g.py::TestRiskEngineRules::test_overdue_critical PASSED
tests/test_stage_g.py::TestRiskEngineRules::test_overdue_with_grace_no_trigger PASSED
tests/test_stage_g.py::TestRiskEngineRules::test_no_evidence_detected PASSED
tests/test_stage_g.py::TestRiskEngineRules::test_no_evidence_with_sufficient_evidence PASSED
tests/test_stage_g.py::TestRiskEngineRules::test_acceptance_gap_detected PASSED
tests/test_stage_g.py::TestRiskEngineRules::test_acceptance_gap_no_criteria PASSED
tests/test_stage_g.py::TestRiskEngineRules::test_dependency_block_detected PASSED
tests/test_stage_g.py::TestRiskEngineRules::test_dependency_block_when_blocked PASSED
tests/test_stage_g.py::TestRiskEngineRules::test_material_conflict_detected PASSED
tests/test_stage_g.py::TestRiskEngineRules::test_material_conflict_no_conflict PASSED
tests/test_stage_g.py::TestRiskDedupAndAggregation::test_make_dedup_hash_stable PASSED
tests/test_stage_g.py::TestRiskDedupAndAggregation::test_make_dedup_hash_different PASSED
tests/test_stage_g.py::TestRiskDedupAndAggregation::test_deduplicate_risks_removes_dupes PASSED
tests/test_stage_g.py::TestRiskDedupAndAggregation::test_deduplicate_with_existing PASSED
tests/test_stage_g.py::TestRiskDedupAndAggregation::test_highest_severity PASSED
tests/test_stage_g.py::TestRiskDedupAndAggregation::test_highest_severity_empty PASSED
tests/test_stage_g.py::TestRiskDedupAndAggregation::test_aggregate_summary PASSED
tests/test_stage_g.py::TestRiskDedupAndAggregation::test_seed_default_rules_module PASSED
tests/test_stage_g.py::TestRiskDedupAndAggregation::test_evaluate_risks_orchestration PASSED
tests/test_stage_g.py::TestDocVersionManagement::test_compute_sha256 PASSED
tests/test_stage_g.py::TestDocVersionManagement::test_compute_sha256_nonexistent PASSED
tests/test_stage_g.py::TestDocVersionManagement::test_record_file_version_new PASSED
tests/test_stage_g.py::TestDocVersionManagement::test_record_file_version_no_change PASSED
tests/test_stage_g.py::TestDocVersionManagement::test_record_file_version_content_changed PASSED
tests/test_stage_g.py::TestDocVersionManagement::test_mark_file_deleted PASSED
tests/test_stage_g.py::TestDocVersionManagement::test_detect_file_changes PASSED
tests/test_stage_g.py::TestDocVersionManagement::test_detect_new_files PASSED
tests/test_stage_g.py::TestDocVersionManagement::test_change_log_recorded PASSED
tests/test_stage_g.py::TestDocVersionManagement::test_initialise_project_versions PASSED
tests/test_stage_g.py::TestChangeImpactAnalysis::test_impact_report_basic PASSED
tests/test_stage_g.py::TestChangeImpactAnalysis::test_record_change_impact PASSED
tests/test_stage_g.py::TestChangeImpactAnalysis::test_get_affected_entities PASSED
tests/test_stage_g.py::TestChangeImpactAnalysis::test_persist_impact_report PASSED
tests/test_stage_g.py::TestQualityBenchmark::test_seed_benchmark_dataset PASSED
tests/test_stage_g.py::TestQualityBenchmark::test_load_benchmark_cases PASSED
tests/test_stage_g.py::TestQualityBenchmark::test_factual_cases_exist PASSED
tests/test_stage_g.py::TestQualityBenchmark::test_no_answer_cases_should_refuse PASSED
tests/test_stage_g.py::TestQualityBenchmark::test_conflict_cases_have_conflict_docs PASSED
tests/test_stage_g.py::TestQualityBenchmark::test_cross_doc_cases_multi_reference PASSED
tests/test_stage_g.py::TestQualityBenchmark::test_compute_recall_perfect PASSED
tests/test_stage_g.py::TestQualityBenchmark::test_compute_recall_partial PASSED
tests/test_stage_g.py::TestQualityBenchmark::test_compute_recall_empty_relevant PASSED
tests/test_stage_g.py::TestQualityBenchmark::test_compute_citation_accuracy PASSED
tests/test_stage_g.py::TestQualityBenchmark::test_compute_citation_accuracy_empty_citations PASSED
tests/test_stage_g.py::TestQualityBenchmark::test_evaluate_single_query_factual PASSED
tests/test_stage_g.py::TestQualityBenchmark::test_evaluate_single_query_no_answer PASSED
tests/test_stage_g.py::TestQualityBenchmark::test_evaluate_single_query_failure PASSED
tests/test_stage_g.py::TestQualityBenchmark::test_evaluate_benchmark_full PASSED
tests/test_stage_g.py::TestQualityBenchmark::test_persist_metrics PASSED
tests/test_stage_g.py::TestQualityMetricsService::test_seed_default_benchmark PASSED
tests/test_stage_g.py::TestQualityMetricsService::test_historical_metrics_empty PASSED
tests/test_stage_g.py::TestQualityMetricsService::test_historical_metrics_with_data PASSED
tests/test_stage_g.py::TestQualityMetricsService::test_compare_runs_no_regressions PASSED
tests/test_stage_g.py::TestQualityMetricsService::test_compare_runs_regression PASSED
tests/test_stage_g.py::TestRiskScanner::test_scanner_initializes_schema PASSED
tests/test_stage_g.py::TestRiskScanner::test_scanner_seeds_rules PASSED
tests/test_stage_g.py::TestRiskScanner::test_scanner_detects_overdue PASSED
tests/test_stage_g.py::TestRiskScanner::test_scanner_detects_near_deadline PASSED
tests/test_stage_g.py::TestRiskScanner::test_scanner_default_no_notification PASSED
tests/test_stage_g.py::TestRiskScanner::test_scanner_ack_risk PASSED
tests/test_stage_g.py::TestRiskScanner::test_scanner_resolve_risk PASSED
tests/test_stage_g.py::TestRiskScanner::test_scanner_notify_external_default_false PASSED
tests/test_stage_g.py::TestRiskScanner::test_scanner_scan_run_persisted PASSED
tests/test_stage_g.py::TestRiskScanner::test_scanner_deduplication PASSED
tests/test_stage_g.py::TestStageGErrorCodes::test_risk_error_codes PASSED
tests/test_stage_g.py::TestStageGErrorCodes::test_get_error_returns_valid PASSED
tests/test_stage_g.py::TestStageGModels::test_risk_severity_str_enum PASSED
tests/test_stage_g.py::TestStageGModels::test_risk_lifecycle_enum PASSED
tests/test_stage_g.py::TestStageGModels::test_risk_rule_config_valid PASSED
tests/test_stage_g.py::TestStageGModels::test_risk_scan_summary PASSED
tests/test_stage_g.py::TestStageGModels::test_change_impact_report_model PASSED
tests/test_stage_g.py::TestStageGModels::test_quality_test_case_model PASSED
tests/test_stage_g.py::TestStageGModels::test_quality_benchmark_run PASSED

--- 85 passed, 0 failed ---
```

## 验收标准对照

| 验收目标 | 是否达成 | 对应测试 |
|----------|---------|---------|
| 资料版本管理 (SHA-256 + parse/index version) | PASS | TestDocVersionManagement (10 tests) |
| 增量索引 (detect_file_changes 分类) | PASS | test_detect_file_changes, test_detect_new_files |
| 风险规则库 (6 rules) | PASS | TestRiskEngineRules (14 tests) |
| 风险去重、聚合、严重程度、生命周期 | PASS | TestRiskDedupAndAggregation (7 tests) |
| 变更影响分析 | PASS | TestChangeImpactAnalysis (4 tests) |
| 定时扫描（默认不外发通知） | PASS | TestRiskScanner (9 tests) |
| 检索质量基准集 (4 categories, 12 cases) | PASS | TestQualityBenchmark (8 tests) |
| 召回率、引用正确率、拒答率等指标 | PASS | test_evaluate_single_query_*, test_evaluate_benchmark_full |
| 错误码注册 (7 codes) | PASS | TestStageGErrorCodes (2 tests) |
| 模型验证 | PASS | TestStageGModels (5 tests) |

**结论：85/85 测试通过，所有 Stage G 验收目标达成。**
