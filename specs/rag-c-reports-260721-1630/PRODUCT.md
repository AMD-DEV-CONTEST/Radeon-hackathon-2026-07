# Phase C — 任务核验与周报生成

## 目标

从项目任务表（XLSX/CSV）读取任务记录，结合项目资料证据进行规则化核验，
输出结构化任务评估、Markdown 周报、CSV 风险清单与下周计划草案。

## 用户可见行为

### C-01 任务读取（XLSX/CSV）

- 支持 `.xlsx`、`.csv`、`.tsv` 格式
- 自动识别中/英文列名（任务名称/title、负责人/assignee、截止日期/deadline 等）
- 跳过空行与缺失标题的行
- 每个任务返回 `TaskRecord`（含 title、assignee、deadline、priority、acceptance_criteria、original_source）

### C-02 规则化核验

- **时间检查**: 对比当前日期判定 on_track/approaching/overdue/no_deadline
- **交付物检查**: 是否存在证据文本
- **完成关键词**: 检测中文（已完成、已交付、通过测试等）和英文（done、completed 等）
- **验收标准匹配**: 将验收标准逐项与证据交叉比对（按测试/文档/报告/代码/部署/评审/验收等类别）
- **缺失项识别**: 检测证据中缺少的关键输出物
- 规则结果汇总为 `CheckResult`，并映射为初步状态

### C-03 任务评估状态

支持以下 7 种状态：

| 状态 | 英文 | 含义 |
|------|------|------|
| 已完成 | completed | 验收标准全部满足，有交付物证明 |
| 基本完成 | mostly_completed | 主要标准满足，少量次要项缺失 |
| 进行中 | in_progress | 有进展证据但未完成主要验收标准 |
| 未开始 | not_started | 无任何证据/交付物 |
| 已延期 | delayed | 已超截止日期，完成度低 |
| 待确认 | needs_confirmation | 证据不充分，存在矛盾或不确定 |
| 已取消 | cancelled | 任务明确被取消 |

### C-04 Markdown 周报

- 总体概况（任务数量、各状态统计、高中风险项）
- 逐任务详情（状态、负责人、截止日期、证据摘要、风险等级、建议）
- 高风险任务重点关注区块

### C-05 CSV 风险清单

- 仅输出 medium+ 风险项
- 列: task_title、assignee、status、risk_level、risk_reason、recommendation、deadline、acceptance_criteria
- 高风险项排在前

### C-06 下周计划草案

- Markdown 格式，明确标注"草案"和"请勿直接覆盖原始任务列表"
- 按任务状态分组：需继续推进、逾期需处理、待确认、需启动
- 下周重点总结

## 验收标准

1. 任务读取：正确解析中英文列名的 XLSX 和 CSV 文件
2. 规则核验：「系统测试」仅有计划和部分记录但无最终报告时 → 判定为「待确认/进行中」，不误判为已完成
3. 周报：包含所有任务详情，高风险项有独立区块
4. 风险 CSV：仅含中高风险项，高风险排在前面
5. 下周计划：明确标注草案，不覆盖原始任务列表
6. 所有输出附来源引用（证据来源或明确标注证据缺失）

## Non-goals

- 不实现 UI 界面
- 不自动连接 LLM 做二次评估（预留了 `build_evaluation_prompt` 接口）
- 不修改原始任务文件
- 不覆盖用户数据
