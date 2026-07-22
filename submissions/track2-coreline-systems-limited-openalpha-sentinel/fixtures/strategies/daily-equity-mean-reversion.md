---
title: Daily Equity Mean Reversion
author: OpenAlpha Sentinel Demo Team
source_url: https://github.com/coreline-systems/AMD-AI-DevMaster-Hackathon/blob/3aba9fc095ab77157ef225a6c5f77dfa5562ffa9/fixtures/strategies/daily-equity-mean-reversion.md
license_spdx: MIT
external_id: demo:daily-equity-mean-reversion
---
# Daily Equity Mean Reversion / 日线股票均值回归

This educational strategy studies liquid US equities on a daily timeframe. It buys a small basket when the 5-day return z-score falls below -2 and price remains above the 200-day moving average. Positions close when the z-score returns to zero or after five sessions.

本教育策略研究流动性较高的美股日线数据。当 5 日收益率 z-score 低于 -2 且价格仍在 200 日移动平均线上方时建立小规模组合；z-score 回到零或持有五个交易日后退出。

## Research evidence

The source-author backtest covers January 2018 through December 2025. It uses point-in-time constituents and reports results separately for 2018-2019, the 2020 shock, and 2021-2025. These are author-reported research results, not independently verified performance.

作者声明的回测区间为 2018 年 1 月至 2025 年 12 月，使用当时可得的成分股，并分别披露 2018-2019、2020 冲击期和 2021-2025 的结果。本段仅是来源作者声明，并非系统独立验证的收益表现。

## Costs and risks

The test deducts 5 basis points of commission and 8 basis points of slippage per round trip. It does not model market impact. Survivorship bias, corporate actions, capacity, and delayed data availability still require independent review.

回测按每次完整交易扣除 5 个基点手续费和 8 个基点滑点，但没有模拟市场冲击。幸存者偏差、公司行动、容量与数据延迟仍需独立复核。

## License

This project-authored demonstration fixture is released under the MIT License. It contains no executable trading code.

