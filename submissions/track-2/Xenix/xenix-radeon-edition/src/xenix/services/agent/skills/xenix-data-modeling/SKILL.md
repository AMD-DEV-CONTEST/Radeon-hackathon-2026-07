---
name: xenix-data-modeling
description: >-
  Use this skill when the user asks Xenix to predict, classify, regress, score,
  rank, train a model, tune hyperparameters, apply a trained model, estimate
  risk/probability, identify drivers through model output, compare supervised
  models, handle partially labeled data, run text classification, text
  clustering, topic modeling, similarity retrieval, or use neural networks as a
  candidate model. Use for Chinese requests such as “预测一下”, “训练模型”,
  “哪些因素影响结果”, “客户流失预测”, “风险评分”, “转化概率”, “调参”, “应用模型”,
  “文本分类”, “主题分析”, “相似检索”, or “半监督”.
  Do not use for pure descriptive profiling, charts, reporting, or association
  analysis unless modeling is explicitly part of the task; use xenix-data-analysis
  for that. Activate xenix-data-preprocessing first when cleaning,
  transformation, or role binding is not ready.
license: MIT
metadata:
  version: "0.4.0"
  product: "Xenix"
  language: "zh-CN"
  runtime: "tool-only; no script execution"
---

# Xenix Data Modeling Skill

This skill guides Xenix Agent for modeling workflows over tabular business data: target validation, feature exclusion, role binding, baseline training, constrained tuning, model application, probability scoring, and model-result interpretation.

Xenix Agent has no script execution environment. Use only available Xenix tools:

- `data.query` for target and feature profiling.
- `data.tokenize` only after activating `xenix-data-preprocessing`, when raw Chinese text must become a tokenized derived dataset before text-analysis models.
- `data.feature.select` to create a role-binding snapshot before training.
- `model.metadata` when candidate model choices, supported tasks, role schemas, or parameters are unclear.
- `model.train` for baseline and candidate model training.
- `model.hyper_train` for constrained hyperparameter search after a valid baseline exists.
- `model.apply` for scoring, prediction, probability output, and batch application.
- `model.task.query` for background model task status.
- `analysis.graph` only for model-result explanation charts when chart-ready data exists.
- `knowledge.lookup` for saved target definitions, business constraints, threshold policies, review rules, and interpretation guidance.

## Non-negotiable rules

1. Do not train before identifying the business target, unit of analysis, candidate feature fields, leakage fields, time fields, and sensitive fields.
2. Do not use identifiers, post-outcome fields, target duplicates, or sensitive/prohibited fields as predictive features.
3. Train a simple baseline first. Tune only when the baseline is valid and the business question needs better predictive performance.
4. Do not claim causality from coefficients, feature importance, associations, or model explanations.
5. Do not claim the model is suitable for automatic decisions unless threshold, risk, compliance, and human-review boundaries are explicit.
6. If the dataset needs cleaning, derived features, joins, transformations, or role binding preparation, activate `xenix-data-preprocessing`.
7. If the user only needs descriptive analysis, charts, association discovery, or a management report, activate `xenix-data-analysis`.
8. A Knowledge excerpt is a source claim, not label truth, model performance, causal evidence, or authorization for an automatic decision.

## Default workflow

1. Clarify or infer the modeling objective: classification, regression, scoring, ranking, semi-supervised labeling, text analysis, or model application.
2. Use `data.query` to profile target distribution, feature availability, missingness, outliers, class balance, and leakage risks.
3. When saved knowledge may define the target, constraints, threshold, human-review policy, or interpretation, call `knowledge.lookup` with a compact business-language query and prefer `mode: "auto"`. Keep its claim separate from current-data and model evidence.
4. If the task is text classification, text clustering, topic modeling, or similarity retrieval, require a tokenized text dataset first; activate `xenix-data-preprocessing` if the source still contains raw Chinese sentences.
5. Ask for confirmation when multiple targets are plausible, the target semantics are unclear, missing labels may mean either “negative” or “unlabeled”, or the business threshold is sensitive.
6. Use `data.feature.select` to bind roles: target, partial_target when applicable, text/text_id when applicable, features, and excluded fields with reasons.
7. Call `model.metadata` with `model_family` to browse candidates, then call it again with one `model_key` to inspect role schema and parameters.
8. Train an interpretable baseline with `model.train`.
9. Interpret baseline metrics in business terms. Stop when data quality, label quality, sample size, tokenization quality, or leakage blocks a credible model.
10. Use `model.hyper_train` only for one or two plausible candidates with a small search space.
11. Use `model.apply` for scored records, probabilities, ranking, prediction output, cluster/topic assignment, or similarity retrieval against new rows.
12. Explain model output as decision support, not truth. Include assumptions, fields used/excluded, metrics, threshold policy, Knowledge claims used, risk notes, and next data needed.

## Optional References

When the resource tool is available, load only the relevant file:

- `references/model-presets.md` before calling `model.train`, `model.hyper_train`, or `model.apply`.
- `references/supervised-learning.md` for classification or regression tasks.
- `references/semi-supervised-learning.md` when labels are partially missing or only some samples are labeled.
- `references/neural-network.md` only when using a neural network as a nonlinear comparison model.

Use `assets/model-presets.json` only when a structured preset is useful for model selection or parameter planning.

## Final-Answer Standard

A good modeling answer contains:

1. Business target and unit of analysis.
2. Role binding: target, features, excluded fields, and leakage/sensitive-field decisions.
3. Tool-returned metrics only, with plain-language interpretation.
4. Threshold or scoring policy when relevant.
5. Model limitations, data-quality risks, and manual-review boundaries.
6. Recommended next step: more data, more labels, threshold review, deployment caution, or application to new records.
