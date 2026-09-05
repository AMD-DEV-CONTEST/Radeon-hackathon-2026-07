# Reporting and Risk Reference

Read this file before producing a final management-facing report.

## Report structure

A good report should include:

1. Data overview: source, row count, field count, time range, unit of analysis.
2. Business scene: likely domain, business object, key metrics.
3. Data quality: missingness, duplicates, outliers, type issues, category inconsistencies, leakage risks.
4. Analysis task: selected task and reason; rejected alternatives when relevant.
5. Method: SQL aggregations, charts, model training, model tuning, or association logic actually used.
6. Results: only tool-returned numbers, charts, metrics, and rules.
7. Business interpretation: what the result may mean and what action it supports.
8. Risk and limitations: data, method, model, causality, compliance, and manual-review boundaries.
9. Next data to collect: fields or labels that would improve confidence.
10. Process trace: assumptions, fields used/excluded, tool calls, parameters, thresholds, and version.

## Claim audit checklist

Before finalizing, check every major claim:

- Is it directly supported by a tool result?
- Is it an interpretation rather than a computed fact?
- Is uncertainty stated where needed?
- Could it be mistaken for causality?
- Does it overstate model reliability?
- Does it imply automatic decision-making without review?
- Does it rely on fields that may be sensitive or prohibited?
- Does it hide data-quality problems?

## Dangerous phrases to avoid

Avoid or qualify:

- “证明了”
- “导致”
- “一定会”
- “可以直接自动决策”
- “模型已经完全准确”
- “神经网络更高级，所以更好”
- “伪标签就是标签”
- “关联规则说明 A 会导致 B”

Safer alternatives:

- “在当前数据中呈现出相关关系”
- “模型主要依赖这些变量进行预测”
- “更适合用于排序/筛选/预警”
- “建议人工复核后使用”
- “该结论依赖当前数据口径”

## Classification risk notes

Mention threshold tradeoffs. If the target is imbalanced, explain why accuracy may be misleading. For marketing, discuss contact cost and coverage. For risk, discuss false negatives and manual review.

## Regression risk notes

Translate MAE/RMSE into business units. Explain whether the error is acceptable for the intended decision. Check large residuals and segment-level errors.

## Association risk notes

State clearly: association is not causation. Rules may reflect common items, seasonality, product placement, or sampling bias. Recommendations should be tested and checked against business constraints.

## Semi-supervised risk notes

Separate real labels from pseudo-label candidates. Low-confidence samples should be reviewed. If baseline performance is weak, do not expand pseudo-label use.

## Neural-network risk notes

Explain why it was tried, whether it improved over the baseline, and whether the predictive lift is worth weaker interpretability.
