# DuckDB SQL Recipes for `data.query`

Use this file before writing `data.query` or `data.transform` calls. These are templates. Replace `{{column}}` placeholders with exact column names observed through `data.query`.

For SQL table names, follow the tool contract:

- with one `dataset_id`, use `input` as the table name;
- with multiple datasets, pass `bindings` and use each `bindings[].alias` as the table name;
- do not use the dataset display name or file name as the SQL table name unless you explicitly set it as a binding alias.

## Safety and style

- Use read-only `SELECT` queries and CTEs.
- Quote unusual column names with double quotes: `"月收入"`.
- Never quote string values with double quotes; use single quotes.
- Use `SELECT *` only for tiny bounded previews through `data.query`.
- Use `TRY_CAST` for uncertain numeric/date fields.
- Normalize blank strings when checking missingness: `NULLIF(TRIM(CAST("col" AS VARCHAR)), '')`.
- Return chart-ready result tables: small, aggregated, named columns.

## Basic dataset size

```sql
SELECT COUNT(*) AS n_rows
FROM input;
```

## Full-row duplicate count

```sql
WITH unique_rows AS (
  SELECT DISTINCT *
  FROM input
)
SELECT
  (SELECT COUNT(*) FROM input) AS n_rows,
  (SELECT COUNT(*) FROM unique_rows) AS n_unique_rows,
  (SELECT COUNT(*) FROM input) - (SELECT COUNT(*) FROM unique_rows) AS n_duplicate_rows;
```

## Missingness for selected columns

```sql
SELECT
  COUNT(*) AS n_rows,
  SUM(CASE WHEN "{{col_a}}" IS NULL OR NULLIF(TRIM(CAST("{{col_a}}" AS VARCHAR)), '') IS NULL THEN 1 ELSE 0 END) AS missing_col_a,
  ROUND(100.0 * SUM(CASE WHEN "{{col_a}}" IS NULL OR NULLIF(TRIM(CAST("{{col_a}}" AS VARCHAR)), '') IS NULL THEN 1 ELSE 0 END) / COUNT(*), 2) AS missing_col_a_pct,
  SUM(CASE WHEN "{{col_b}}" IS NULL OR NULLIF(TRIM(CAST("{{col_b}}" AS VARCHAR)), '') IS NULL THEN 1 ELSE 0 END) AS missing_col_b,
  ROUND(100.0 * SUM(CASE WHEN "{{col_b}}" IS NULL OR NULLIF(TRIM(CAST("{{col_b}}" AS VARCHAR)), '') IS NULL THEN 1 ELSE 0 END) / COUNT(*), 2) AS missing_col_b_pct
FROM input;
```

## Cardinality and distinct ratio

```sql
SELECT
  COUNT(*) AS n_rows,
  COUNT(DISTINCT "{{column}}") AS n_distinct,
  ROUND(1.0 * COUNT(DISTINCT "{{column}}") / NULLIF(COUNT(*), 0), 4) AS distinct_ratio
FROM input;
```

Use this to identify IDs, high-cardinality categoricals, and candidate target fields.

## Numeric profile

```sql
SELECT
  COUNT(*) AS n_rows,
  COUNT("{{numeric_col}}") AS n_non_null,
  MIN(TRY_CAST("{{numeric_col}}" AS DOUBLE)) AS min_value,
  quantile_cont(TRY_CAST("{{numeric_col}}" AS DOUBLE), 0.25) AS q1,
  quantile_cont(TRY_CAST("{{numeric_col}}" AS DOUBLE), 0.50) AS median,
  quantile_cont(TRY_CAST("{{numeric_col}}" AS DOUBLE), 0.75) AS q3,
  MAX(TRY_CAST("{{numeric_col}}" AS DOUBLE)) AS max_value,
  AVG(TRY_CAST("{{numeric_col}}" AS DOUBLE)) AS mean_value,
  STDDEV_SAMP(TRY_CAST("{{numeric_col}}" AS DOUBLE)) AS std_value
FROM input
WHERE TRY_CAST("{{numeric_col}}" AS DOUBLE) IS NOT NULL;
```

## IQR outlier count

```sql
WITH q AS (
  SELECT
    quantile_cont(TRY_CAST("{{numeric_col}}" AS DOUBLE), 0.25) AS q1,
    quantile_cont(TRY_CAST("{{numeric_col}}" AS DOUBLE), 0.75) AS q3
  FROM input
  WHERE TRY_CAST("{{numeric_col}}" AS DOUBLE) IS NOT NULL
), scored AS (
  SELECT
    TRY_CAST("{{numeric_col}}" AS DOUBLE) AS x,
    q.q1,
    q.q3,
    q.q3 - q.q1 AS iqr
  FROM input, q
  WHERE TRY_CAST("{{numeric_col}}" AS DOUBLE) IS NOT NULL
)
SELECT
  COUNT(*) AS n_non_null,
  SUM(CASE WHEN x < q1 - 1.5 * iqr OR x > q3 + 1.5 * iqr THEN 1 ELSE 0 END) AS n_iqr_outliers,
  ROUND(100.0 * SUM(CASE WHEN x < q1 - 1.5 * iqr OR x > q3 + 1.5 * iqr THEN 1 ELSE 0 END) / COUNT(*), 2) AS outlier_pct
FROM scored;
```

## Categorical top values

```sql
SELECT
  COALESCE(NULLIF(TRIM(CAST("{{category_col}}" AS VARCHAR)), ''), '<missing>') AS category,
  COUNT(*) AS n,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct
FROM input
GROUP BY 1
ORDER BY n DESC
LIMIT 20;
```

## Classification target distribution

```sql
SELECT
  COALESCE(NULLIF(TRIM(CAST("{{target_col}}" AS VARCHAR)), ''), '<missing>') AS target_class,
  COUNT(*) AS n,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct
FROM input
GROUP BY 1
ORDER BY n DESC;
```

A class below roughly 5% is a strong imbalance signal. Do not rely on accuracy alone.

## Regression target profile

```sql
SELECT
  COUNT(*) AS n_rows,
  COUNT(TRY_CAST("{{target_col}}" AS DOUBLE)) AS n_valid_target,
  MIN(TRY_CAST("{{target_col}}" AS DOUBLE)) AS min_target,
  quantile_cont(TRY_CAST("{{target_col}}" AS DOUBLE), 0.25) AS q1,
  quantile_cont(TRY_CAST("{{target_col}}" AS DOUBLE), 0.50) AS median,
  quantile_cont(TRY_CAST("{{target_col}}" AS DOUBLE), 0.75) AS q3,
  MAX(TRY_CAST("{{target_col}}" AS DOUBLE)) AS max_target,
  AVG(TRY_CAST("{{target_col}}" AS DOUBLE)) AS mean_target,
  STDDEV_SAMP(TRY_CAST("{{target_col}}" AS DOUBLE)) AS std_target
FROM input
WHERE TRY_CAST("{{target_col}}" AS DOUBLE) IS NOT NULL;
```

## Date range and granularity check

```sql
SELECT
  MIN(TRY_CAST("{{date_col}}" AS TIMESTAMP)) AS min_time,
  MAX(TRY_CAST("{{date_col}}" AS TIMESTAMP)) AS max_time,
  COUNT(DISTINCT DATE_TRUNC('day', TRY_CAST("{{date_col}}" AS TIMESTAMP))) AS n_days,
  COUNT(DISTINCT DATE_TRUNC('month', TRY_CAST("{{date_col}}" AS TIMESTAMP))) AS n_months
FROM input
WHERE TRY_CAST("{{date_col}}" AS TIMESTAMP) IS NOT NULL;
```

## Time trend aggregate

```sql
SELECT
  DATE_TRUNC('{{day_or_week_or_month}}', TRY_CAST("{{date_col}}" AS TIMESTAMP)) AS period,
  COUNT(*) AS n_records,
  SUM(TRY_CAST("{{metric_col}}" AS DOUBLE)) AS total_metric,
  AVG(TRY_CAST("{{metric_col}}" AS DOUBLE)) AS avg_metric
FROM input
WHERE TRY_CAST("{{date_col}}" AS TIMESTAMP) IS NOT NULL
GROUP BY 1
ORDER BY 1;
```

## Correlation between two numeric fields

```sql
SELECT
  corr(TRY_CAST("{{x_col}}" AS DOUBLE), TRY_CAST("{{y_col}}" AS DOUBLE)) AS pearson_corr,
  COUNT(*) AS n_pairs
FROM input
WHERE TRY_CAST("{{x_col}}" AS DOUBLE) IS NOT NULL
  AND TRY_CAST("{{y_col}}" AS DOUBLE) IS NOT NULL;
```

Correlation is not causation. Use it for screening, not final proof.

## Subject-item structure check

```sql
SELECT
  COUNT(DISTINCT "{{subject_col}}") AS n_subjects,
  COUNT(DISTINCT "{{item_col}}") AS n_items,
  COUNT(*) AS n_rows,
  ROUND(1.0 * COUNT(*) / NULLIF(COUNT(DISTINCT "{{subject_col}}"), 0), 2) AS avg_rows_per_subject
FROM input
WHERE "{{subject_col}}" IS NOT NULL
  AND "{{item_col}}" IS NOT NULL;
```

## Items per basket

```sql
WITH baskets AS (
  SELECT
    "{{subject_col}}" AS subject_id,
    COUNT(DISTINCT "{{item_col}}") AS n_items
  FROM input
  WHERE "{{subject_col}}" IS NOT NULL
    AND "{{item_col}}" IS NOT NULL
  GROUP BY 1
)
SELECT
  COUNT(*) AS n_baskets,
  AVG(n_items) AS avg_items_per_basket,
  quantile_cont(n_items, 0.50) AS median_items_per_basket,
  MAX(n_items) AS max_items_per_basket
FROM baskets;
```

## Word-frequency table for word cloud from tokenized field

Prefer the output shape `word`, `count` for `analysis.graph` when using `wordcloud_spec`.
If the source text is raw Chinese sentences or paragraphs, do not treat `countpattern`-style tokenization as a valid shortcut; segment upstream first or work from existing token/tag rows.

If the dataset already has one token/word/tag per row:

```sql
SELECT
  LOWER(TRIM(CAST("{{word_col}}" AS VARCHAR))) AS word,
  COUNT(*) AS count
FROM input
WHERE NULLIF(TRIM(CAST("{{word_col}}" AS VARCHAR)), '') IS NOT NULL
GROUP BY 1
HAVING LENGTH(word) >= 2
ORDER BY count DESC
LIMIT 80;
```

If one field contains delimited tags or keywords:

```sql
WITH exploded AS (
  SELECT
    LOWER(TRIM(token)) AS word
  FROM input,
  UNNEST(
    str_split(
      regexp_replace(COALESCE(CAST("{{tag_col}}" AS VARCHAR), ''), '[，;；、|/]+', ',', 'g'),
      ','
    )
  ) AS t(token)
)
SELECT
  word,
  COUNT(*) AS count
FROM exploded
WHERE word IS NOT NULL
  AND word <> ''
  AND LENGTH(word) >= 2
GROUP BY 1
ORDER BY count DESC
LIMIT 80;
```
