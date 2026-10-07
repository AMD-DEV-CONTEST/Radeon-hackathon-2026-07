"""Sentiment Agent wrapper for the Streamlit dashboard.

Fetches the latest news for the company extracted from OCR and computes
public-perception sentiment metrics, then passes results to the
Cross Reference Agent.
"""
from __future__ import annotations

from typing import Any

from src.sentiment_agent import run_sentiment_agent


def run(
    *,
    company_name: str,
    news_api_key: str,
    base_url: str,
    model: str,
    api_key: str = "local",
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run the Sentiment Agent for *company_name*.

    Args:
        company_name:  Entity name extracted from the OCR payload (used as news query).
        news_api_key:  NewsAPI key — obtain a free key at https://newsapi.org/register.
        base_url/model/api_key: OpenAI-compatible LLM settings.

    Returns:
        {entity, metrics, analysis, top_headlines}
    """
    return run_sentiment_agent(
        company_name=company_name,
        news_api_key=news_api_key,
        base_url=base_url,
        model=model,
        api_key=api_key,
        run_id=run_id,
    )
