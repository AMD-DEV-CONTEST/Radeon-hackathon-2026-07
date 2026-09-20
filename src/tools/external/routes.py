"""FastAPI routes for external tools — exposed under /api/tools/*.

Endpoints:
  GET /api/tools/intent?text=...          — intent classification only
  GET /api/tools/market_data?symbol=...   — OHLCV (mock default / real opt-in)
  GET /api/tools/announcement?symbol=...  — announcements (mock default / real)
  GET /api/tools/query?text=...           — full auditable chain (steps trace)

The `steps` trace is what Dify nodes render so judges can SEE the agent's
autonomous planning (intent → RAG → fallback) instead of only the answer.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from .intent import classify_intent
from .providers import market_data, announcement
from .registry import handle_query

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("/intent")
async def intent_endpoint(text: str = Query(..., description="User message")):
    return classify_intent(text).to_dict()


@router.get("/market_data")
async def market_data_endpoint(
    symbol: str = Query("510300.SH", description="A-share symbol, e.g. 510300.SH"),
    days: int = Query(30, ge=5, le=250),
    mode: str | None = Query(None, description="mock (default) | real"),
):
    return market_data(symbol, days, mode).to_dict()


@router.get("/announcement")
async def announcement_endpoint(
    symbol: str = Query("510300.SH", description="A-share symbol"),
    mode: str | None = Query(None, description="mock (default) | real"),
):
    return announcement(symbol, mode).to_dict()


@router.get("/query")
async def query_endpoint(
    text: str = Query(..., description="User question"),
    mode: str | None = Query(None, description="mock (default) | real"),
):
    """Full chain: intent → RAG → external fallback, with auditable steps."""
    return handle_query(text, mode).to_dict()
