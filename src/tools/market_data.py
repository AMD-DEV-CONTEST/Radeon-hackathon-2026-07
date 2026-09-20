"""Market data tool — fetches real-time and historical crypto market data.

Exposed as a Dify custom API tool via Swagger/OpenAPI spec.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..backtest.data_fetcher import get_market_summary, fetch_ohlcv


router = APIRouter(prefix="/market", tags=["market"])


class MarketSummaryResponse(BaseModel):
    pair: str
    exchange: str
    last_price: float
    change_pct: float
    high_24h: float
    low_24h: float
    volume_24h: float
    quote_volume_24h: float
    timestamp: int


@router.get("/summary", response_model=MarketSummaryResponse)
async def market_summary(
    pair: str = Query("BTC/USDT", description="Trading pair"),
    exchange: str = Query("binance", description="Exchange name"),
):
    """Get current market summary for a trading pair."""
    data = get_market_summary(pair, exchange)
    return MarketSummaryResponse(**data)


@router.get("/history")
async def historical_data(
    pair: str = Query("BTC/USDT"),
    timeframe: str = Query("1h"),
    exchange: str = Query("binance"),
    days: int = Query(30, description="Days of history"),
):
    """Get historical OHLCV data."""
    df = fetch_ohlcv(pair, timeframe, exchange, days)
    return {
        "pair": pair,
        "timeframe": timeframe,
        "exchange": exchange,
        "candles": df.reset_index().to_dict(orient="records"),
        "count": len(df),
    }
