---
name: us-equity-market-briefing
description: Produces a traceable pre-market, intraday, or closing U.S. equity brief from current structured market data and sends it only after explicit user confirmation.
---
# U.S. Equity Market Briefing

## Use This Skill
Use this workflow for a U.S. equity market overview, pre-market note, intraday update, closing review, or market-brief email. It does not execute trades, predict guaranteed returns, or present analysis as real-time fact.

## Workflow
1. Confirm the requested session, date, audience, and delivery format. Ask when timing or delivery intent materially changes the result.
2. Call `get_us_market_snapshot` before stating current index levels or market movers. Preserve `observed_at`, `source`, `status`, all `warnings`, and `provider_diagnostics`.
3. Use web search only for news, filings, catalysts, and independent cross-checking. Clearly distinguish Yahoo Finance structured data, SEC disclosures, and web evidence.
4. Build the brief around major indexes, leading and declining equities, most-active names, notable evidence, data limitations, and risk disclosures.
5. Save requested workspace artifacts with file tools. Call `send_market_brief_email` only after recipients, subject, and body are explicitly confirmed.

## Output Standard
- State the market session and observation timestamp.
- Cite the structured data source and preserve provider warnings.
- Separate measured facts from interpretation.
- Explain unavailable or partial data rather than filling gaps from memory.
- End with a research-only, non-investment-advice disclosure.
