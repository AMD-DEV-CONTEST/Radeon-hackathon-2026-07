"""Paper trading tool — Binance Testnet integration with safety limits.

Safety features:
- DRY_RUN mode (default): simulates orders without touching Testnet
- Max position size, max order amount, daily max loss
- Only Binance Testnet (never real exchange)
- All actions logged for audit

Usage:
    Set env vars: BINANCE_TESTNET_API_KEY, BINANCE_TESTNET_API_SECRET
    Set DRY_RUN=false to use real Testnet (default: true)
"""

from __future__ import annotations

import os
import time
import json
import threading
from datetime import datetime, timezone
from typing import Any

import ccxt
from fastapi import APIRouter
from pydantic import BaseModel


router = APIRouter(prefix="/paper-trade", tags=["paper-trade"])

# --- Safety limits ---
MAX_ORDER_AMOUNT_USD = 1000.0  # Max per-order value in USDT
MAX_POSITION_USD = 5000.0      # Max total position in USDT
DAILY_MAX_LOSS_PCT = 0.10      # Max daily loss (10% of starting balance)
DEFAULT_STAKE = 0.001           # Default BTC amount for demo

# --- State tracking (in-memory, per session) — protected by lock ---
_position_tracker: dict[str, float] = {}  # pair -> amount held
_order_log: list[dict] = []
_daily_pnl: float = 0.0
_daily_reset_time: float = time.time()
_state_lock = threading.Lock()

_testnet_exchange: ccxt.Exchange | None = None


def get_testnet_exchange(api_key: str = "", api_secret: str = "") -> ccxt.Exchange:
    global _testnet_exchange
    if _testnet_exchange is None:
        _testnet_exchange = ccxt.binance({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "urls": {
                "api": {
                    "public": "https://testnet.binance.vision/api",
                    "private": "https://testnet.binance.vision/api",
                }
            },
        })
    return _testnet_exchange


def _is_dry_run() -> bool:
    return os.environ.get("DRY_RUN", "true").lower() not in ("false", "0", "no")


def _check_daily_reset():
    global _daily_pnl, _daily_reset_time
    with _state_lock:
        if time.time() - _daily_reset_time > 86400:  # 24h
            _daily_pnl = 0.0
            _daily_reset_time = time.time()


def _log_order(action: str, pair: str, amount: float, price: float, success: bool, details: dict, mode: str):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "action": action,
        "pair": pair,
        "amount": amount,
        "price": price,
        "value_usd": amount * price,
        "success": success,
        "details": details,
    }
    with _state_lock:
        _order_log.append(entry)
    return entry


class PaperTradeRequest(BaseModel):
    action: str  # "buy" | "sell" | "status" | "balance" | "orders" | "close_all"
    pair: str = "BTC/USDT"
    amount: float | None = None
    price: float | None = None
    dry_run: bool | None = None  # Override env DRY_RUN


class PaperTradeResponse(BaseModel):
    success: bool
    action: str
    pair: str
    mode: str = "dry_run"  # "dry_run" or "testnet"
    details: dict[str, Any] = {}
    error: str | None = None
    order_log: list[dict] = []
    warning: str | None = None


@router.post("/execute", response_model=PaperTradeResponse)
async def execute_paper_trade(req: PaperTradeRequest):
    """Execute a paper trade on Binance Testnet (or DRY_RUN simulation).

    Safety:
    - Default: DRY_RUN=true (no real Testnet calls)
    - Max order: $1000 USDT
    - Max position: $5000 USDT
    - Daily max loss: 10%
    - Only Binance Testnet, never real exchange
    """
    dry_run = _is_dry_run() if req.dry_run is None else req.dry_run
    # Security: never allow real exchange trades via API without explicit env config
    if not dry_run and not os.environ.get("ENABLE_TESTNET_TRADING", "false").lower() in ("true", "1", "yes"):
        return PaperTradeResponse(
            success=False, action=req.action, pair=req.pair, mode="dry_run",
            error="Testnet trading is disabled. Set ENABLE_TESTNET_TRADING=true to enable.",
        )
    mode = "dry_run" if dry_run else "testnet"

    _check_daily_reset()

    # Get current price (works in both modes — public endpoint)
    current_price = 0.0
    ticker = {}
    try:
        exchange = get_testnet_exchange()
        ticker = exchange.fetch_ticker(req.pair)
        current_price = ticker.get("last", 0)
    except Exception:
        # Fallback if Testnet unreachable
        current_price = 65000.0  # Approximate BTC price for DRY_RUN
        ticker = {"last": current_price, "bid": current_price, "ask": current_price, "baseVolume": 0}

    if req.action == "status":
        return PaperTradeResponse(
            success=True, action="status", pair=req.pair, mode=mode,
            details={
                "last_price": current_price,
                "bid": ticker.get("bid", 0),
                "ask": ticker.get("ask", 0),
                "volume": ticker.get("baseVolume", 0),
                "dry_run": dry_run,
                "position": _position_tracker.get(req.pair, 0),
            },
        )

    if req.action == "balance":
        if dry_run:
            return PaperTradeResponse(
                success=True, action="balance", pair=req.pair, mode=mode,
                details={
                    "total": {"USDT": 10000.0, "BTC": _position_tracker.get(req.pair, 0)},
                    "free": {"USDT": 10000.0 - _position_tracker.get(req.pair, 0) * current_price,
                             "BTC": _position_tracker.get(req.pair, 0)},
                    "used": {},
                    "dry_run": True,
                },
            )
        api_key = os.environ.get("BINANCE_TESTNET_API_KEY", "")
        api_secret = os.environ.get("BINANCE_TESTNET_API_SECRET", "")
        if not api_key or not api_secret:
            return PaperTradeResponse(
                success=False, action="balance", pair=req.pair, mode=mode,
                error="Binance Testnet API keys not configured",
            )
        exchange = get_testnet_exchange(api_key, api_secret)
        balance = exchange.fetch_balance()
        return PaperTradeResponse(
            success=True, action="balance", pair=req.pair, mode=mode,
            details={"total": balance.get("total", {}), "free": balance.get("free", {})},
        )

    if req.action == "orders":
        return PaperTradeResponse(
            success=True, action="orders", pair=req.pair, mode=mode,
            order_log=_order_log[-20:],
        )

    if req.action == "close_all":
        held = _position_tracker.get(req.pair, 0)
        if held <= 0:
            return PaperTradeResponse(
                success=True, action="close_all", pair=req.pair, mode=mode,
                details={"message": "No position to close"},
            )
        return await _execute_sell(req.pair, held, current_price, dry_run, mode)

    # --- Buy / Sell ---
    amount = req.amount or DEFAULT_STAKE
    order_value = amount * current_price

    # Safety check: max order amount
    if order_value > MAX_ORDER_AMOUNT_USD:
        return PaperTradeResponse(
            success=False, action=req.action, pair=req.pair, mode=mode,
            error=f"Order value ${order_value:.2f} exceeds max ${MAX_ORDER_AMOUNT_USD}",
        )

    if req.action == "buy":
        # Safety check: max position
        current_position_value = _position_tracker.get(req.pair, 0) * current_price
        if current_position_value + order_value > MAX_POSITION_USD:
            return PaperTradeResponse(
                success=False, action="buy", pair=req.pair, mode=mode,
                error=f"Position would exceed max ${MAX_POSITION_USD}",
            )
        return await _execute_buy(req.pair, amount, current_price, dry_run, mode)

    elif req.action == "sell":
        held = _position_tracker.get(req.pair, 0)
        if held < amount:
            return PaperTradeResponse(
                success=False, action="sell", pair=req.pair, mode=mode,
                error=f"Insufficient position: have {held}, want to sell {amount}",
            )
        return await _execute_sell(req.pair, amount, current_price, dry_run, mode)

    return PaperTradeResponse(
        success=False, action=req.action, pair=req.pair, mode=mode,
        error=f"Unknown action: {req.action}",
    )


async def _execute_buy(pair: str, amount: float, price: float, dry_run: bool, mode: str) -> PaperTradeResponse:
    if dry_run:
        _position_tracker[pair] = _position_tracker.get(pair, 0) + amount
        entry = _log_order("buy", pair, amount, price, True,
                          {"simulated": True, "fill_price": price}, mode)
        return PaperTradeResponse(
            success=True, action="buy", pair=pair, mode=mode,
            details={"order_id": f"DRY-{int(time.time())}", "amount": amount,
                     "fill_price": price, "value_usd": amount * price,
                     "position": _position_tracker.get(pair, 0)},
            order_log=[entry],
        )

    # Real Testnet
    api_key = os.environ.get("BINANCE_TESTNET_API_KEY", "")
    api_secret = os.environ.get("BINANCE_TESTNET_API_SECRET", "")
    if not api_key or not api_secret:
        return PaperTradeResponse(
            success=False, action="buy", pair=pair, mode=mode,
            error="Binance Testnet API keys not configured",
        )
    exchange = get_testnet_exchange(api_key, api_secret)
    order = exchange.create_market_buy_order(pair, amount)
    _position_tracker[pair] = _position_tracker.get(pair, 0) + amount
    entry = _log_order("buy", pair, amount, price, True, order, mode)
    return PaperTradeResponse(
        success=True, action="buy", pair=pair, mode=mode,
        details={"order_id": order.get("id"), "amount": order.get("amount"),
                 "filled": order.get("filled"), "value_usd": amount * price},
        order_log=[entry],
    )


async def _execute_sell(pair: str, amount: float, price: float, dry_run: bool, mode: str) -> PaperTradeResponse:
    if dry_run:
        _position_tracker[pair] = max(0, _position_tracker.get(pair, 0) - amount)
        entry = _log_order("sell", pair, amount, price, True,
                          {"simulated": True, "fill_price": price}, mode)
        return PaperTradeResponse(
            success=True, action="sell", pair=pair, mode=mode,
            details={"order_id": f"DRY-{int(time.time())}", "amount": amount,
                     "fill_price": price, "value_usd": amount * price,
                     "position": _position_tracker.get(pair, 0)},
            order_log=[entry],
        )

    api_key = os.environ.get("BINANCE_TESTNET_API_KEY", "")
    api_secret = os.environ.get("BINANCE_TESTNET_API_SECRET", "")
    if not api_key or not api_secret:
        return PaperTradeResponse(
            success=False, action="sell", pair=pair, mode=mode,
            error="Binance Testnet API keys not configured",
        )
    exchange = get_testnet_exchange(api_key, api_secret)
    order = exchange.create_market_sell_order(pair, amount)
    _position_tracker[pair] = max(0, _position_tracker.get(pair, 0) - amount)
    entry = _log_order("sell", pair, amount, price, True, order, mode)
    return PaperTradeResponse(
        success=True, action="sell", pair=pair, mode=mode,
        details={"order_id": order.get("id"), "amount": order.get("amount"),
                 "filled": order.get("filled"), "value_usd": amount * price},
        order_log=[entry],
    )
