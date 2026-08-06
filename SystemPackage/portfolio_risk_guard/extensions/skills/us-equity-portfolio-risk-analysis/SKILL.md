---
name: us-equity-portfolio-risk-analysis
description: Validates U.S. equity holdings and measures concentration, volatility, drawdown, S&P 500 beta, correlation, and user-specified market stress scenarios.
---
# U.S. Equity Portfolio Risk Analysis

## Use This Skill
Use this workflow for risk measurement of explicit U.S. equity holdings. It does not connect to brokers, execute trades, or promise future performance.

## Input Rules
- Each position must use a valid U.S. equity ticker.
- Every position must consistently provide either `weight` or `shares`.
- `cost_price` is optional and must be positive when present.
- Run only stress scenarios explicitly requested by the user.
- Apply qualitative risk labels only against thresholds supplied by the user or cited from mounted policy material.

## Workflow
1. Read any portfolio file into structured holdings; never pass a file path as the tool input.
2. Call `analyze_us_equity_portfolio` to retrieve Yahoo Finance adjusted history, align trading dates, calculate portfolio statistics and S&P 500 beta, and preserve all warnings.
3. If internal policy governs thresholds or reporting, search knowledge and cite the matched rules.
4. Explain concentration, return, volatility, maximum drawdown, beta, position-level risk, highest correlation, and each requested S&P 500 stress scenario.
5. Separate historical measurement, beta-based estimates, analytical judgment, and limitations.

## Output Standard
- State the holding basis, sample period, observation count, benchmark, source, and adjustment method.
- Preserve every warning and do not calculate a misleading partial portfolio when a holding lacks valid history.
- Explain that beta stress results are approximations, not forecasts.
- Do not assign unsupported risk categories or issue deterministic trade instructions.
