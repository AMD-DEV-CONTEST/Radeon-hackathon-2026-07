"""Fetch historical OHLCV data from crypto exchanges via CCXT.

Falls back to synthetic data generation when exchange APIs are unreachable
(e.g., network-restricted cloud instances).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import ccxt
import numpy as np
import pandas as pd


# Exchange instances (lazy init)
_exchanges: dict[str, ccxt.Exchange] = {}

# Synthetic data cache
_synthetic_cache: dict[str, pd.DataFrame] = {}


def get_exchange(name: str = "binance") -> ccxt.Exchange:
    """Get or create a CCXT exchange instance."""
    if name not in _exchanges:
        exchange_class = getattr(ccxt, name)
        _exchanges[name] = exchange_class({"enableRateLimit": True})
    return _exchanges[name]


def fetch_ohlcv(
    pair: str = "BTC/USDT",
    timeframe: str = "1h",
    exchange_name: str = "binance",
    days: int = 180,
    since: int | None = None,
    limit: int = 1000,
) -> pd.DataFrame:
    """Fetch historical OHLCV data.

    Tries real exchange first; falls back to synthetic data on network error.
    """
    try:
        exchange = get_exchange(exchange_name)
        if since is None:
            since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)

        all_data: list[list] = []
        while True:
            ohlcv = exchange.fetch_ohlcv(pair, timeframe, since=since, limit=limit)
            if not ohlcv:
                break
            all_data.extend(ohlcv)
            since = ohlcv[-1][0] + 1
            if len(ohlcv) < limit:
                break

        if all_data:
            df = pd.DataFrame(all_data, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("datetime", inplace=True)
            df.drop(columns=["timestamp"], inplace=True)
            return df
    except Exception as e:
        print(f"[DataFetcher] Exchange API unreachable ({e.__class__.__name__}), using synthetic data")

    return _generate_synthetic_ohlcv(pair, timeframe, days)


def _generate_synthetic_ohlcv(
    pair: str,
    timeframe: str,
    days: int,
) -> pd.DataFrame:
    """Generate realistic synthetic OHLCV data.

    Uses Student-t distribution + GARCH(1,1) volatility clustering +
    market regime switching to produce data that closely mimics real
    crypto markets:
    - Fat tails (excess kurtosis from Student-t)
    - Volatility clustering (high vol follows high vol)
    - Market regime shifts (bull / bear / sideways)
    - Volume-price correlation (volume spikes on large moves)
    """
    cache_key = f"{pair}_{timeframe}_{days}"
    if cache_key in _synthetic_cache:
        return _synthetic_cache[cache_key]

    # Pair-specific parameters
    base_prices = {
        "BTC/USDT": 65000,
        "ETH/USDT": 3500,
        "BNB/USDT": 600,
        "SOL/USDT": 150,
    }
    base_price = base_prices.get(pair, 1000)

    # Volatility per timeframe
    tf_minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440, "1w": 10080}
    minutes = tf_minutes.get(timeframe, 60)
    periods_per_year = 525600 / minutes
    base_sigma = 0.70 / np.sqrt(periods_per_year)  # 70% annual vol → per-candle
    base_mu = 0.15 / periods_per_year  # 15% annual drift

    # Generate timestamps
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    freq = pd.Timedelta(minutes=minutes)
    timestamps = pd.date_range(start=start, end=end, freq=freq)
    n = len(timestamps)

    np.random.seed(42)

    # --- Market regime switching (Markov chain) ---
    # States: 0=bull, 1=bear, 2=sideways
    # Transition matrix (probabilities of staying / switching)
    transition = np.array([
        [0.97, 0.02, 0.01],  # bull → bull/bear/sideways
        [0.02, 0.96, 0.02],  # bear → bull/bear/sideways
        [0.04, 0.03, 0.93],  # sideways → bull/bear/sideways
    ])
    regime_params = {
        0: {"mu": base_mu * 3.0,  "sigma": base_sigma * 1.2,  "vol_mult": 1.3},  # bull: high drift, higher vol
        1: {"mu": -base_mu * 2.5, "sigma": base_sigma * 1.5,  "vol_mult": 1.8},  # bear: negative drift, high vol
        2: {"mu": 0.0,            "sigma": base_sigma * 0.6,  "vol_mult": 0.7},  # sideways: no drift, low vol
    }

    regime = 0  # Start in bull market
    regimes = np.zeros(n, dtype=int)

    # --- GARCH(1,1) parameters ---
    omega = base_sigma**2 * 0.05  # long-run variance contribution
    alpha_garch = 0.10  # reaction to recent shocks
    beta_garch = 0.85   # persistence of variance
    var_t = base_sigma**2  # Initial variance

    # --- Generate returns with regime + GARCH + Student-t ---
    from scipy.stats import t as student_t
    df_t = 5  # degrees of freedom (fat tails; normal = inf)

    returns = np.zeros(n)
    min_variance = (base_sigma * 0.25) ** 2
    max_variance = (base_sigma * 6.0) ** 2
    for i in range(n):
        # Regime transition
        regime = np.random.choice(3, p=transition[regime])
        regimes[i] = regime
        params = regime_params[regime]

        # GARCH(1,1) variance update
        if i > 0:
            var_t = omega + alpha_garch * returns[i-1]**2 + beta_garch * var_t
        # Student-t shocks can otherwise make recursive GARCH variance explode.
        # Bound variance to a realistic per-candle range before sampling.
        var_t = float(np.clip(var_t, min_variance, max_variance))
        # Scale variance by regime volatility multiplier
        effective_sigma = np.sqrt(var_t) * params["vol_mult"]

        # Student-t sample (fat tails)
        raw = student_t.rvs(df=df_t, size=1)[0]
        # Scale to desired std
        scaled = raw * effective_sigma / np.sqrt(df_t / (df_t - 2))
        # A single synthetic candle must never create non-finite prices. 12% is
        # deliberately generous for crypto while still preventing exp overflow.
        returns[i] = float(np.clip(params["mu"] + scaled, -0.12, 0.12))

    # --- Build price path ---
    # Keep the full synthetic path plausible for the requested horizon. The
    # bound expands with sqrt(time), matching how volatility scales over time.
    max_price_factor = 1.0 + 1.5 * np.sqrt(max(days, 1) / 365.0)
    max_log_move = np.log(max_price_factor)
    cumulative_returns = np.clip(np.cumsum(returns), -max_log_move, max_log_move)
    prices = base_price * np.exp(cumulative_returns)
    # Ensure prices stay positive
    prices = np.maximum(prices, base_price * 0.1)

    # --- Volume with price-volume correlation ---
    abs_returns = np.abs(returns)
    vol_base = np.random.lognormal(mean=15, sigma=1.0, size=n)
    # Volume spikes on large price moves (correlation with |returns|)
    vol_multiplier = 1.0 + abs_returns / (base_sigma + 1e-8) * 0.5
    # Higher volume in high-volatility regimes
    for i in range(n):
        regime_vol_mult = regime_params[regimes[i]]["vol_mult"]
        vol_multiplier[i] *= regime_vol_mult
    volumes = vol_base * vol_multiplier

    # --- Build OHLCV from close prices ---
    intraday_vol = np.maximum(np.abs(returns), 0.001) * prices * 0.5
    opens = np.roll(prices, 1)
    opens[0] = prices[0]

    highs = np.maximum(opens, prices) + np.random.uniform(0, 1, n) * intraday_vol
    lows = np.minimum(opens, prices) - np.random.uniform(0, 1, n) * intraday_vol
    lows = np.maximum(lows, prices * 0.90)

    df = pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": prices,
        "volume": volumes,
    }, index=timestamps[:n])

    _synthetic_cache[cache_key] = df
    print(f"[DataFetcher] Generated {len(df)} synthetic candles for {pair} {timeframe}"
          f" (GARCH + Student-t + regime switching)")
    return df


def get_market_summary(
    pair: str = "BTC/USDT",
    exchange_name: str = "binance",
) -> dict[str, Any]:
    """Get current market summary for a trading pair.

    Returns dict with last_price, 24h_change, volume, high, low.
    """
    try:
        exchange = get_exchange(exchange_name)
        ticker = exchange.fetch_ticker(pair)
        return {
            "pair": pair,
            "exchange": exchange_name,
            "last_price": ticker.get("last", 0),
            "change_pct": ticker.get("percentage", 0),
            "high_24h": ticker.get("high", 0),
            "low_24h": ticker.get("low", 0),
            "volume_24h": ticker.get("baseVolume", 0),
            "quote_volume_24h": ticker.get("quoteVolume", 0),
            "timestamp": ticker.get("timestamp", 0),
        }
    except Exception:
        # Fallback to synthetic data's last value
        df = fetch_ohlcv(pair, "1h", exchange_name, days=1)
        if df.empty:
            return {"pair": pair, "exchange": exchange_name, "last_price": 0,
                    "change_pct": 0, "high_24h": 0, "low_24h": 0,
                    "volume_24h": 0, "quote_volume_24h": 0, "timestamp": 0}
        last = df.iloc[-1]
        first = df.iloc[0]
        return {
            "pair": pair,
            "exchange": exchange_name,
            "last_price": float(last["close"]),
            "change_pct": float((last["close"] - first["open"]) / first["open"] * 100),
            "high_24h": float(df["high"].max()),
            "low_24h": float(df["low"].min()),
            "volume_24h": float(df["volume"].sum()),
            "quote_volume_24h": float(df["volume"].sum() * last["close"]),
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
        }


def calculate_indicators(
    df: pd.DataFrame,
    indicators: list[dict],
) -> pd.DataFrame:
    """Calculate technical indicators on a price DataFrame.

    Args:
        df: DataFrame with OHLCV columns.
        indicators: List of indicator specs from the DSL.

    Returns:
        DataFrame with indicator columns added.
    """
    import talib

    for ind in indicators:
        name = ind["name"]
        ind_type = ind["type"]
        params = ind.get("params", {})
        field = params.get("field", "close")
        period = params.get("period", 14)
        data = df[field].values

        if ind_type == "SMA":
            df[name] = talib.SMA(data, timeperiod=period)
        elif ind_type == "EMA":
            df[name] = talib.EMA(data, timeperiod=period)
        elif ind_type == "RSI":
            df[name] = talib.RSI(data, timeperiod=period)
        elif ind_type == "MACD":
            fast = params.get("fast_period", 12)
            slow = params.get("slow_period", 26)
            signal = params.get("signal_period", 9)
            macd, signal_line, hist = talib.MACD(
                data, fastperiod=fast, slowperiod=slow, signalperiod=signal
            )
            df[name] = macd
            df[f"{name}_signal"] = signal_line
            df[f"{name}_hist"] = hist
        elif ind_type == "ATR":
            df[name] = talib.ATR(
                df["high"].values, df["low"].values, df["close"].values,
                timeperiod=period,
            )
        elif ind_type == "BollingerBands":
            std = params.get("std_dev", 2.0)
            upper, middle, lower = talib.BBANDS(
                data, timeperiod=period, nbdevup=std, nbdevdn=std,
            )
            df[f"{name}_upper"] = upper
            df[f"{name}_middle"] = middle
            df[f"{name}_lower"] = lower
        elif ind_type == "ADX":
            df[name] = talib.ADX(
                df["high"].values, df["low"].values, df["close"].values,
                timeperiod=period,
            )
        elif ind_type == "CCI":
            df[name] = talib.CCI(
                df["high"].values, df["low"].values, df["close"].values,
                timeperiod=period,
            )
        elif ind_type == "OBV":
            df[name] = talib.OBV(data, df["volume"].values)
        elif ind_type == "Stochastic":
            k, d = talib.STOCH(
                df["high"].values, df["low"].values, df["close"].values,
                fastk_period=period,
            )
            df[f"{name}_k"] = k
            df[f"{name}_d"] = d
        elif ind_type == "WMA":
            df[name] = talib.WMA(data, timeperiod=period)
        elif ind_type == "VWAP":
            # TA-Lib doesn't have a direct VWAP; compute manually
            # VWAP = cumsum(typical_price * volume) / cumsum(volume)
            typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
            cum_tp_vol = (typical_price * df["volume"]).cumsum()
            cum_vol = df["volume"].cumsum()
            df[name] = (cum_tp_vol / cum_vol).fillna(method="ffill")
        elif ind_type == "HMA":
            # Hull MA: WMA(2*WMA(n/2) - WMA(n), sqrt(n))
            import numpy as _np
            half_period = max(1, period // 2)
            sqrt_period = max(1, int(_np.sqrt(period)))
            wma_half = talib.WMA(data, timeperiod=half_period)
            wma_full = talib.WMA(data, timeperiod=period)
            raw = 2 * wma_half - wma_full
            df[name] = talib.WMA(raw, timeperiod=sqrt_period)
        elif ind_type == "ZLEMA":
            # Zero-Lag EMA: EMA of (2*price - price(delay))
            delay = max(1, period // 2)
            delayed = pd.Series(data).shift(delay).values
            adjusted = 2 * data - delayed
            df[name] = talib.EMA(adjusted, timeperiod=period)
        elif ind_type == "Supertrend":
            # Supertrend = (hl2 ± multiplier * ATR)
            # Direction flips when price crosses the band
            multiplier = params.get("multiplier", 3.0)
            hl2 = (df["high"] + df["low"]) / 2.0
            atr = talib.ATR(
                df["high"].values, df["low"].values, df["close"].values,
                timeperiod=period,
            )
            upper_band = hl2 + multiplier * atr
            lower_band = hl2 - multiplier * atr
            # Determine trend direction
            close = df["close"].values
            st = pd.Series(index=df.index, dtype=float)
            direction = 1  # 1=uptrend, -1=downtrend
            for i in range(len(close)):
                if i == 0:
                    st.iloc[i] = lower_band[i]
                    continue
                if close[i] > upper_band[i - 1]:
                    direction = 1
                elif close[i] < lower_band[i - 1]:
                    direction = -1
                if direction == 1:
                    st.iloc[i] = max(lower_band[i], st.iloc[i - 1]) if pd.notna(st.iloc[i - 1]) else lower_band[i]
                else:
                    st.iloc[i] = min(upper_band[i], st.iloc[i - 1]) if pd.notna(st.iloc[i - 1]) else upper_band[i]
            df[name] = st
        elif ind_type == "ICHIMOKU":
            # Ichimoku Cloud: conversion, base, spanA, spanB, lagging
            high = df["high"].values
            low = df["low"].values
            conv_period = params.get("fast_period", 9)
            base_period = params.get("slow_period", 26)
            span_b_period = period * 2
            # Tenkan-sen (Conversion)
            df[f"{name}_tenkan"] = (
                pd.Series(high).rolling(conv_period).max() +
                pd.Series(low).rolling(conv_period).min()
            ) / 2.0
            # Kijun-sen (Base)
            df[f"{name}_kijun"] = (
                pd.Series(high).rolling(base_period).max() +
                pd.Series(low).rolling(base_period).min()
            ) / 2.0
            # Senkou Span A
            df[f"{name}_spanA"] = (df[f"{name}_tenkan"] + df[f"{name}_kijun"]) / 2.0
            # Senkou Span B
            df[f"{name}_spanB"] = (
                pd.Series(high).rolling(span_b_period).max() +
                pd.Series(low).rolling(span_b_period).min()
            ) / 2.0
            # Main line = Span A for signal evaluation
            df[name] = df[f"{name}_spanA"]
        else:
            df[name] = talib.SMA(data, timeperiod=period)

    return df
