# Technical specification — Phase C

- Level: S1
- Status: implemented

## Scope

| 模块 | 文件 | 职责 |
|------|------|------|
| `app/tools/` | `task_reader.py` | XLSX/CSV 任务读取，列名映射 |
| `app/tools/` | `task_checker.py` | 规则化核验（时间/交付物/关键词/验收标准/缺失项） |
| `app/reports/` | `generator.py` | 周报、风险 CSV、下周计划生成 |

## Implementation plan

### task_reader.py

- `read_tasks(path) → List[TaskRecord]`: 入口，根据后缀分发 XLSX/CSV 读取
- `_build_column_mapping(header) → dict`: 中英文列名 → 字段名映射
- `_build_record(mapping, row) → TaskRecord | None`: 逐行构建记录
- 依赖: `openpyxl`（XLSX）、stdlib `csv`（CSV/TSV）

### task_checker.py

- `check_task(task, evidence_texts) → CheckResult`: 入口
- `_check_time(deadline) → str`: 日期解析，支持 10+ 种格式
- `_find_completion_keywords(text) → list`: 中英文关键词检测
- `_match_acceptance_criteria(criteria, evidence) → dict`: 逐项匹配
- `_find_missing_items(task, evidence) → list`: 缺失项检测
- `_determine_rule_status(...) → str`: 规则状态推断
- `build_evaluation_prompt(cr) → str`: 构建 LLM 评估提示（预留接口）
- `parse_llm_response(resp) → dict`: 解析 LLM JSON 响应（预留接口）

### generator.py

- `evaluate_with_rules(task, evidence) → TaskEvaluation`: 纯规则评估
- `generate_weekly_report(evals, ...) → str`: Markdown 周报
- `generate_risk_csv(evals) → str`: CSV 风险清单
- `generate_next_week_plan(evals, ...) → str`: 下周计划草案

### 数据流

```
CSV/XLSX → TaskRecord[] → evidence[] → check_task() → CheckResult
                                               ↓
                                       evaluate_with_rules()
                                               ↓
                                       TaskEvaluation[]
                                          ↙    ↓    ↘
                             周报(MD)  风险(CSV)  计划(MD)
```

## 关键约束

- **验收标准核验**: `_match_acceptance_criteria` 将验收标准逐项拆分，
  按证据类别（测试/文档/报告/代码/部署/评审/验收）交叉匹配。
  如果某项标准在证据中找不到对应关键词，标记为 `not_matched`。

- **状态推断**: 规则检查结果先映射初步状态，
  「系统测试」场景：有部分证据 + 验收标准不满足 + 缺失报告 → needs_confirmation

- **下周计划**: 始终标注草案，不修改原始任务列表。

## Verification

1. `pytest tests/test_task_reports.py -v` — 所有测试通过
2. 验收场景: 「系统测试」仅有计划 + 部分记录 → needs_confirmation（非 completed）
3. 边界用例: 空文件、缺失列、特殊字符、空证据均正确处理
