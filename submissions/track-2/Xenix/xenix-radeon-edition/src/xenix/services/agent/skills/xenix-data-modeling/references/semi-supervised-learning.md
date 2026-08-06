# Semi-supervised Learning Reference

Use this file when a label field exists but only part of the data is labeled, or when labels contain values such as empty, unknown, pending, unreviewed, 待审核, 未标注.

Use `model.metadata` with `model_family=supervised` to inspect whether semi-supervised candidates such as label propagation, label spreading, or self-training are available for the current task. After choosing one candidate, call `model.metadata` again with that `model_key` before passing parameters. If no direct method is suitable, implement a conservative workflow using `data.query`, a supervised `model.train` baseline on labeled rows, `model.apply` on unlabeled rows, and high-confidence candidate pseudo-labels. Do not run iterative self-training unless the selected model tool explicitly supports it.

## Suitability checks

Use `data.query` to answer:

- Which field is the label?
- Which values mean true labels?
- Which values mean unlabeled rather than negative?
- How many labeled and unlabeled rows exist?
- Does every class have enough labeled examples?
- Is the label distribution severely imbalanced?
- Are labels likely to contain conflicts or errors?

Do not treat missing labels as negative labels unless the business semantics confirm that interpretation.

## Conservative workflow

1. Split rows into labeled and unlabeled subsets by label semantics.
2. Profile labeled class distribution.
3. Train a supervised baseline on labeled rows with `model.train`.
4. Evaluate baseline metrics on a validation/test split from labeled rows.
5. If baseline is weak, stop and recommend more manual labels.
6. If baseline is credible, use `model.apply` on unlabeled rows to get probabilities.
7. Mark only high-confidence predictions as pseudo-label candidates.
8. Send low-confidence, high-value, high-risk, or boundary cases to human review.

## Confidence policy

Default pseudo-label thresholds:

- high confidence: probability >= 0.85 or <= 0.15 for binary tasks;
- medium confidence: 0.65-0.85 or 0.15-0.35;
- low confidence: near the decision boundary.

Raise thresholds in high-risk domains. Lower thresholds only for exploratory analysis, never for automatic decisions.

## Output categories

A semi-supervised result should separate:

- true labeled rows;
- high-confidence pseudo-label candidates;
- medium-confidence review candidates;
- low-confidence manual-review rows;
- rows excluded because of missing/invalid features.

Use these phrases:

- “伪标签候选” rather than “真实标签”.
- “建议人工复核” for low confidence or high business-risk rows.
- “当前模型只适合辅助排序/筛选，不适合自动定论” when label quality is limited.

## Stop conditions

Do not proceed to pseudo-label expansion when:

- labeled sample count is too small;
- one or more classes are barely represented;
- baseline model metrics are poor;
- label semantics are ambiguous;
- feature fields do not plausibly describe the label;
- business domain requires expert review.
