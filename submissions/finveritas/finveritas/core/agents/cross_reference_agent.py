"""Cross Reference Agent

Takes outputs from multiple deterministic agents and produces a consolidated
explainable summary via an LLM.

Constraints:
- Must not calculate new numbers.
- Must use only provided metrics and qualitative flags.
- No credit decisions (enforced by post-generation guardrail with one retry).
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from src import db as _db

# Patterns that indicate the LLM has drifted into credit-decision language,
# which is prohibited by RBI Digital Lending Guidelines 2022.
_CREDIT_DECISION_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(approve[ds]?|reject(?:ed|ion)?|deny|denied|decline[ds]?)\b"),
    re.compile(r"\bcredit\s+(decision|approval|rejection|eligib\w+)\b"),
    re.compile(r"\b(creditworthy|not\s+creditworthy|bankable|unbankable)\b"),
    re.compile(r"\bshould\s+(approve|reject|lend|not\s+lend|extend|withhold)\b"),
    re.compile(r"\b(grant|deny|extend|withhold)\s+(?:a\s+)?(?:credit|loan|lending|facility)\b"),
    re.compile(r"\brecommend(?:ed|s)?\s+(?:for|against)\s+(?:credit|lending|loan|approval)\b"),
]


def _credit_decision_violations(text: str) -> list[str]:
    """Return list of matched patterns; empty means the text is clean."""
    low = text.lower()
    return [pat.pattern for pat in _CREDIT_DECISION_PATTERNS if pat.search(low)]


def run(
    *,
    entity: str,
    revenue: dict[str, Any],
    liquidity: dict[str, Any],
    balance_sheet: dict[str, Any],
    sentiment: dict[str, Any] | None = None,
    base_url: str,
    model: str,
    api_key: str = "local",
    run_id: str | None = None,
) -> dict[str, Any]:
    """Generate a cross-referenced explanation using only agent metrics."""
    inputs: dict[str, Any] = {
        "revenue_metrics": revenue.get("metrics"),
        "liquidity_metrics": liquidity.get("metrics"),
        "balance_sheet_metrics": balance_sheet.get("metrics"),
    }
    must_include = [
        "a short revenue summary",
        "a short liquidity summary",
        "a short balance sheet/leverage summary",
    ]
    if sentiment:
        inputs["sentiment_metrics"] = sentiment.get("metrics")
        inputs["sentiment_analysis_snippet"] = (
            (sentiment.get("analysis") or "")[:300] or None
        )
        must_include.append("a short public sentiment summary")

    must_include.append("one integrated concluding sentence")

    payload = {
        "entity": entity,
        "inputs": inputs,
        "requirements": {
            "no_new_numbers": True,
            "no_credit_decisions": True,
            "professional_tone": True,
            "temperature": 0,
        },
    }

    system = (
        "You are a financial analyst producing an explainable, cross-referenced summary. "
        "Use only the provided metrics. "
        "Do not compute, estimate, or infer any new numbers. "
        "Do not introduce new financial line items. "
        "Do not provide credit, lending, or investment recommendations. "
        "Do not use words like approve, reject, deny, decline, creditworthy, or bankable. "
        "Write in a concise professional tone (6-10 sentences)."
    )

    human = {
        "task": (
            "Cross-reference all provided metrics to describe overall financial and "
            "public-perception trends, highlighting consistency or tension between signals."
        ),
        **payload,
        "output": {
            "format": "plain_text",
            "must_include": must_include,
        },
    }

    llm = ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=0,
    )

    messages = [SystemMessage(content=system), HumanMessage(content=json.dumps(human, indent=2))]

    violations: list[str] = []
    for attempt in range(2):
        resp = _db.instrumented_invoke(
            llm, messages,
            run_id=run_id, agent_name="cross_reference_agent", model=model, base_url=base_url,
            attempt=attempt + 1,
            violations_found=violations if violations else None,
        )
        text = getattr(resp, "content", None)
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("LLM returned empty cross-reference analysis")

        text = text.strip()
        violations = _credit_decision_violations(text)
        if not violations:
            return {
                "entity": entity,
                "metrics": {
                    "revenue": revenue.get("metrics"),
                    "liquidity": liquidity.get("metrics"),
                    "balance_sheet": balance_sheet.get("metrics"),
                    "sentiment": sentiment.get("metrics") if sentiment else None,
                },
                "analysis": text,
            }

        # Retry once with an explicit correction prompt
        correction = (
            "Your previous response contained credit-decision language which is not permitted. "
            "Do not use: approve, reject, deny, decline, creditworthy, bankable, or similar terms. "
            "Describe financial trends only — do not recommend any course of action."
        )
        messages = [
            SystemMessage(content=system),
            HumanMessage(content=json.dumps(human, indent=2)),
            SystemMessage(content=correction),
        ]

    raise RuntimeError(
        f"Cross Reference Agent LLM violated credit-decision guardrail after retry. "
        f"Matched patterns: {violations}"
    )
