## Decision: Use a deterministic report endpoint and bounded synthetic market data
## Context: Dify successfully reached the backtest API, but raw JSON was unsuitable for the demo and unbounded Student-t/GARCH shocks produced infinite synthetic prices when Binance was unavailable.
## Alternatives considered: Add another Dify LLM summarization node; parse JSON in a Dify Code node; disable synthetic fallback; keep unbounded GARCH data and suppress invalid metrics.
## Reasoning: A plain-text report endpoint is deterministic, fast, and easy to reproduce. Bounding variance, per-candle returns, and horizon-level price movement fixes the data source rather than hiding bad backtest results.
## Trade-offs accepted: The fallback data is safer and more plausible but no longer represents unconstrained tail events. The Chinese report format is API-owned, so wording changes require a code update rather than prompt editing.
