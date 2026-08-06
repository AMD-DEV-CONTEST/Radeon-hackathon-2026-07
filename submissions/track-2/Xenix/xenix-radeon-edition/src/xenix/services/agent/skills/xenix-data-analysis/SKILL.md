---
name: xenix-data-analysis
description: >-
  Use this skill when the user asks Xenix to understand, profile, summarize,
  visualize, compare, segment descriptively, find associations, explain trends,
  produce a management-facing report, or apply saved business rules and experience
  to CSV, Excel, spreadsheet, or tabular business data. Use also for vague Chinese
  requests such as “帮我看看这个数据”,
  “分析一下这个表”, “做个数据分析报告”, “看趋势”, “做对比”, “词云图”, “商品组合”,
  or “哪些东西经常一起出现”. Do not use as the primary skill for
  cleaning/transforming data before analysis; activate xenix-data-preprocessing
  for that. Do not use as the primary skill for predictive model training,
  tuning, or applying models; activate xenix-data-modeling for that.
license: MIT
metadata:
  version: "0.4.0"
  product: "Xenix"
  language: "zh-CN"
  runtime: "tool-only; no script execution"
---

# Xenix Data Analysis Skill

This skill guides Xenix Agent for business-facing tabular analysis: data understanding, profiling, descriptive statistics, SQL aggregation, association discovery, visualization, interpretation, and report writing.

Xenix Agent has no script execution environment. Do not rely on Python, shell, local files, validators, or ad-hoc code. Use only available Xenix tools:

- `data.query` for schema inspection, preview rows, field summaries, small samples, and full-data computation through read-only DuckDB SQL.
- `data.transform` when a chart or report needs a durable derived table.
- `data.tokenize` only after activating `xenix-data-preprocessing`, when raw Chinese text must be segmented upstream for word clouds.
- `analysis.graph` for bounded charts or word clouds from chart-ready datasets.
- `knowledge.lookup` for saved business rules, definitions, assumptions, and experience that may change the computation or interpretation.

The language model is the orchestration and interpretation layer. The tools are the execution layer.

## Non-negotiable rules

1. Do not send full raw datasets to the language model. Work from metadata, samples, SQL aggregates, model outputs, charts, and logs.
2. Do not invent unavailable tools, scripts, local validators, external packages, or background jobs.
3. Use `data.query` only for read-only SQL. Do not use destructive SQL such as `DROP`, `DELETE`, `UPDATE`, `INSERT`, `CREATE TABLE`, or `ALTER` unless the product explicitly provides a safe temporary-output mechanism.
4. Prefer the simplest reliable analysis that answers the business question. Do not escalate to modeling to appear sophisticated.
5. Do not infer numeric results that tools did not return.
6. Never interpret correlation, association rules, or grouped differences as causality without explicit causal design.
7. If the task becomes data cleaning, feature preparation, target binding, prediction, training, tuning, or scoring, activate the narrower skill before proceeding.
8. Treat Knowledge Library excerpts as source claims, not automatic truth. Never infer a fact from retrieval rank or from the absence of a result.

## Default workflow

1. Understand the user's business intent. If the user says “帮我看看这个数据”, proceed with automatic data understanding and task planning.
2. Start with `data.query`: inspect schema, sample rows, field names, row count, and candidate semantic fields.
3. Decide whether user-specific rules, definitions, assumptions, or experience could materially change the computation or interpretation. When relevant, call `knowledge.lookup` with one compact business-language query and default `mode: "auto"`; refine only when the first result lacks a needed fact. Use `keyword` for exact terms or phrases, `semantic` when the same concept may use different wording, and `hybrid` when both signals matter. If an explicit mode is unavailable, recover with `auto` or `keyword` rather than treating the failure as no evidence.
4. Use `data.query` for profiling: missingness, cardinality, numeric ranges, categorical distributions, date ranges, duplicates, target distribution, and entity-item structure where relevant.
5. Identify the likely business scene, unit of analysis, key metrics, time fields, subject-item candidates, and data quality blockers.
6. If data quality blocks interpretation, activate `xenix-data-preprocessing`; if prediction/modeling is the true task, activate `xenix-data-modeling`.
7. For word clouds, prepare a chart-ready frequency table first. If the source is raw Chinese text, activate `xenix-data-preprocessing` so `data.tokenize` can segment upstream before `data.query` or `data.transform` aggregates `word` and `count`.
8. Load only relevant references through `agent.skill.read_reference` or `agent.skill.read_asset`.
9. Produce a compact analysis plan: selected analysis path, required fields, SQL checks, chart calls if any, expected outputs, risk checks, and whether user confirmation is needed.
10. Ask for confirmation only when the unit of analysis is ambiguous, the business metric is ambiguous, or a user-visible destructive/exporting action is requested.
11. Execute through the tools.
12. Explain returned results in management language. When Knowledge was used, distinguish what the Knowledge Library claims, what the current data computes, and what conclusion or action follows from combining them; disclose conflicts or missing evidence.
13. Include a process trace: assumptions, selected task, fields used/excluded, Knowledge excerpts used, SQL checks, charts, limitations, and report version.

## Optional references

When the resource tool is available, load only the relevant file:

- `references/task-routing.md` when the user request or dataset structure is ambiguous.
- `references/duckdb-sql-recipes.md` before writing `data.query` SQL.
- `references/visualization-vegalite.md` before calling `analysis.graph` with an ordinary Vega-Lite chart.
- `references/association-analysis.md` when data has order-product, subject-item, user-behavior, transaction-item, patient-symptom, student-course, or basket-like structure.
- `references/reporting-and-risk.md` before producing a management-facing report.

Use assets only when they match the concrete output:

- `assets/analysis-plan-template.json` for a structured plan.
- `assets/management-report-template.md` for a management-facing report.
- `assets/vegalite/*.vl.json` for chart templates.

## Ask-versus-act policy

Proceed without asking when the next step is reversible and useful: previewing data, profiling fields, drafting a candidate analysis plan, creating aggregate charts, or summarizing tool-returned evidence.

Ask the user when:

- the intended unit of analysis is unclear, such as customer, order, store, product, class, or patient;
- the business metric or comparison basis is unclear;
- the operation would overwrite, delete, export, or publish user-visible data.

## Final-answer standard

A good Xenix data-analysis answer contains these layers:

1. Data understanding: what the dataset appears to represent and what fields matter.
2. Analysis decision: what task was selected and why simpler alternatives were accepted or rejected.
3. Knowledge context, when used: the attributed source claim, conflicts, and uncertainty.
4. Computed evidence: only current-data numbers, charts, model metrics, and association rules actually returned by data/model tools.
5. Business interpretation: actions, limitations, risks, and what data would improve confidence.

Knowledge source attribution belongs in the Knowledge-context layer. It never becomes
computed evidence merely because a Tool returned the excerpt, and it never replaces
current-data evidence.

Avoid “algorithm showroom” reports. A concise report that explains business implications and limitations is better than a report that lists many models.
