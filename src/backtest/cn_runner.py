"""Deterministic mainland-China ETF demo backtest with explicit market rules."""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


@dataclass
class CNBacktestResult:
    initial_balance: float
    final_balance: float
    total_return: float
    max_drawdown: float
    total_trades: int
    win_rate: float
    benchmark_return: float
    data_source: str = "deterministic_synthetic_cn_market_demo"


def _periods(strategy: dict[str, Any]) -> tuple[int, int]:
    periods = []
    for indicator in strategy.get("indicators", []):
        value = indicator.get("params", {}).get("period")
        try:
            periods.append(int(value))
        except (TypeError, ValueError):
            continue
    periods = sorted(set(periods))
    return (periods[0], periods[-1]) if len(periods) >= 2 else (20, 50)


def run_cn_demo_backtest(dsl: dict[str, Any], days: int, initial_balance: float) -> CNBacktestResult:
    """Run an EMA-cross demo on seeded synthetic prices; never presents them as live data."""
    strategy = dsl.get("strategy", {})
    market = strategy.get("market", {})
    instrument = str(market.get("instrument", "510300.SH"))
    fast_period, slow_period = _periods(strategy)
    seed = int(hashlib.sha256(f"{instrument}:{days}".encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    prices = [3.5 + (seed % 100) / 100]
    for i in range(max(days, slow_period + 10)):
        regime = 0.00025 + 0.0007 * math.sin(i / 31)
        prices.append(max(0.5, prices[-1] * (1 + regime + rng.gauss(0, 0.012))))

    constraints = strategy.get("constraints", {})
    lot_size = int(constraints.get("lot_size", 100))
    risk = strategy.get("risk", {})
    max_position = float(risk.get("max_position_pct", 0.3))
    cash = float(initial_balance)
    shares = 0
    buy_price = 0.0
    buy_day = -10
    wins = 0
    trades = 0
    equity_curve: list[float] = []

    def avg(idx: int, period: int) -> float:
        return sum(prices[idx - period + 1:idx + 1]) / period

    for i in range(slow_period, len(prices)):
        price = prices[i]
        fast = avg(i, fast_period)
        slow = avg(i, slow_period)
        if shares == 0 and fast > slow:
            execution = price * 1.0005
            affordable = int((cash * max_position) / execution / lot_size) * lot_size
            if affordable >= lot_size:
                commission = max(5.0, affordable * execution * 0.0003)
                cash -= affordable * execution + commission
                shares, buy_price, buy_day = affordable, execution, i
        elif shares > 0 and fast < slow and i > buy_day:  # T+1
            execution = price * 0.9995
            gross = shares * execution
            fees = max(5.0, gross * 0.0003) + gross * 0.0005
            cash += gross - fees
            trades += 1
            wins += int(execution > buy_price)
            shares = 0
        equity_curve.append(cash + shares * price)

    final_balance = cash + shares * prices[-1]
    peak = initial_balance
    max_drawdown = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1)
    return CNBacktestResult(
        initial_balance=initial_balance,
        final_balance=final_balance,
        total_return=final_balance / initial_balance - 1,
        max_drawdown=max_drawdown,
        total_trades=trades,
        win_rate=wins / trades if trades else 0.0,
        benchmark_return=prices[-1] / prices[slow_period] - 1,
    )
