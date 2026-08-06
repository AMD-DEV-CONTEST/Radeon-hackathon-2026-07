# Preprocessing Tool Contract

Use this file before mapping data preparation work to Xenix tools. Xenix Agent has no script runtime. Every full-data operation must be expressed through product tools.

## Tool Responsibilities

### `data.query`

Use for read-only inspection and quality checks:

- schema projection and preview rows;
- row and column counts;
- missingness;
- duplicate counts;
- cardinality and distinct ratios;
- numeric ranges and outliers;
- category frequency and category variants;
- date parseability and time range;
- target/feature profiling before role binding;
- validation after cleaning or transformation.

Do not use destructive SQL. Prefer CTEs. `data.query` results are replayed as Xenix Table Text: read the metadata first, then the preview table or records block.
For an Agent pass, start with one compact schema/sample query rather than
parallel or repeated metadata queries. Batch related aggregate checks in one
CTE/projection, then make a single focused follow-up only when the result makes
the cleaning decision materially ambiguous.

When headers contain spaces, punctuation, or Unicode typography, set
`column_reference: "indexes"`. In that one query, each bound relation exposes
zero-based SQL aliases `c0`, `c1`, ... instead of source names; use
`input.c2` for source index 2. This mode is query-local.

### `data.integrate`

Use only when multiple registered datasets should be vertically appended into one generated dataset. The current tool accepts `dataset_ids` and an optional `name`; it does not accept join keys, join type, or column conflict rules.

Before using it, confirm:

- rows from all inputs share the same or intentionally compatible grain;
- stacking rows is the intended operation;
- column differences are acceptable for the generated combined table.

Do not use `data.integrate` for horizontal joins. For joins, feature construction, reshaping, or grain changes, use `data.transform` with multiple `bindings`.

### `data.clean.metadata`

Use only when `data.clean` operation names or parameters are uncertain. Request
the smallest relevant `groups` list. It returns a compact operation catalog,
including the column-reference legend; it does not change data.

### `data.clean`

Use for predefined atomic cleaning operations on one registered dataset:

- schema normalization;
- duplicate handling;
- missing-value handling;
- high-missing-column handling;
- type conversion;
- text standardization;
- validation;
- outlier clipping;
- categorical encoding;
- numeric scaling.

If `operations` is absent or empty, no cleaning happens. Do not use `data.clean` as a vague instruction such as “clean everything”; provide explicit operations and parameters.

`data.query` returns zero-based column indexes. Prefer `column_index` or
`column_indexes` in cleaning parameters, but take them only from a
source-schema query such as `SELECT * FROM input LIMIT 50`; a projection or
rename has result-local ordinal positions. `column_name` and `column_names` are
fallback forms. Provide exactly one form for a selected field set—never mix
index and name references in one operation. In the same call, do not carry
indexes past `missing.drop_high_missing_columns` or `encoding.one_hot`, since
those operations may remove or add columns. Use known column names for later
operations, or run a new `data.query` and then a new `data.clean` call against
the derived dataset; stale indexes are rejected at runtime. Legacy `column`
and `columns` name forms remain accepted for compatibility.

### `data.tokenize`

Use for service-owned Chinese text segmentation when raw text must become a durable derived dataset:

- upstream preparation for word clouds;
- text classification, text clustering, topic modeling, or similarity retrieval;
- token-preserving analysis that should not be re-segmented ad hoc in later tools.

The current tool accepts one text column plus optional identifier columns and
one Xenix-owned profile, `zh_business_v1`. For difficult headers, use the
source-schema zero-based `text_column_index` and optional `id_column_indexes`
instead of names. Provide exactly one text-selector form and at most one
identifier-selector form; never reuse a projected query result's ordinal.
Xenix resolves indexes before tokenization, and its report retains canonical
column names.

Choose:

- `output=token_text` to preserve source rows and append `token_text` plus `token_count`;
- `output=token_rows` to explode one token per row with `source_row_number`, optional identifiers, `token_index`, and `token`.

Do not treat `data.tokenize` as a generic tokenizer wrapper. It does not expose raw tokenizer parameters or arbitrary language profiles in the current slice.

### `data.transform`

Use for SQL-derived datasets:

- filtering rows;
- selecting or renaming columns;
- deriving calculated fields;
- joining or reshaping data;
- grouping or aggregating to a new grain;
- preparing model-ready or chart-ready derived datasets.

`data.transform` materializes a derived dataset. Use `dataset_id` for one input aliased as `input`, or `bindings` for multiple inputs with explicit SQL aliases. Use `data.query` first when only diagnostic evidence is needed.

`data.transform` also accepts `column_reference: "indexes"` with the same
query-local `c0`, `c1`, ... aliases. Give output columns explicit business
names before materializing a derived dataset.

### `data.feature.select`

Use before modeling to create a durable role-binding snapshot. Bind:

- `target` for supervised targets;
- `partial_target` for semi-supervised labels;
- `feature` for usable explanatory fields;
- exclusions through explicit reasoning in the surrounding answer.

Do not include identifiers, post-outcome fields, target duplicates, or sensitive/prohibited fields as predictive features.

Prefer each role's zero-based `column_indexes` from a source-schema
`SELECT * FROM input` query; projected/renamed result positions are not source
indexes. Xenix resolves them against the current dataset schema and persists
canonical names. Use `columns` only as a fallback and never mix names with
indexes in one role.

## Planning Pattern

1. `data.query` to inspect schema, preview rows, quality, and candidate roles.
2. `data.clean.metadata` only when the relevant operation or parameter is uncertain.
3. `data.clean` for explicit atomic cleaning.
4. `data.tokenize` when raw Chinese text must be segmented into a stable derived dataset.
5. `data.transform` for derived features, joins, grain changes, and chart/model-ready datasets.
6. `data.feature.select` when handing off to modeling.
7. `data.query` to validate the result.

## Output Discipline

For every preprocessing operation, record:

- source dataset id;
- derived dataset id or binding id returned by the tool;
- fields changed;
- rows or values affected when the tool reports them;
- assumptions;
- remaining blockers.
