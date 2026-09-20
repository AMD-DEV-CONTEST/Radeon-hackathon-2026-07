"""Backtest runner — executes strategy on historical data.

This module runs backtests by:
1. Fetching historical OHLCV data via CCXT
2. Computing indicators
3. Evaluating entry/exit conditions from DSL
4. Simulating trades and computing performance metrics

Key fixes vs original:
- Multi-position management (respects max_open_trades)
- Timeframe-aware Sharpe annualization
- Buy-and-hold benchmark comparison
- Slippage model
- Sortino, Calmar, max consecutive losses
- Safe expression evaluation (no df.eval injection)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .data_fetcher import fetch_ohlcv, calculate_indicators
from ..dsl.expr_parser import evaluate_expression


@dataclass
class BacktestResult:
    """Structured backtest result."""
    total_trades: int = 0
    win_trades: int = 0
    loss_trades: int = 0
    win_rate: float = 0.0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    final_balance: float = 0.0
    initial_balance: float = 0.0
    duration_days: int = 0
    trades: list[dict] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    error: str | None = None
    is_valid: bool = True  # False if backtest sanity check failed
    # --- New metrics ---
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    max_consecutive_losses: int = 0
    avg_trade_duration: float = 0.0  # in candles
    benchmark_return: float = 0.0
    alpha: float = 0.0  # strategy return - benchmark return
    volatility_annual: float = 0.0
    benchmark_curve: list[float] = field(default_factory=list)


@dataclass
class _Position:
    """An open position in the backtest."""
    entry_price: float
    amount: float  # in base currency (e.g. BTC)
    entry_index: int
    entry_timestamp: Any
    side: str = "long"  # "long" or "short"


# Timeframe → minutes mapping for annualization
_TIMEFRAME_MINUTES: dict[str, int] = {
    "1m": 1, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "4h": 240, "1d": 1440, "1w": 10080,
}


def run_backtest(
    strategy_dsl: dict[str, Any],
    days: int = 180,
    initial_balance: float = 10000.0,
    fee: float = 0.001,  # 0.1% per trade
    slippage: float = 0.0005,  # 0.05% slippage
) -> BacktestResult:
    """Run a backtest on historical data using the strategy DSL.

    Args:
        strategy_dsl: Parsed strategy DSL dict.
        days: Number of days of historical data to use.
        initial_balance: Starting balance in quote currency.
        fee: Trading fee per transaction (as decimal).
        slippage: Slippage per transaction (as decimal).

    Returns:
        BacktestResult with performance metrics.
    """
    strat = strategy_dsl["strategy"]
    market = strat["market"]
    indicators = strat["indicators"]
    entry = strat["entry"]
    exit_conf = strat.get("exit", {})
    risk = strat["risk"]

    # --- Fetch historical data ---
    try:
        df = fetch_ohlcv(
            pair=market["pair"],
            timeframe=market["timeframe"],
            exchange_name=market["exchange"],
            days=days,
        )
    except Exception as e:
        return BacktestResult(error=f"Data fetch error: {e}")

    if df.empty:
        return BacktestResult(error="No historical data available")

    # --- Calculate indicators ---
    try:
        df = calculate_indicators(df, indicators)
    except Exception as e:
        return BacktestResult(error=f"Indicator calculation error: {e}")

    # --- Evaluate entry/exit signals ---
    df = _evaluate_signals(df, entry, exit_conf)

    # --- Simulate trades ---
    result = _simulate_trades(
        df=df,
        initial_balance=initial_balance,
        fee=fee,
        slippage=slippage,
        stop_loss=risk.get("stop_loss", -0.03),
        take_profit=risk.get("take_profit"),
        max_open_trades=risk.get("max_open_trades", 3),
        stake_amount=risk.get("stake_amount", 0.1),
        timeframe=market["timeframe"],
        time_in_trade=risk.get("time_in_trade"),
    )

    result.duration_days = days
    result.initial_balance = initial_balance

    # --- Buy-and-hold benchmark ---
    bh_units = initial_balance / df.iloc[0]["close"]
    result.benchmark_curve = (bh_units * df["close"]).round(2).tolist()
    result.benchmark_return = round(
        (df.iloc[-1]["close"] - df.iloc[0]["close"]) / df.iloc[0]["close"], 4
    )
    result.alpha = round(result.total_return - result.benchmark_return, 4)

    return result


def _evaluate_signals(
    df: pd.DataFrame,
    entry: dict,
    exit_conf: dict,
) -> pd.DataFrame:
    """Evaluate entry and exit boolean expressions on the DataFrame."""
    long_entry_expr = entry.get("long")
    short_entry_expr = entry.get("short")

    if long_entry_expr:
        df["enter_long"] = evaluate_expression(df, long_entry_expr)
    else:
        df["enter_long"] = False

    if short_entry_expr:
        df["enter_short"] = evaluate_expression(df, short_entry_expr)
    else:
        df["enter_short"] = False

    long_exit_expr = exit_conf.get("long")
    short_exit_expr = exit_conf.get("short")

    if long_exit_expr:
        df["exit_long"] = evaluate_expression(df, long_exit_expr)
    else:
        df["exit_long"] = False

    if short_exit_expr:
        df["exit_short"] = evaluate_expression(df, short_exit_expr)
    else:
        df["exit_short"] = False

    return df


def _simulate_trades(
    df: pd.DataFrame,
    initial_balance: float,
    fee: float,
    slippage: float,
    stop_loss: float,
    take_profit: float | None,
    max_open_trades: int,
    stake_amount: float | str,
    timeframe: str = "1h",
    time_in_trade: dict | None = None,
) -> BacktestResult:
    """Simulate trades with multi-position management and short support.

    Supports concurrent positions up to max_open_trades.
    Each position is tracked independently for stop-loss/take-profit.
    Both long and short positions are supported.
    """
    result = BacktestResult()
    balance = float(initial_balance)
    open_positions: list[_Position] = []
    trades: list[dict] = []

    equity_curve: list[float] = []
    dates: list[str] = []

    # Determine per-position capital allocation
    if isinstance(stake_amount, str) and stake_amount == "unlimited":
        per_trade_pct = 0.90 / max_open_trades
    else:
        per_trade_pct = min(float(stake_amount), 0.90)

    # --- Compute max candles in trade from time_in_trade ---
    tf_minutes = _TIMEFRAME_MINUTES.get(timeframe, 60)
    max_candles_in_trade = 0
    if time_in_trade:
        max_minutes = 0
        max_minutes += time_in_trade.get("max_minutes", 0)
        max_minutes += time_in_trade.get("max_hours", 0) * 60
        max_minutes += time_in_trade.get("max_days", 0) * 1440
        if max_minutes > 0:
            max_candles_in_trade = int(max_minutes / tf_minutes)

    def _calc_pnl_pct(pos: _Position, current_price: float) -> float:
        if pos.side == "long":
            return (current_price - pos.entry_price) / pos.entry_price
        else:
            return (pos.entry_price - current_price) / pos.entry_price

    for i, (timestamp, row) in enumerate(df.iterrows()):
        current_price = row["close"]

        # --- Check stop-loss / take-profit / time-in-trade / exit signals ---
        positions_to_close: list[int] = []
        for idx, pos in enumerate(open_positions):
            pnl_pct = _calc_pnl_pct(pos, current_price)
            close_reason = None

            if pnl_pct <= stop_loss:
                close_reason = "stop_loss"
            elif take_profit and pnl_pct >= take_profit:
                close_reason = "take_profit"
            elif max_candles_in_trade > 0 and (i - pos.entry_index) >= max_candles_in_trade:
                close_reason = "time_limit"
            elif pos.side == "long" and row.get("exit_long", False):
                close_reason = "signal_exit"
            elif pos.side == "short" and row.get("exit_short", False):
                close_reason = "signal_exit"

            if close_reason:
                positions_to_close.append(idx)

        # Close positions (reverse order to maintain indices)
        for idx in reversed(positions_to_close):
            pos = open_positions.pop(idx)
            if pos.side == "long":
                exec_price = current_price * (1 - slippage)
                proceeds = pos.amount * exec_price * (1 - fee)
                cost_basis = pos.amount * pos.entry_price * (1 + fee)
                profit = proceeds - cost_basis
                balance += proceeds
            else:
                # Short: buy back at slightly worse price
                exec_price = current_price * (1 + slippage)
                buy_cost = pos.amount * exec_price * (1 + fee)
                # Short proceeds were credited at entry; profit = entry_credit - buy_cost
                entry_credit = pos.amount * pos.entry_price * (1 - fee)
                profit = entry_credit - buy_cost
                balance -= buy_cost

            trades.append({
                "type": "sell" if pos.side == "long" else "cover",
                "side": pos.side,
                "datetime": str(timestamp),
                "price": round(exec_price, 6),
                "amount": pos.amount,
                "cost": pos.amount * exec_price,
                "fee": pos.amount * exec_price * fee,
                "profit": round(profit, 4),
                "reason": close_reason,
                "duration_candles": i - pos.entry_index,
            })

        # --- Check long entry signal ---
        if (
            row.get("enter_long", False)
            and len(open_positions) < max_open_trades
            and current_price > 0
            and balance > 0  # Prevent opening positions with negative balance
        ):
            pos_capital = balance * per_trade_pct / max(1, max_open_trades - len(open_positions))
            pos_capital = min(pos_capital, balance * 0.90)

            if pos_capital > 0:
                exec_price = current_price * (1 + slippage)
                amount = pos_capital / exec_price
                cost = pos_capital + pos_capital * fee
                balance -= cost

                open_positions.append(_Position(
                    entry_price=exec_price,
                    amount=amount,
                    entry_index=i,
                    entry_timestamp=timestamp,
                    side="long",
                ))
                trades.append({
                    "type": "buy",
                    "side": "long",
                    "datetime": str(timestamp),
                    "price": round(exec_price, 6),
                    "amount": amount,
                    "cost": cost,
                    "fee": pos_capital * fee,
                    "reason": "signal_entry",
                })

        # --- Check short entry signal ---
        if (
            row.get("enter_short", False)
            and len(open_positions) < max_open_trades
            and current_price > 0
        ):
            pos_capital = balance * per_trade_pct / max(1, max_open_trades - len(open_positions))
            pos_capital = min(pos_capital, balance * 0.90)

            if pos_capital > 0:
                exec_price = current_price * (1 - slippage)
                amount = pos_capital / exec_price
                # Credit balance with short proceeds
                proceeds = pos_capital * (1 - fee)
                balance += proceeds

                open_positions.append(_Position(
                    entry_price=exec_price,
                    amount=amount,
                    entry_index=i,
                    entry_timestamp=timestamp,
                    side="short",
                ))
                trades.append({
                    "type": "sell_short",
                    "side": "short",
                    "datetime": str(timestamp),
                    "price": round(exec_price, 6),
                    "amount": amount,
                    "cost": pos_capital,
                    "fee": pos_capital * fee,
                    "reason": "signal_entry",
                })

        # --- Track equity ---
        unrealized = 0.0
        for p in open_positions:
            if p.side == "long":
                unrealized += p.amount * current_price
            else:
                unrealized -= p.amount * current_price
        equity = balance + unrealized
        equity_curve.append(round(equity, 2))
        dates.append(str(timestamp))

    # --- Close any remaining positions at backtest end ---
    last_price = df.iloc[-1]["close"]
    for pos in open_positions:
        if pos.side == "long":
            exec_price = last_price * (1 - slippage)
            proceeds = pos.amount * exec_price * (1 - fee)
            cost_basis = pos.amount * pos.entry_price * (1 + fee)
            profit = proceeds - cost_basis
            balance += proceeds
        else:
            exec_price = last_price * (1 + slippage)
            buy_cost = pos.amount * exec_price * (1 + fee)
            entry_credit = pos.amount * pos.entry_price * (1 - fee)
            profit = entry_credit - buy_cost
            balance -= buy_cost
        trades.append({
            "type": "sell" if pos.side == "long" else "cover",
            "side": pos.side,
            "datetime": str(dates[-1]),
            "price": round(exec_price, 6),
            "amount": pos.amount,
            "cost": pos.amount * exec_price,
            "fee": pos.amount * exec_price * fee,
            "profit": round(profit, 4),
            "reason": "backtest_end",
            "duration_candles": len(df) - 1 - pos.entry_index,
        })
    open_positions.clear()

    # --- Calculate metrics ---
    result.final_balance = round(max(balance, 0), 2)  # Floor at 0
    result.total_return = round(max((balance - initial_balance) / initial_balance, -1.0), 4)  # Cap at -100%
    result.equity_curve = equity_curve
    result.dates = dates
    result.trades = trades

    # --- Trade-level metrics ---
    completed = [t for t in trades if t["type"] in ("sell", "cover")]
    result.total_trades = len(completed)

    if completed:
        profits = [t.get("profit", 0) for t in completed]
        result.win_trades = sum(1 for p in profits if p > 0)
        result.loss_trades = sum(1 for p in profits if p <= 0)
        result.win_rate = result.win_trades / result.total_trades if result.total_trades > 0 else 0
        result.avg_win = float(np.mean([p for p in profits if p > 0])) if result.win_trades > 0 else 0
        result.avg_loss = float(np.mean([p for p in profits if p <= 0])) if result.loss_trades > 0 else 0

        gross_profit = sum(p for p in profits if p > 0)
        gross_loss = abs(sum(p for p in profits if p < 0))
        result.profit_factor = round(gross_profit / gross_loss, 4) if gross_loss > 0 else float("inf")

        # Max consecutive losses
        max_consec_loss = 0
        current_streak = 0
        for p in profits:
            if p <= 0:
                current_streak += 1
                max_consec_loss = max(max_consec_loss, current_streak)
            else:
                current_streak = 0
        result.max_consecutive_losses = max_consec_loss

        # Average trade duration
        durations = [t.get("duration_candles", 0) for t in completed]
        result.avg_trade_duration = round(float(np.mean(durations)), 1) if durations else 0

    # --- Equity curve metrics ---
    if equity_curve:
        eq_series = pd.Series(equity_curve)

        # Max drawdown
        peak = eq_series.expanding().max()
        drawdown = (eq_series - peak) / peak
        result.max_drawdown = round(float(drawdown.min()), 4)

        # Returns for ratio calculations
        returns = eq_series.pct_change().dropna()

        # Annualization factor based on timeframe
        tf_minutes = _TIMEFRAME_MINUTES.get(timeframe, 60)
        periods_per_year = 525600 / tf_minutes  # 365.25 * 24 * 60 / tf_minutes
        ann_factor = np.sqrt(periods_per_year)

        # Volatility (annualized)
        if len(returns) > 2 and returns.std() > 0:
            result.volatility_annual = round(float(returns.std() * ann_factor), 4)

        # Sharpe ratio (annualized, risk-free = 0)
        if len(returns) > 2 and returns.std() > 0:
            result.sharpe_ratio = round(
                float((returns.mean() / returns.std()) * ann_factor), 4
            )

        # Sortino ratio (annualized, only downside deviation)
        downside = returns[returns < 0]
        if len(downside) > 0 and downside.std() > 0:
            result.sortino_ratio = round(
                float((returns.mean() / downside.std()) * ann_factor), 4
            )

        # Calmar ratio (annualized return / max drawdown)
        if result.max_drawdown < 0:
            ann_return = (1 + result.total_return) ** (periods_per_year / len(returns)) - 1
            result.calmar_ratio = round(ann_return / abs(result.max_drawdown), 4)

    # --- Backtest sanity check ---
    # Detect invalid backtests caused by cash constraint violations
    if balance < 0:
        result.is_valid = False
        result.error = "Backtest INVALID: cash went negative — strategy opened positions with insufficient funds"
    elif result.max_drawdown <= -1.0:
        result.is_valid = False
        result.error = "Backtest INVALID: max drawdown = -100% — total capital wipeout"
    elif abs(result.total_return) > 10.0:  # >1000% return is almost certainly a bug
        result.is_valid = False
        result.error = f"Backtest INVALID: total return {result.total_return:.2%} exceeds sanity threshold (1000%) — likely cash constraint violation"

    if not result.is_valid:
        # Reset metrics to safe values for display
        result.final_balance = 0.0
        result.total_return = -1.0  # -100%
        result.alpha = -1.0
        result.sharpe_ratio = 0.0
        result.sortino_ratio = 0.0
        result.calmar_ratio = 0.0

    return result


# ---------------------------------------------------------------------------
# Walk-Forward Analysis
# ---------------------------------------------------------------------------

@dataclass
class WalkForwardResult:
    """Walk-forward analysis result with in-sample and out-of-sample metrics."""
    in_sample: BacktestResult = field(default_factory=BacktestResult)
    out_of_sample: BacktestResult = field(default_factory=BacktestResult)
    overfitting_score: float = 0.0  # IS return - OOS return; higher = more overfit
    is_robust: bool = False  # True if OOS Sharpe > 0 and OOS return > 0
    split_ratio: float = 0.7
    error: str | None = None


def run_walk_forward(
    strategy_dsl: dict[str, Any],
    days: int = 180,
    initial_balance: float = 10000.0,
    in_sample_ratio: float = 0.7,
    fee: float = 0.001,
    slippage: float = 0.0005,
) -> WalkForwardResult:
    """Run walk-forward analysis (in-sample / out-of-sample split).

    Splits historical data into two segments:
    - In-sample (e.g. 70%): Used for strategy validation / parameter fitting
    - Out-of-sample (e.g. 30%): Unseen data to test generalization

    A robust strategy should show positive returns and similar Sharpe
    in both segments. Large divergence indicates overfitting.

    Args:
        strategy_dsl: Parsed strategy DSL dict.
        days: Total days of historical data.
        initial_balance: Starting balance.
        in_sample_ratio: Fraction of data for in-sample (0-1).
        fee: Trading fee per transaction.
        slippage: Slippage per transaction.

    Returns:
        WalkForwardResult with both segments and overfitting assessment.
    """
    strat = strategy_dsl["strategy"]
    market = strat["market"]
    indicators = strat["indicators"]
    entry = strat["entry"]
    exit_conf = strat.get("exit", {})
    risk = strat["risk"]

    # --- Fetch full dataset ---
    try:
        df = fetch_ohlcv(
            pair=market["pair"],
            timeframe=market["timeframe"],
            exchange_name=market["exchange"],
            days=days,
        )
    except Exception as e:
        return WalkForwardResult(error=f"Data fetch error: {e}")

    if df.empty or len(df) < 100:
        return WalkForwardResult(error="Insufficient data for walk-forward analysis")

    # --- Calculate indicators on full dataset (avoid lookahead in indicator calc) ---
    try:
        df = calculate_indicators(df, indicators)
    except Exception as e:
        return WalkForwardResult(error=f"Indicator calculation error: {e}")

    # --- Split data ---
    split_idx = int(len(df) * in_sample_ratio)
    df_is = df.iloc[:split_idx].copy()
    df_oos = df.iloc[split_idx:].copy()

    if len(df_is) < 50 or len(df_oos) < 50:
        return WalkForwardResult(error="Insufficient data after split")

    # --- Evaluate signals on each segment ---
    df_is = _evaluate_signals(df_is, entry, exit_conf)
    df_oos = _evaluate_signals(df_oos, entry, exit_conf)

    # --- Run backtests ---
    is_result = _simulate_trades(
        df=df_is,
        initial_balance=initial_balance,
        fee=fee,
        slippage=slippage,
        stop_loss=risk.get("stop_loss", -0.03),
        take_profit=risk.get("take_profit"),
        max_open_trades=risk.get("max_open_trades", 3),
        stake_amount=risk.get("stake_amount", 0.1),
        timeframe=market["timeframe"],
    )
    is_result.duration_days = int(days * in_sample_ratio)
    is_result.initial_balance = initial_balance

    oos_result = _simulate_trades(
        df=df_oos,
        initial_balance=initial_balance,
        fee=fee,
        slippage=slippage,
        stop_loss=risk.get("stop_loss", -0.03),
        take_profit=risk.get("take_profit"),
        max_open_trades=risk.get("max_open_trades", 3),
        stake_amount=risk.get("stake_amount", 0.1),
        timeframe=market["timeframe"],
    )
    oos_result.duration_days = int(days * (1 - in_sample_ratio))
    oos_result.initial_balance = initial_balance

    # --- Buy-and-hold benchmarks for each segment ---
    bh_is = initial_balance / df_is.iloc[0]["close"]
    is_result.benchmark_return = round(
        (df_is.iloc[-1]["close"] - df_is.iloc[0]["close"]) / df_is.iloc[0]["close"], 4
    )
    is_result.alpha = round(is_result.total_return - is_result.benchmark_return, 4)

    bh_oos = initial_balance / df_oos.iloc[0]["close"]
    oos_result.benchmark_return = round(
        (df_oos.iloc[-1]["close"] - df_oos.iloc[0]["close"]) / df_oos.iloc[0]["close"], 4
    )
    oos_result.alpha = round(oos_result.total_return - oos_result.benchmark_return, 4)

    # --- Overfitting assessment ---
    wf = WalkForwardResult(
        in_sample=is_result,
        out_of_sample=oos_result,
        split_ratio=in_sample_ratio,
    )
    wf.overfitting_score = round(is_result.total_return - oos_result.total_return, 4)
    wf.is_robust = (
        oos_result.sharpe_ratio > 0
        and oos_result.total_return > 0
        and oos_result.max_drawdown > -0.30
    )

    return wf
