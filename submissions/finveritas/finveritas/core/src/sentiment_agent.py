"""Sentiment Analysis Agent

Fetches recent company news headlines from NewsAPI and computes
deterministic public-perception metrics. Uses an LLM *only* to
generate a concise explanation of the computed metrics.

Design constraints (consistent with other agents in this repo):
- All numeric computations happen in Python — no ML models.
- The LLM must not compute or infer new numbers; it only explains provided metrics.
- NewsAPI free tier (https://newsapi.org) is the data source.

NewsAPI free tier: 100 requests/day, English-language results, last 30 days of coverage.
Obtain a free key at https://newsapi.org/register.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

import requests
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from src import db as _db

SentimentLabel = Literal["positive", "negative", "neutral"]

_NEWSAPI_URL = "https://newsapi.org/v2/everything"

# ---------------------------------------------------------------------------
# Keyword dictionaries for deterministic scoring
# Each word is checked against the lowercased token set of title + description.
# ---------------------------------------------------------------------------

_POSITIVE: frozenset[str] = frozenset({
    "profit", "profits", "growth", "surge", "surged", "record", "beat", "beats",
    "exceed", "exceeds", "exceeded", "strong", "stronger", "gain", "gains",
    "rise", "rises", "rose", "risen", "rally", "rallied", "upgrade", "upgraded",
    "outperform", "outperforms", "expansion", "expands", "expanded", "success",
    "successful", "milestone", "innovation", "innovative", "partnership",
    "award", "best", "high", "higher", "soar", "soared", "boost", "boosted",
    "advance", "advances", "positive", "increase", "increases", "increased",
    "improved", "improvement", "dividend", "dividends", "recovery", "recovers",
    "robust", "win", "wins", "won", "launch", "launches", "launched", "deal",
    "deals", "contract", "contracts", "acquisition", "invest", "investment",
    "bullish", "optimistic", "confident", "confidence", "breakthrough",
    "opportunity", "opportunities", "accelerate", "accelerates", "celebrates",
})

_NEGATIVE: frozenset[str] = frozenset({
    "loss", "losses", "lost", "decline", "declines", "declined", "fall",
    "falls", "fell", "fallen", "drop", "drops", "dropped", "cut", "cuts",
    "miss", "misses", "missed", "disappoint", "disappoints", "disappointed",
    "disappointing", "weak", "weaker", "weakness", "risk", "risks", "concern",
    "concerns", "trouble", "troubles", "debt", "debts", "lawsuit", "lawsuits",
    "fraud", "fraudulent", "investigation", "investigated", "layoff", "layoffs",
    "downgrade", "downgraded", "underperform", "underperforms", "scandal",
    "crash", "crashes", "slump", "slumped", "lower", "warning", "warnings",
    "negative", "decrease", "decreases", "decreased", "penalty", "penalties",
    "fine", "fines", "recall", "recalls", "bankruptcy", "bankrupt", "default",
    "defaults", "volatile", "volatility", "uncertain", "uncertainty", "resign",
    "resigns", "resigned", "withdraw", "withdraws", "delay", "delays",
    "delayed", "cancel", "cancels", "cancelled", "bearish", "pessimistic",
    "probe", "scrutiny", "violation", "violations", "charge", "charges", "accused",
    "sue", "sued", "sues", "sanction", "sanctions",
})


# ---------------------------------------------------------------------------
# News fetching
# ---------------------------------------------------------------------------

def fetch_news(
    company_name: str,
    api_key: str,
    max_articles: int = 20,
    language: str = "en",
) -> list[dict[str, Any]]:
    """Fetch recent news articles for *company_name* from NewsAPI.

    Returns a list of article dicts with keys: title, description, url, publishedAt.

    Raises:
        requests.HTTPError: on non-200 HTTP responses.
        RuntimeError: if the NewsAPI response carries a non-ok status field.
    """
    params: dict[str, Any] = {
        "q": company_name,
        "language": language,
        "sortBy": "publishedAt",
        "pageSize": min(max_articles, 100),  # NewsAPI max is 100
        "apiKey": api_key,
    }
    resp = requests.get(_NEWSAPI_URL, params=params, timeout=15)
    resp.raise_for_status()

    data = resp.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"NewsAPI error: {data.get('message', 'unknown error')}")

    return data.get("articles") or []


# ---------------------------------------------------------------------------
# Deterministic keyword-based scoring
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z]+")


def _score_text(text: str) -> float:
    """Return a sentiment score in [-1, 1] for *text* via keyword counting.

    score = (positive_hits - negative_hits) / max(1, positive_hits + negative_hits)
    A score near +1 is strongly positive; near -1 strongly negative; ~0 is neutral.
    """
    tokens = set(_TOKEN_RE.findall(text.lower()))
    pos = len(tokens & _POSITIVE)
    neg = len(tokens & _NEGATIVE)
    return (pos - neg) / max(1, pos + neg)


@dataclass(frozen=True)
class ArticleScore:
    title: str
    score: float
    label: SentimentLabel


def score_articles(
    articles: list[dict[str, Any]],
    threshold: float = 0.15,
) -> list[ArticleScore]:
    """Score each article deterministically and assign a sentiment label.

    An article scores *title + description* together.
    Label thresholds (default 0.15):
        score >=  threshold  → "positive"
        score <= -threshold  → "negative"
        otherwise            → "neutral"
    """
    scored: list[ArticleScore] = []
    for article in articles:
        title = (article.get("title") or "").strip()
        description = (article.get("description") or "").strip()
        combined = f"{title} {description}"
        score = _score_text(combined)
        if score >= threshold:
            label: SentimentLabel = "positive"
        elif score <= -threshold:
            label = "negative"
        else:
            label = "neutral"
        scored.append(ArticleScore(title=title, score=score, label=label))
    return scored


# ---------------------------------------------------------------------------
# Aggregate metrics
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SentimentMetrics:
    total_articles: int
    positive_count: int
    negative_count: int
    neutral_count: int
    sentiment_score: float      # mean article score, range [-1, 1]
    positive_pct: float         # percentage of positive articles
    negative_pct: float         # percentage of negative articles
    dominant_sentiment: SentimentLabel

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_articles": self.total_articles,
            "positive_count": self.positive_count,
            "negative_count": self.negative_count,
            "neutral_count": self.neutral_count,
            "sentiment_score": float(self.sentiment_score),
            "positive_pct": float(self.positive_pct),
            "negative_pct": float(self.negative_pct),
            "dominant_sentiment": self.dominant_sentiment,
        }


def compute_sentiment_metrics(scored: list[ArticleScore]) -> SentimentMetrics:
    """Aggregate a list of ArticleScore objects into a SentimentMetrics summary."""
    if not scored:
        raise ValueError("No articles to compute sentiment metrics from")

    total = len(scored)
    pos = sum(1 for s in scored if s.label == "positive")
    neg = sum(1 for s in scored if s.label == "negative")
    neu = total - pos - neg

    mean_score = sum(s.score for s in scored) / total
    pos_pct = round((pos / total) * 100.0, 2)
    neg_pct = round((neg / total) * 100.0, 2)

    counts: dict[str, int] = {"positive": pos, "negative": neg, "neutral": neu}
    dominant: SentimentLabel = max(counts, key=lambda k: counts[k])  # type: ignore[return-value]

    return SentimentMetrics(
        total_articles=total,
        positive_count=pos,
        negative_count=neg,
        neutral_count=neu,
        sentiment_score=round(mean_score, 4),
        positive_pct=pos_pct,
        negative_pct=neg_pct,
        dominant_sentiment=dominant,
    )


# ---------------------------------------------------------------------------
# LLM explanation
# ---------------------------------------------------------------------------

def _select_top_headlines(scored: list[ArticleScore], n: int = 5) -> list[str]:
    """Pick representative headlines: top positive, top negative, then neutral."""
    positive = sorted(
        (s for s in scored if s.label == "positive"),
        key=lambda x: x.score, reverse=True,
    )
    negative = sorted(
        (s for s in scored if s.label == "negative"),
        key=lambda x: x.score,
    )
    neutral = [s for s in scored if s.label == "neutral"]
    mixed = positive[:2] + negative[:2] + neutral[:1]
    return [s.title for s in mixed if s.title][:n]


def _build_human_message(
    entity: str,
    metrics: dict[str, Any],
    headlines: list[str],
) -> str:
    return json.dumps(
        {
            "task": (
                "Describe the current public sentiment around this company based on recent news. "
                "Reference the provided metrics and representative headlines. "
                "Do not compute new numbers. Do not provide investment or credit advice."
            ),
            "entity": entity,
            "sentiment_metrics": metrics,
            "representative_headlines": headlines,
            "output": {
                "format": "plain_text",
                "length": "4-6 sentences",
                "must_include": [
                    "overall dominant sentiment label",
                    "proportion of positive vs negative coverage",
                    "brief qualitative characterisation based on headlines",
                ],
            },
        },
        indent=2,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_sentiment_agent(
    *,
    company_name: str,
    news_api_key: str,
    base_url: str,
    model: str,
    api_key: str = "local",
    max_articles: int = 20,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Fetch news, compute deterministic sentiment metrics, and generate an LLM explanation.

    Args:
        company_name:  Company name used as the NewsAPI search query.
        news_api_key:  NewsAPI key (free tier sufficient).
        base_url:      OpenAI-compatible LLM base URL.
        model:         Model name to use for explanation.
        api_key:       LLM API key (use "local" for LM Studio).
        max_articles:  Number of articles to fetch (max 100 for free tier).

    Returns:
        {
            "entity":        str,
            "metrics":       dict,   # SentimentMetrics as flat dict
            "analysis":      str,    # LLM-generated explanation
            "top_headlines": list,   # up to 5 representative headlines
        }
    """
    articles = fetch_news(company_name, news_api_key, max_articles=max_articles)
    if not articles:
        raise ValueError(f"No news articles found for '{company_name}' via NewsAPI")

    scored = score_articles(articles)
    metrics = compute_sentiment_metrics(scored)
    top_headlines = _select_top_headlines(scored)

    system = (
        "You are a financial analyst summarising public news sentiment for a company. "
        "Use only the provided metrics and headlines. "
        "Do not compute, estimate, or infer any new numbers. "
        "Do not provide credit, lending, or investment recommendations. "
        "Write in a concise, professional tone."
    )
    human_content = _build_human_message(company_name, metrics.to_dict(), top_headlines)

    llm = ChatOpenAI(model=model, base_url=base_url, api_key=api_key, temperature=0)
    messages = [SystemMessage(content=system), HumanMessage(content=human_content)]
    resp = _db.instrumented_invoke(
        llm, messages,
        run_id=run_id, agent_name="sentiment_agent", model=model, base_url=base_url,
    )
    text = getattr(resp, "content", None)
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("LLM returned an empty sentiment analysis")

    return {
        "entity": company_name,
        "metrics": metrics.to_dict(),
        "analysis": text.strip(),
        "top_headlines": top_headlines,
    }
