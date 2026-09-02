# Phase C — 测试报告

- Level: S1
- Status: verified

## 测试结果

```
tests/test_task_reports.py ............................... 79 passed in 1.42s
verify_phase_c.py ............................... 7/7 验收通过
validate_specs.py --strict ..................... errors=0
```

全量: 79 passed（含 17 个 LLM 集成异步测试）

## 覆盖详情

| 模块 | 测试数 | 覆盖点 |
|------|:-----:|--------|
| TaskChecker — 时间检查 | 6 | on_track/approaching/overdue/no_deadline、10+ 日期格式解析 |
| TaskChecker — 完成关键词 | 5 | 中文（已完成/已交付/通过测试等）、英文（done/completed 等） |
| TaskChecker — 取消/废弃 | 4 | deprecated、废弃、已取消等关键词 |
| TaskChecker — 验收标准匹配 | 8 | 精确匹配、语义匹配（char-all）、连接词排除、not_matched |
| TaskChecker — 缺失项 | 4 | 缺失报告、缺失代码、缺失评审、无缺失 |
| TaskChecker — 状态推断 | 12 | 7 种状态全覆盖、partial_kw 降级、>0.5 阈值、优先级链 |
| TaskChecker — 部分进度 | 4 | 进行中 (50%)、编写中、部分完成关键词 7 种模式 |
| Generator — 状态映射 | 3 | risk_level + risk_reason 全覆盖 |
| Generator — LLM 集成 | 17 | mock client、prompt 构造、异步解析、回退降级 |
| Generator/集成 | 10 | 周报 Markdown、风险 CSV、下周计划、来源引用、边界用例 |
| 边界 | 6 | 空输入、缺失列、特殊字符、空证据、超长文本 |

**总计: 79 个测试**

## 验收指标达成

1. ✅ 任务读取：中英文列名 XLSX/CSV 正确解析
2. ✅ 规则核验：「系统测试」仅有计划和部分记录 → needs_confirmation（非 completed）
3. ✅ 周报：包含全部任务详情，高风险项独立区块
4. ✅ 风险 CSV：仅含中高风险，高风险排前
5. ✅ 下周计划：明确标注草案，不覆盖原始任务
6. ✅ 输出附来源引用或缺失标注

## 7 种状态全覆盖

| 状态 | 测试用例 | 覆盖 |
|:---|:---|:---:|
| completed | 全 AC 匹配 + 交付物 | ✅ |
| mostly_completed | >50% AC + 无 partial | ✅ |
| in_progress | 有进展但 AC 不足 | ✅ |
| not_started | 无证据 | ✅ |
| delayed | overdue + 完成度低 | ✅ |
| needs_confirmation | 证据不充分/partial+missing | ✅ |
| cancelled | 废弃关键词 | ✅ |

## LLM 集成架构

```
规则引擎 (check_task) → status 已确定
         │
         ▼
evaluate_with_llm()
    ├─ 规则状态不变（不交给 LLM 判定）
    ├─ build_explanation_prompt() → status + 任务/证据/规则结果
    └─ LLM 调用 → 仅输出 explanation + risk_reason + recommendation
         │
         └─ 失败回退 → 纯规则 fallback（透明降级）
```

## 如何运行

```bash
# 核心测试
pytest tests/test_task_reports.py -q --tb=short

# 全场景验收
python scripts/verify_phase_c.py

# 规范检查
python scripts/validate_specs.py --strict
```
