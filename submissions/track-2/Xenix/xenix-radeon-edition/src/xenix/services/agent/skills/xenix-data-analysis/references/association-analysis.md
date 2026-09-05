# Association and Combination Discovery Reference

Use this file when the data has a subject-item structure: order-product, customer-behavior, patient-symptom, student-course, tourist-attraction, user-content, or similar. The business question is usually “哪些东西经常一起出现” or “出现 A 时还常出现什么”.

This workflow can be executed with `data.query` and `analysis.graph`; it does not require scripts.

For single-dataset SQL calls, use `input` as the table name. For multi-dataset calls, pass explicit `bindings` and use each `bindings[].alias`.

## Structure recognition

Identify:

- subject field: order ID, customer ID, patient ID, user ID, visit ID, class ID;
- item field: product, dish, symptom, tag, behavior, course, attraction;
- optional time window: same order, same visit, same day, same month;
- item normalization needs: synonyms, spelling variants, category granularity.

Do not run association analysis if there is no meaningful “one subject contains multiple items” structure.

## Basket profiling SQL

```sql
WITH basket_items AS (
  SELECT DISTINCT
    "{{subject_col}}" AS subject_id,
    "{{item_col}}" AS item
  FROM input
  WHERE "{{subject_col}}" IS NOT NULL
    AND "{{item_col}}" IS NOT NULL
), baskets AS (
  SELECT subject_id, COUNT(*) AS n_items
  FROM basket_items
  GROUP BY 1
)
SELECT
  COUNT(*) AS n_baskets,
  AVG(n_items) AS avg_items_per_basket,
  quantile_cont(n_items, 0.50) AS median_items_per_basket,
  MAX(n_items) AS max_items_per_basket
FROM baskets;
```

## Top items SQL

```sql
WITH basket_items AS (
  SELECT DISTINCT
    "{{subject_col}}" AS subject_id,
    "{{item_col}}" AS item
  FROM input
  WHERE "{{subject_col}}" IS NOT NULL
    AND "{{item_col}}" IS NOT NULL
)
SELECT
  item,
  COUNT(*) AS basket_count,
  ROUND(100.0 * COUNT(*) / (SELECT COUNT(DISTINCT subject_id) FROM basket_items), 2) AS basket_pct
FROM basket_items
GROUP BY 1
ORDER BY basket_count DESC
LIMIT 30;
```

## Pair association SQL

```sql
WITH basket_items AS (
  SELECT DISTINCT
    "{{subject_col}}" AS subject_id,
    CAST("{{item_col}}" AS VARCHAR) AS item
  FROM input
  WHERE "{{subject_col}}" IS NOT NULL
    AND "{{item_col}}" IS NOT NULL
), total AS (
  SELECT COUNT(DISTINCT subject_id) AS n_baskets FROM basket_items
), item_counts AS (
  SELECT item, COUNT(DISTINCT subject_id) AS item_count
  FROM basket_items
  GROUP BY 1
), pair_counts AS (
  SELECT
    a.item AS item_a,
    b.item AS item_b,
    COUNT(DISTINCT a.subject_id) AS pair_count
  FROM basket_items a
  JOIN basket_items b
    ON a.subject_id = b.subject_id
   AND a.item < b.item
  GROUP BY 1, 2
)
SELECT
  p.item_a,
  p.item_b,
  p.pair_count,
  ROUND(100.0 * p.pair_count / t.n_baskets, 2) AS support_pct,
  ROUND(100.0 * p.pair_count / ia.item_count, 2) AS confidence_a_to_b_pct,
  ROUND(100.0 * p.pair_count / ib.item_count, 2) AS confidence_b_to_a_pct,
  ROUND((p.pair_count * t.n_baskets * 1.0) / NULLIF(ia.item_count * ib.item_count, 0), 3) AS lift
FROM pair_counts p
JOIN item_counts ia ON p.item_a = ia.item
JOIN item_counts ib ON p.item_b = ib.item
CROSS JOIN total t
WHERE p.pair_count >= {{min_pair_count}}
ORDER BY lift DESC, pair_count DESC
LIMIT 50;
```

## Rule screening

Prefer rules that are:

- frequent enough to be reliable;
- have meaningful confidence;
- have lift above 1, ideally clearly above 1;
- easy to explain;
- actionable in the business context;
- not blocked by inventory, policy, compliance, or domain rules.

Filter out:

- rules based on very low counts;
- rules with common items but weak lift;
- rules that are true but useless;
- sensitive or prohibited recommendations;
- long combinations that managers cannot act on.

## Visualization

Use:

- Top-N bar chart for high-frequency items;
- heatmap for item-category combinations;
- network graph only if `analysis.graph` supports it and the rule count is small;
- scatter chart if showing support vs confidence/lift is useful.

## Interpretation language

Use business language:

- “A 和 B 经常共同出现。”
- “出现 A 的记录中，B 也出现的比例较高。”
- “lift 大于 1 表示它们的共同出现强于随机独立情况下的预期。”
- “关联不等于因果，也不代表必须推荐。”

High-risk domains such as medical, finance, education placement, and compliance review require human validation.
