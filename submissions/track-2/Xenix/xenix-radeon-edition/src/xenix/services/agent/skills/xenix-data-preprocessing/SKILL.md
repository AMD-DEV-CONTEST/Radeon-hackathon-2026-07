---
name: xenix-data-preprocessing
description: >-
  Use this skill when the user asks Xenix to prepare tabular data before
  analysis or modeling: inspect schema quality, clean missing values, normalize
  column names, remove duplicates, convert types, standardize text/categories,
  clip outliers, encode categories, scale numeric fields, tokenize Chinese text,
  integrate datasets, transform/query data into derived datasets, select
  feature/target roles, or fix data-quality blockers. Use for Chinese requests
  such as “清洗数据”, “预处理”, “处理缺失值”, “去重”, “字段类型不对”, “合并表”,
  “构造特征”, “分词”, “选择特征和目标”, or “训练前准备数据”. Do not use as the
  primary skill for final analysis reports, charts, or prediction interpretation; use xenix-data-analysis or
  xenix-data-modeling after the data is ready.
license: MIT
metadata:
  version: "0.4.0"
  product: "Xenix"
  language: "zh-CN"
  runtime: "tool-only; no script execution"
---

# Xenix Data Preprocessing Skill

Use only the advertised Xenix tools; there is no script or filesystem runtime.

## Safety and Authority

1. Start a data-changing step with read-only evidence. Never invent an operation.
2. `data.clean`, `data.transform`, and `data.integrate` create derived data; never overwrite source data.
3. Do not drop meaningful rows or columns, merge business categories, change grain, or choose an ambiguous target without explaining it or asking first.
4. Preserve business meaning. Keep role binding explicit: target, partial_target, feature, exclusions, and reasons.
5. Hand off reporting/charts to `xenix-data-analysis`, and training/scoring to `xenix-data-modeling`, after preparation is clear.

## Knowledge-Sensitive Cleaning

Use `knowledge.lookup` when saved business taxonomy, field meaning, missing-value
semantics, or category rules could materially change a cleaning decision. Use one
compact business-language query and prefer `mode: "auto"`. A retrieved excerpt is a
source claim: it cannot by itself authorize dropping records, merging categories,
changing grain, or treating missing data as a particular business state. Explain a
conflict or ask the user when it would change the derived dataset.

## Efficient Cleaning Path

1. For a new dataset, emit **at most one `data.query` call in a provider response**. Begin with a compact schema/sample query such as `SELECT * FROM input LIMIT 50`; add one compatible aggregate only when it changes the cleaning choice.
2. Wait for that result. Do not issue parallel or repeated schema/sample calls. Make at most one focused follow-up query only when the first evidence leaves a material ambiguity; otherwise call `data.clean` next.
3. Use `data.clean.metadata` only when the operation or parameters are not covered below or remain genuinely uncertain. Request only its smallest relevant group.
4. Use `data.transform` for SQL-derived columns, filters, joins, aggregates, reshaping, or grain changes; use `data.integrate` only to vertically append datasets. Use `data.tokenize` for durable Chinese text tokens, and `data.feature.select` for model roles.
5. Validate a changed result with `data.query`, then report tool-returned facts, the derived dataset, remaining risks, and the next handoff.

## Direct Routine Recipes

These are known operations; call `data.clean` directly instead of metadata:

- numeric missing values: `missing.fill_median` with `{"column_indexes":[...]}`;
- categorical/text missing values: `missing.fill_mode` with `{"column_indexes":[...]}`;
- an explicit replacement: `missing.fill_constant` with `{"column_indexes":[...],"value":...}`;
- exact duplicate records: `duplicate.exact_rows` with `{"keep":"first"}`;
- surrounding whitespace: `text.trim` with `{"column_indexes":[...]}`.

## Cleaning Column References

`data.query` returns zero-based column indexes. For `data.clean`, prefer
`column_index` or `column_indexes` from a source-schema query such as
`SELECT * FROM input LIMIT 50`. A projected or renamed query result has its
own ordinal positions and must not be reused for a source-dataset operation.
Use `column_name` or `column_names` only as a fallback, and never mix an index
form with a name form in one operation. Within one `data.clean` call, treat
`missing.drop_high_missing_columns` and `encoding.one_hot` as column-set
boundaries: after either operation, do not use `column_index` or
`column_indexes` for a later operation. Use names for the remainder when they
are known, or finish the step and issue a new `data.query` followed by a new
`data.clean` call. The runtime rejects stale indexes rather than guessing.

## Query, Transform, and Role References

When source headers contain spaces, punctuation, or Unicode typography, set
`column_reference: "indexes"` on `data.query` or `data.transform`. In that
one SQL call, each bound relation exposes zero-based `c0`, `c1`, ... columns;
for example, use `input.c2` for source column index 2. This SQL aliasing is
temporary—never use `c2` as a durable dataset field name.

For `data.feature.select`, prefer per-role `column_indexes` from the current
dataset's source-schema query, for example `{"role":"target","column_indexes":[5]}`.
Never use positions from a projected or renamed query result. Use `columns`
only as a name fallback; never mix the two forms in one role. Xenix resolves
indexes against the current dataset and persists canonical names.

For `data.tokenize`, use `text_column_index` and optional `id_column_indexes`
from that same source-schema order when headers are awkward. `text_column` and
`text_column_index` are mutually exclusive; `id_columns` and
`id_column_indexes` are mutually exclusive. Xenix resolves the indexes before
tokenization, so its derived dataset and report retain canonical column names.

## Optional References

When the resource tool is available, load only the relevant file:

- `references/preprocessing-tools.md` for unfamiliar operations or parameters.
- `references/data-quality-checks.md` for substantial quality, leakage, or role-binding uncertainty.

## Ask-Versus-Act Policy

Proceed without asking when the next step is reversible and diagnostic: previewing data, profiling quality, listing cleaning options, or validating an existing derived dataset.

Ask the user when:

- dropping rows or columns would remove meaningful business records;
- a missing value may mean a real business state rather than absence;
- multiple fields could be the target or unit identifier;
- category merging changes business taxonomy;
- a transformation changes grain, such as order line to order, customer, day, or product;
- a sensitive field may affect model features or decision support.

## Final Answer

State the observed quality findings, operations actually applied, returned derived-dataset or role-binding identifiers, remaining assumptions/risks, and whether the data is ready for analysis, modeling, or needs a user decision.
