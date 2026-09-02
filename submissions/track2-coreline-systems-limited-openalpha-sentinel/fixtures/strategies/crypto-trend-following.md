---
title: Crypto Volatility-Scaled Trend Following
author: OpenAlpha Sentinel Demo Team
source_url: https://github.com/coreline-systems/AMD-AI-DevMaster-Hackathon/blob/3aba9fc095ab77157ef225a6c5f77dfa5562ffa9/fixtures/strategies/crypto-trend-following.md
license_spdx: Apache-2.0
external_id: demo:crypto-trend-following
---
# Crypto Volatility-Scaled Trend Following / 加密资产波动率缩放趋势策略

This research note describes a daily momentum strategy for BTC and ETH. A long signal requires the 20-day EMA to exceed the 100-day EMA and price to break the prior 20-day high. Exposure is scaled down when 30-day realized volatility rises.

本研究资料描述 BTC 与 ETH 的日线动量策略。当 20 日 EMA 高于 100 日 EMA 且价格突破此前 20 日高点时产生做多信号；30 日已实现波动率上升时降低仓位。

## Test window and execution assumptions

The source-author test spans July 2020 through June 2025. It includes a 10 basis point fee and 15 basis points of slippage for each round trip. Funding, exchange failure, custody risk, and taxes are not modeled.

作者声明的测试区间为 2020 年 7 月至 2025 年 6 月。每次完整交易计入 10 个基点手续费与 15 个基点滑点，但未模拟资金费率、交易所故障、托管风险和税费。

## License

This project-authored demonstration fixture is available under Apache-2.0. It is a research description and does not place orders.

