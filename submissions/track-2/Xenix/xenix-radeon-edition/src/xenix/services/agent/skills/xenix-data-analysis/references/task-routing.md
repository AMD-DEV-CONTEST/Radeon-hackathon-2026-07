# Task Routing Reference

Use this file when the user request or dataset structure is ambiguous. The goal is to select one primary path and activate a narrower skill when the task is not primarily descriptive analysis.

## Skill routing

Use `xenix-data-analysis` when the main task is to understand, summarize, compare, visualize, find associations, inspect trends, or write a report.

Activate `xenix-data-preprocessing` when the next useful step is cleaning, type conversion, duplicate handling, missing-value handling, dataset integration, SQL materialization, feature construction, or role binding.

Activate `xenix-data-modeling` when the main task is prediction, classification, regression, scoring, ranking, model training, model tuning, model application, semi-supervised labeling, or model-result interpretation.

## Primary routing matrix

| Data signal | Primary path | First checks | User confirmation needed when |
|---|---|---|---|
| Data has quality blockers: missing target, bad types, duplicates, inconsistent categories, unclear grain | Preprocessing | schema, missingness, duplicates, types, category variants, role candidates | cleaning changes business meaning |
| Clear continuous business outcome: price, sales, cost, revenue, profit, score | Modeling: regression | target distribution, numeric ranges, outliers, leakage, business error tolerance | multiple continuous outcomes look plausible |
| Clear categorical or 0/1 outcome: buy, churn, respond, default, pass/fail, risk class | Modeling: classification | class distribution, imbalance, leakage, stratified split | multiple outcome fields look plausible |
| Some rows have labels and many rows are unlabeled/unknown/pending | Modeling: semi-supervised workflow | labeled/unlabeled split, label quality, baseline model | missing label could mean “negative” rather than “unlabeled” |
| One subject has multiple items: order-product, user-behavior, patient-symptom, student-course | Association / combination discovery | subject field, item field, item standardization, basket count | subject or item field is unclear |
| Time field plus metric | Trend / forecasting candidate | date range, granularity, missing periods, aggregation level | forecasting horizon or metric is unclear |
| No target, but many comparable entities: customers, products, stores, students | Descriptive segmentation or modeling handoff | entity level, numeric feature availability, actionability | segmentation purpose is unclear |
| User asks “帮我看看这个数据” | Automatic profiling and task recommendation | data overview, quality, key metrics, likely tasks | dataset has multiple equally plausible business contexts |

## Target-variable recognition

A field is a strong target candidate when:

- its name denotes an outcome: 是否购买, 响应, 流失, 违约, 转化, 销量, 价格, 利润, 评分;
- its values represent a result rather than an input descriptor;
- it is available for historical rows and can be predicted for future rows;
- it is not a direct duplicate or post-hoc explanation of another outcome field.

A field is usually not a target by default when it is:

- an ID or code;
- a stable descriptor such as region, gender, product type, customer grade;
- a raw timestamp;
- a field that only exists after the business decision has already happened.

## Unit-of-analysis recognition

Before analysis, preprocessing, modeling, or association analysis, determine the unit of analysis:

- customer-level: one row per customer or aggregate customer behavior;
- order-level: one row per order or order line;
- product-level: one row per product/SKU;
- store-level: one row per store/day/month;
- transaction-line-level: one row per item inside a transaction;
- event-level: one row per behavior, visit, or log event.

Misidentifying the unit of analysis causes incorrect metrics and leakage.

## When to prefer non-model analysis

Prefer descriptive, diagnostic, or visualization analysis instead of modeling when:

- there is no valid target variable;
- sample size is very small;
- target leakage cannot be ruled out;
- missingness or label quality blocks reliable modeling;
- the user asks for “现状、结构、趋势、分布、对比、异常” rather than prediction;
- business action can be supported by simple grouping or ranking.

When the user explicitly asks for prediction, scoring, risk probability, driver analysis through model output, or applying a model, do not keep the task in this analysis skill. Activate `xenix-data-modeling`.

When the data cannot be trusted or used because of missingness, duplicates, type problems, inconsistent categories, unclear joins, or role-binding uncertainty, activate `xenix-data-preprocessing` before continuing.

## Minimal plan format

A good plan contains:

- data scene and unit of analysis;
- selected task and rejected alternatives;
- required fields and excluded fields;
- SQL profiling checks;
- chart calls if applicable;
- handoff to preprocessing or modeling if needed;
- risk checks;
- final deliverable.
