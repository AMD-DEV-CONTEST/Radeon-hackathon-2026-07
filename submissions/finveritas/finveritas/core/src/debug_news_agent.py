"""DEBUG ONLY: News + LLM summarizer agent.

Purpose:
- Fetch relevant articles from NewsAPI for a user query.
- Ask an OpenAI-compatible LLM (e.g., Groq endpoint) to summarize them.

This file is intentionally standalone and not wired into the main app pipeline.

Usage:
  # from repo root
  set -a && source .env && set +a
  /Users/mayank/Downloads/PBL-2-avi/mayankPbl/ocr/.venv/bin/python3.14 \
    /Users/mayank/Downloads/PBL-2-avi/mayankPbl/ocr/src/debug_news_agent.py \
    --query "TCS quarterly results and guidance"
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

import requests
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

NEWS_API_URL = "https://newsapi.org/v2/everything"


def fetch_news(query: str, news_api_key: str, max_articles: int = 10) -> list[dict[str, Any]]:
    params = {
        "q": query,
        "language": "en",
        "sortBy": "relevancy",
        "pageSize": max(1, min(max_articles, 50)),
        "apiKey": news_api_key,
    }
    resp = requests.get(NEWS_API_URL, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != "ok":
        raise RuntimeError(f"NewsAPI failed: {data}")

    articles = data.get("articles") or []
    cleaned: list[dict[str, Any]] = []
    for a in articles:
        cleaned.append(
            {
                "title": a.get("title"),
                "source": (a.get("source") or {}).get("name"),
                "publishedAt": a.get("publishedAt"),
                "description": a.get("description"),
                "url": a.get("url"),
            }
        )
    return cleaned


def summarize_with_llm(
    *,
    query: str,
    articles: list[dict[str, Any]],
    base_url: str,
    model: str,
    api_key: str,
) -> str:
    llm = ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=0,
    )

    system = (
        "You are a concise research assistant. "
        "Summarize only from the provided news items. "
        "Do not invent facts. If evidence is weak, say so clearly."
    )

    human = {
        "task": "Summarize relevant news for the query and list key takeaways.",
        "query": query,
        "articles": articles,
        "required_output": {
            "sections": [
                "1) Relevance summary",
                "2) 5 key takeaways",
                "3) Notable sources",
                "4) Confidence (High/Medium/Low)",
            ],
            "style": "short, factual, bullet-heavy",
        },
    }

    resp = llm.invoke(
        [
            SystemMessage(content=system),
            HumanMessage(content=json.dumps(human, ensure_ascii=False, indent=2)),
        ]
    )

    text = getattr(resp, "content", None)
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("LLM returned empty response")
    return text.strip()


def main() -> None:
    ap = argparse.ArgumentParser(description="DEBUG ONLY - News query summarizer")
    ap.add_argument("--query", required=True, help="What you want the agent to fetch and summarize")
    ap.add_argument("--max-articles", type=int, default=10)
    ap.add_argument("--news-api-key", default=None)
    ap.add_argument("--base-url", default=None, help="OpenAI-compatible base URL")
    ap.add_argument("--model", default=None)
    ap.add_argument("--api-key", default=None, help="LLM key (e.g., Groq key)")
    args = ap.parse_args()

    news_api_key = args.news_api_key or os.environ.get("NEWS_API_KEY")
    if not news_api_key:
        raise SystemExit("Missing NEWS_API_KEY")

    base_url = args.base_url or os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    model = args.model or os.environ.get("LLM_MODEL", "llama-3.1-8b-instant")
    base_url_l = (base_url or "").strip().lower()
    if "api.groq.com" in base_url_l:
        llm_key = args.api_key or os.environ.get("GROQ_API_KEY") or os.environ.get("LLM_API_KEY")
    elif "generativelanguage.googleapis.com" in base_url_l:
        llm_key = args.api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("LLM_API_KEY")
    else:
        llm_key = args.api_key or os.environ.get("LLM_API_KEY") or os.environ.get("GROQ_API_KEY")
    if not llm_key:
        raise SystemExit("Missing LLM_API_KEY/GROQ_API_KEY")

    print("[debug] fetching news...")
    articles = fetch_news(args.query, news_api_key, max_articles=args.max_articles)
    if not articles:
        raise SystemExit("No articles returned for query")

    print(f"[debug] fetched {len(articles)} article(s)")
    print("[debug] summarizing with LLM...")
    summary = summarize_with_llm(
        query=args.query,
        articles=articles,
        base_url=base_url,
        model=model,
        api_key=llm_key,
    )

    out = {
        "query": args.query,
        "articles_count": len(articles),
        "top_articles": articles[:5],
        "summary": summary,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
