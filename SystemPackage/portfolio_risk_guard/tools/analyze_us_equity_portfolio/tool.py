from __future__ import annotations

from datetime import datetime
import math
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from agent_factory.market_data.us_equities import (
    US_EQUITY_SOURCE_NAME,
    USMarketDataClient,
    us_equity_ticker,
)


BENCHMARK_TICKER = "^GSPC"


def run(arguments: dict, resources: dict) -> dict:
    del resources
    holdings = _holdings(arguments.get("holdings"))
    history_days = int(arguments.get("history_days", 250))
    if not 60 <= history_days <= 500:
        raise ValueError("history_days must be between 60 and 500")
    stress_scenarios = _stress_scenarios(arguments.get("stress_scenarios", []))
    observed_at = datetime.now(ZoneInfo("America/New_York")).isoformat()
    warnings: list[str] = []
    close_by_ticker: dict[str, pd.Series] = {}
    names: dict[str, str] = {}
    weight_basis = "provided_weights" if "weight" in holdings[0] else "latest_market_value"

    with USMarketDataClient() as market_data:
        for holding in holdings:
            ticker = holding["ticker"]
            try:
                quote = market_data.quote(ticker)
                close_by_ticker[ticker] = _close_series(
                    market_data.history(ticker, count=history_days, adjustment="adjusted"), ticker
                )
                names[ticker] = str(quote["name"])
            except Exception as exc:
                warnings.append(f"{ticker} market data unavailable: {type(exc).__name__}: {exc}")
        try:
            benchmark = _close_series(
                market_data.history(BENCHMARK_TICKER, count=history_days, adjustment="adjusted"),
                BENCHMARK_TICKER,
            )
        except Exception as exc:
            benchmark = None
            warnings.append(f"S&P 500 benchmark unavailable: {type(exc).__name__}: {exc}")

    if len(close_by_ticker) != len(holdings):
        return _error_result(observed_at, weight_basis, warnings)

    prices = pd.concat(close_by_ticker.values(), axis=1, join="inner").dropna()
    if len(prices) < 2:
        raise ValueError("holdings have fewer than two overlapping trading days")
    weights, weight_basis = _weights(holdings, close_by_ticker)
    returns = prices.pct_change().dropna()
    portfolio_returns = returns.mul(weights, axis="columns").sum(axis=1)
    equity = (1 + portfolio_returns).cumprod()
    drawdown = equity / equity.cummax() - 1
    benchmark_returns = benchmark.pct_change().dropna() if benchmark is not None else None
    portfolio_beta = _beta(portfolio_returns, benchmark_returns)
    portfolio = {
        "start_date": prices.index[0].date().isoformat(),
        "end_date": prices.index[-1].date().isoformat(),
        "observations": int(len(prices)),
        "period_return_pct": _percent(equity.iloc[-1] - 1),
        "annualized_volatility_pct": _percent(portfolio_returns.std() * math.sqrt(252)),
        "max_drawdown_pct": _percent(drawdown.min()),
        "beta_vs_sp500": portfolio_beta,
        "concentration_hhi": _number(float(np.square(weights.to_numpy()).sum())),
        "largest_weight_pct": _percent(weights.max()),
    }

    holding_results: list[dict[str, Any]] = []
    for holding in holdings:
        ticker = holding["ticker"]
        close = close_by_ticker[ticker]
        item_returns = close.pct_change().dropna()
        latest_close = float(close.iloc[-1])
        item = {
            "ticker": ticker,
            "name": names[ticker],
            "weight_pct": _percent(weights[ticker]),
            "latest_close": _number(latest_close),
            "latest_date": close.index[-1].date().isoformat(),
            "period_return_pct": _percent(close.iloc[-1] / close.iloc[0] - 1),
            "annualized_volatility_pct": _percent(item_returns.std() * math.sqrt(252)),
            "max_drawdown_pct": _percent((close / close.cummax() - 1).min()),
            "beta_vs_sp500": _beta(item_returns, benchmark_returns),
            "cost_return_pct": None,
        }
        if "cost_price" in holding:
            item["cost_return_pct"] = _percent(latest_close / holding["cost_price"] - 1)
        holding_results.append(item)

    correlation = returns.corr()
    stress_results = [
        {
            "sp500_shock_pct": shock,
            "estimated_portfolio_change_pct": (
                _number(shock * portfolio_beta) if portfolio_beta is not None else None
            ),
            "method": "historical beta approximation",
        }
        for shock in stress_scenarios
    ]
    return {
        "status": "partial" if warnings else "success",
        "observed_at": observed_at,
        "source": US_EQUITY_SOURCE_NAME,
        "adjustment": "Yahoo Finance adjusted close",
        "benchmark": "S&P 500 (^GSPC)",
        "weight_basis": weight_basis,
        "portfolio": portfolio,
        "holdings": holding_results,
        "highest_correlation": _highest_correlation(correlation),
        "stress_results": stress_results,
        "warnings": warnings,
        "message": (
            "U.S. equity portfolio risk metrics completed. Historical statistics and beta-based "
            "stress estimates do not predict future performance."
        ),
    }


def _error_result(observed_at: str, weight_basis: str, warnings: list[str]) -> dict[str, Any]:
    return {
        "status": "error",
        "observed_at": observed_at,
        "source": US_EQUITY_SOURCE_NAME,
        "adjustment": "Yahoo Finance adjusted close",
        "benchmark": "S&P 500 (^GSPC)",
        "weight_basis": weight_basis,
        "portfolio": {},
        "holdings": [],
        "highest_correlation": None,
        "stress_results": [],
        "warnings": warnings,
        "message": "At least one holding lacks valid history; no partial portfolio was calculated.",
    }


def _close_series(rows: list[dict[str, Any]], ticker: str) -> pd.Series:
    frame = pd.DataFrame(rows)
    dates = pd.to_datetime(frame["date"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    series = pd.Series(close.to_numpy(), index=dates, name=ticker).dropna()
    series = series.loc[~series.index.isna()]
    if len(series) < 2:
        raise ValueError("not enough valid history")
    return series


def _holdings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise ValueError("holdings must contain 1 to 20 items")
    normalized: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("each holding must be an object")
        ticker = us_equity_ticker(raw.get("ticker"))
        has_weight = raw.get("weight") is not None
        has_shares = raw.get("shares") is not None
        if has_weight == has_shares:
            raise ValueError(f"holding {ticker} must provide exactly one of weight or shares")
        key = "weight" if has_weight else "shares"
        item: dict[str, Any] = {"ticker": ticker, key: _positive(raw[key], field=f"{ticker}.{key}")}
        if raw.get("cost_price") is not None:
            item["cost_price"] = _positive(raw["cost_price"], field=f"{ticker}.cost_price")
        normalized.append(item)
    tickers = [item["ticker"] for item in normalized]
    if len(tickers) != len(set(tickers)):
        raise ValueError("holding tickers must be unique")
    if len({"weight" if "weight" in item else "shares" for item in normalized}) != 1:
        raise ValueError("all holdings must use the same weight or shares basis")
    return normalized


def _weights(
    holdings: list[dict[str, Any]], close_by_ticker: dict[str, pd.Series]
) -> tuple[pd.Series, str]:
    if "weight" in holdings[0]:
        raw = pd.Series({item["ticker"]: item["weight"] for item in holdings}, dtype=float)
        basis = "provided_weights"
    else:
        raw = pd.Series({
            item["ticker"]: item["shares"] * float(close_by_ticker[item["ticker"]].iloc[-1])
            for item in holdings
        }, dtype=float)
        basis = "latest_market_value"
    total = float(raw.sum())
    if not math.isfinite(total) or total <= 0:
        raise ValueError("holding basis must have a positive finite total")
    return raw / total, basis


def _stress_scenarios(value: Any) -> list[float]:
    if not isinstance(value, list) or len(value) > 5:
        raise ValueError("stress_scenarios must contain at most 5 numbers")
    scenarios: list[float] = []
    for item in value:
        shock = float(item)
        if not math.isfinite(shock) or not -50 <= shock <= 50:
            raise ValueError("stress scenarios must be between -50 and 50 percent")
        scenarios.append(shock)
    return scenarios


def _beta(returns: pd.Series, benchmark_returns: pd.Series | None) -> float | None:
    if benchmark_returns is None:
        return None
    aligned = pd.concat([returns.rename("asset"), benchmark_returns.rename("benchmark")], axis=1).dropna()
    if len(aligned) < 2:
        return None
    variance = float(aligned["benchmark"].var())
    if not math.isfinite(variance) or variance <= 0:
        return None
    return _number(float(aligned.cov().loc["asset", "benchmark"]) / variance)


def _highest_correlation(correlation: pd.DataFrame) -> dict[str, Any] | None:
    if len(correlation.columns) < 2:
        return None
    best: tuple[str, str, float] | None = None
    columns = list(correlation.columns)
    for index, left in enumerate(columns):
        for right in columns[index + 1 :]:
            value = float(correlation.loc[left, right])
            if math.isfinite(value) and (best is None or value > best[2]):
                best = (left, right, value)
    return None if best is None else {
        "left_ticker": best[0], "right_ticker": best[1], "correlation": _number(best[2])
    }


def _positive(value: Any, *, field: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{field} must be a positive finite number")
    return parsed


def _number(value: Any) -> float | None:
    parsed = float(value)
    return round(parsed, 4) if math.isfinite(parsed) else None


def _percent(value: Any) -> float | None:
    return _number(float(value) * 100)
