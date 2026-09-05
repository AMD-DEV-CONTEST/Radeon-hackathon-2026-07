# Data Quality Checks Reference

Use this file before cleaning, transforming, or creating model role bindings. The goal is to make data readiness explicit before downstream analysis or modeling.

## Quality Dimensions

Check these dimensions in order:

1. Row grain: one row per what? Customer, order, order line, product, day, event, store, class, patient, or another business object.
2. Keys and identifiers: uniqueness, duplicate keys, missing keys, and whether IDs are meaningful features or only record handles.
3. Missingness: missing percentage by field, missing target/label rows, blank strings, and sentinel values such as unknown, N/A, 待定, 未填.
4. Type quality: numeric fields stored as text, dates stored in multiple formats, boolean fields encoded inconsistently.
5. Category quality: spelling variants, whitespace, case variants, mixed languages, overly rare categories, and category drift.
6. Numeric quality: impossible values, extreme outliers, unit mixing, negative values where impossible, zero inflation.
7. Time quality: date range, missing periods, duplicated timestamps, future dates, and time leakage.
8. Leakage: fields created after the target outcome, direct duplicates of the target, labels embedded in text, and status fields that reveal the answer.
9. Sensitivity: protected or risky fields that should not drive automated decisions.
10. Readiness: whether the dataset is ready for analysis, ready for modeling, or blocked.

## Common SQL Check Shapes

Use `data.query` for evidence before any cleaning operation.

For a single registered dataset, Xenix exposes the SQL table as `input`. For multiple datasets, use `data.query` or `data.transform` `bindings` and refer to each explicit binding alias. Do not use dataset display names as SQL table names.

Missingness:

```sql
SELECT
  COUNT(*) AS n_rows,
  SUM(CASE WHEN "{{column}}" IS NULL OR NULLIF(TRIM(CAST("{{column}}" AS VARCHAR)), '') IS NULL THEN 1 ELSE 0 END) AS n_missing,
  ROUND(100.0 * SUM(CASE WHEN "{{column}}" IS NULL OR NULLIF(TRIM(CAST("{{column}}" AS VARCHAR)), '') IS NULL THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) AS missing_pct
FROM input;
```

Distinct ratio:

```sql
SELECT
  COUNT(*) AS n_rows,
  COUNT(DISTINCT "{{column}}") AS n_distinct,
  ROUND(1.0 * COUNT(DISTINCT "{{column}}") / NULLIF(COUNT(*), 0), 4) AS distinct_ratio
FROM input;
```

Category variants:

```sql
SELECT
  TRIM(CAST("{{category_col}}" AS VARCHAR)) AS category_value,
  COUNT(*) AS n_rows
FROM input
WHERE "{{category_col}}" IS NOT NULL
GROUP BY 1
ORDER BY n_rows DESC
LIMIT 50;
```

Numeric range:

```sql
SELECT
  COUNT(*) AS n_rows,
  MIN(TRY_CAST("{{numeric_col}}" AS DOUBLE)) AS min_value,
  quantile_cont(TRY_CAST("{{numeric_col}}" AS DOUBLE), 0.50) AS median_value,
  MAX(TRY_CAST("{{numeric_col}}" AS DOUBLE)) AS max_value,
  AVG(TRY_CAST("{{numeric_col}}" AS DOUBLE)) AS mean_value
FROM input
WHERE TRY_CAST("{{numeric_col}}" AS DOUBLE) IS NOT NULL;
```

Duplicate key:

```sql
SELECT
  "{{key_col}}" AS key_value,
  COUNT(*) AS n_rows
FROM input
WHERE "{{key_col}}" IS NOT NULL
GROUP BY 1
HAVING COUNT(*) > 1
ORDER BY n_rows DESC
LIMIT 50;
```

## Cleaning Decision Rules

- Missing target values block supervised modeling unless the task is semi-supervised.
- Missing feature values may be imputed, encoded as missingness indicators, or excluded depending on meaning and rate.
- High-cardinality IDs should usually be excluded from modeling.
- Outlier clipping is acceptable only when the value is implausible or when robust modeling needs bounded influence; document the threshold.
- Category merging is a business taxonomy decision when categories have semantic differences.
- Type conversion should preserve invalid values for audit when the tool reports conversion failures.
- Row dropping requires user confirmation when records are business-significant.

## Handoff Criteria

Ready for analysis:

- row grain is known;
- key metrics and dimensions are readable;
- major missingness and duplicate risks are stated.

Ready for modeling:

- target semantics are clear;
- target distribution is profiled;
- features are available before the outcome;
- leakage fields are excluded;
- role binding is created or ready to create.

Blocked:

- unit of analysis is unknown;
- target is missing or ambiguous;
- key fields cannot be parsed;
- cleaning would require business choices the user has not made.
