---
title: Cointegrated ETF Pairs Research
author: OpenAlpha Sentinel Demo Team
source_url: https://github.com/coreline-systems/AMD-AI-DevMaster-Hackathon/blob/3aba9fc095ab77157ef225a6c5f77dfa5562ffa9/fixtures/strategies/etf-pairs-trading.md
license_spdx: BSD-3-Clause
external_id: demo:etf-pairs-trading
---
# Cointegrated ETF Pairs Research / ETF 协整配对研究

This note explores market-neutral pairs trading across sector ETFs. Candidate pairs pass a rolling cointegration test; entry occurs when the spread z-score exceeds 2.2 and exit occurs below 0.5. Signals are evaluated on daily closes.

本资料研究行业 ETF 之间的市场中性配对交易。候选配对需通过滚动协整检验；价差 z-score 高于 2.2 时入场，回落到 0.5 以下时退出，信号基于日线收盘价。

## Evidence limits

The source-author backtest covers 2016 through 2024. The note does not disclose transaction costs, borrow fees, slippage, rejected orders, or how multiple-testing bias was controlled. Those omissions materially limit reproducibility.

作者声明的回测区间为 2016 至 2024 年。资料没有披露交易成本、借券费用、滑点、拒单情况或多重检验偏差的控制方法，因此可复现性有限。

## License

This project-authored demonstration fixture is released under BSD-3-Clause. It contains no third-party strategy code.

