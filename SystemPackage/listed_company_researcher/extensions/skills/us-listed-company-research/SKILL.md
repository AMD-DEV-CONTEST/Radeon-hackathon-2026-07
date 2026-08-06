---
name: us-listed-company-research
description: Performs evidence-based research on one U.S.-listed company using public market data, SEC disclosures, and user-provided material while separating facts from analysis.
---
# U.S. Listed Company Research

## Use This Skill
Use this workflow for company research, fundamental analysis, price-and-filing analysis, internal-material review, or a formal report on a U.S.-listed equity. It does not cover trade execution or guaranteed return claims.

## Workflow
1. Confirm the ticker, research objective, time horizon, comparison basis, and required deliverable. Do not infer a missing ticker.
2. Call `research_us_company` for security identity, current quote metadata, adjusted price history, trend metrics, and SEC company facts. Preserve `observed_at`, `source`, `adjustment`, and every warning.
3. Use web search for recent filings, investor-relations material, news, industry context, or cross-checking. Label each source type clearly.
4. When user-mounted reports, internal standards, or project material are relevant, search knowledge first and cite the matched material.
5. Separate verified facts, analytical interpretation, counter-evidence, risks, and missing information. Save requested deliverables with workspace file tools.

## Output Standard
- Identify the company and ticker unambiguously.
- Include data timestamps, sources, and adjusted-price methodology.
- Preserve all tool warnings and disclose incomplete sections.
- Never invent valuation or financial figures not returned by tools or supported sources.
- Do not issue deterministic buy/sell instructions or promise returns.
