# Visualization and Vega-Lite Reference

Use this file before calling `analysis.graph` with a Vega-Lite `spec`. The graph tool receives a compact Vega-Lite specification for a registered, chart-ready dataset. Xenix injects the selected dataset into the Vega-Lite spec; do not add or edit `data` or `datasets`.

Use `wordcloud_spec`, not Vega-Lite, for word clouds.

## Chart selection

| User intent | Recommended chart | Data preparation |
|---|---|---|
| 比较类别大小、Top N、排名 | horizontal bar | `GROUP BY` category, sort descending, limit 10-20 |
| 趋势、时间变化 | line chart | aggregate by day/week/month/quarter |
| 占比结构 | bar or pie only for few categories | categories should sum to a meaningful whole |
| 两个数值变量关系 | scatter | sample or aggregate if there are too many points |
| 类别 × 类别 强度 | heatmap | group by both dimensions |
| 数值分布 | histogram or boxplot | bin or compute quantiles |

## Visual quality rules

- Use a descriptive title and short subtitle when the Vega-Lite schema supports it.
- Prefer horizontal bars for more than 6 categories or long Chinese labels.
- Sort ranked charts by value descending.
- Limit category charts to Top 10-20; group the rest as “其他” when useful.
- Use readable labels: avoid raw technical column names in titles.
- Use restrained palettes. Do not overuse bright categorical colors.
- For Chinese text, prefer system fonts or `Noto Sans SC` when available.
- Avoid 3D, decorative gradients, excessive labels, and overloaded dashboards.

## Vega-Lite horizontal bar template

Use `assets/vegalite/topn-bar.vl.json` for ranked category comparisons. Prepare a registered dataset with:

```json
[
  {"category": "A", "value": 120},
  {"category": "B", "value": 96}
]
```

## Vega-Lite line chart template

Use `assets/vegalite/time-line.vl.json` for a single time-series metric. Prepare a registered dataset with:

```json
[
  {"period": "2026-01", "value": 1200},
  {"period": "2026-02", "value": 1380}
]
```

## Vega-Lite heatmap template

Use `assets/vegalite/heatmap.vl.json` for two categorical dimensions and one measure. Prepare a registered dataset with:

```json
[
  {"x": "渠道A", "y": "品类1", "value": 42},
  {"x": "渠道B", "y": "品类1", "value": 31}
]
```

## Common interpretation phrases

- “这个图展示的是当前口径下的汇总结果，不表示因果。”
- “Top N 之外的长尾类别没有消失，只是为了阅读性被省略。”
- “趋势图反映的是按当前口径汇总后的变化，是否为真实季节性还需要更长时间跨度验证。”
