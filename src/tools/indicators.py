"""Technical indicator calculator tool.

Calculates indicators on raw OHLCV data, exposed as API endpoints
for Dify to call during strategy analysis.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel


router = APIRouter(prefix="/indicators", tags=["indicators"])


class IndicatorRequest(BaseModel):
    candles: list[dict[str, Any]]  # OHLCV dicts
    indicators: list[dict[str, Any]]  # Indicator specs from DSL


class IndicatorResponse(BaseModel):
    values: dict[str, list[float | None]]
    last_values: dict[str, float | None]


@router.post("/calculate", response_model=IndicatorResponse)
async def calculate(req: IndicatorRequest):
    """Calculate technical indicators on provided candle data."""
    import pandas as pd
    import talib

    df = pd.DataFrame(req.candles)
    if "datetime" in df.columns:
        df.drop(columns=["datetime"], inplace=True)

    values: dict[str, list[float | None]] = {}
    last_values: dict[str, float | None] = {}

    for ind in req.indicators:
        name = ind["name"]
        ind_type = ind["type"]
        params = ind.get("params", {})
        field = params.get("field", "close")
        period = params.get("period", 14)
        data = df[field].values

        result: list[float | None] = []

        if ind_type == "SMA":
            result = talib.SMA(data, timeperiod=period).tolist()
        elif ind_type == "EMA":
            result = talib.EMA(data, timeperiod=period).tolist()
        elif ind_type == "RSI":
            result = talib.RSI(data, timeperiod=period).tolist()
        elif ind_type == "MACD":
            fast = params.get("fast_period", 12)
            slow = params.get("slow_period", 26)
            signal = params.get("signal_period", 9)
            macd, _, _ = talib.MACD(data, fastperiod=fast, slowperiod=slow, signalperiod=signal)
            result = macd.tolist()
        elif ind_type == "ATR":
            result = talib.ATR(
                df["high"].values, df["low"].values, df["close"].values,
                timeperiod=period,
            ).tolist()
        elif ind_type == "BollingerBands":
            std = params.get("std_dev", 2.0)
            upper, middle, lower = talib.BBANDS(data, timeperiod=period, nbdevup=std, nbdevdn=std)
            values[f"{name}_upper"] = upper.tolist()
            values[f"{name}_middle"] = middle.tolist()
            values[f"{name}_lower"] = lower.tolist()
            last_values[f"{name}_upper"] = upper[-1] if len(upper) > 0 else None
            last_values[f"{name}_middle"] = middle[-1] if len(middle) > 0 else None
            last_values[f"{name}_lower"] = lower[-1] if len(lower) > 0 else None
            continue
        elif ind_type == "ADX":
            result = talib.ADX(
                df["high"].values, df["low"].values, df["close"].values,
                timeperiod=period,
            ).tolist()
        elif ind_type == "CCI":
            result = talib.CCI(
                df["high"].values, df["low"].values, df["close"].values,
                timeperiod=period,
            ).tolist()
        elif ind_type == "OBV":
            result = talib.OBV(data, df["volume"].values).tolist()
        elif ind_type == "Stochastic":
            k, d = talib.STOCH(
                df["high"].values, df["low"].values, df["close"].values,
                fastk_period=period,
            )
            values[f"{name}_k"] = k.tolist()
            values[f"{name}_d"] = d.tolist()
            last_values[f"{name}_k"] = k[-1] if len(k) > 0 else None
            last_values[f"{name}_d"] = d[-1] if len(d) > 0 else None
            continue
        elif ind_type == "WMA":
            result = talib.WMA(data, timeperiod=period).tolist()
        elif ind_type == "VWAP":
            import pandas as _pd
            typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
            cum_tp_vol = (typical_price * df["volume"]).cumsum()
            cum_vol = df["volume"].cumsum()
            vwap = (cum_tp_vol / cum_vol).fillna(method="ffill")
            result = vwap.tolist()
        elif ind_type == "HMA":
            import numpy as _np
            half_period = max(1, period // 2)
            sqrt_period = max(1, int(_np.sqrt(period)))
            wma_half = talib.WMA(data, timeperiod=half_period)
            wma_full = talib.WMA(data, timeperiod=period)
            raw = 2 * wma_half - wma_full
            result = talib.WMA(raw, timeperiod=sqrt_period).tolist()
        elif ind_type == "ZLEMA":
            import pandas as _pd
            delay = max(1, period // 2)
            delayed = _pd.Series(data).shift(delay).values
            adjusted = 2 * data - delayed
            result = talib.EMA(adjusted, timeperiod=period).tolist()
        elif ind_type == "Supertrend":
            multiplier = params.get("multiplier", 3.0)
            import pandas as _pd
            hl2 = (df["high"] + df["low"]) / 2.0
            atr = talib.ATR(
                df["high"].values, df["low"].values, df["close"].values,
                timeperiod=period,
            )
            upper_band = hl2 + multiplier * atr
            lower_band = hl2 - multiplier * atr
            close = df["close"].values
            st = _pd.Series(index=df.index, dtype=float)
            direction = 1
            for i in range(len(close)):
                if i == 0:
                    st.iloc[i] = lower_band[i]
                    continue
                if close[i] > upper_band[i - 1]:
                    direction = 1
                elif close[i] < lower_band[i - 1]:
                    direction = -1
                if direction == 1:
                    st.iloc[i] = max(lower_band[i], st.iloc[i - 1]) if _pd.notna(st.iloc[i - 1]) else lower_band[i]
                else:
                    st.iloc[i] = min(upper_band[i], st.iloc[i - 1]) if _pd.notna(st.iloc[i - 1]) else upper_band[i]
            result = st.tolist()
        elif ind_type == "ICHIMOKU":
            import pandas as _pd
            high = df["high"].values
            low = df["low"].values
            conv_period = params.get("fast_period", 9)
            base_period = params.get("slow_period", 26)
            span_b_period = period * 2
            tenkan = ((_pd.Series(high).rolling(conv_period).max() + _pd.Series(low).rolling(conv_period).min()) / 2.0).tolist()
            kijun = ((_pd.Series(high).rolling(base_period).max() + _pd.Series(low).rolling(base_period).min()) / 2.0).tolist()
            spanA = ((tenkan[i] + kijun[i]) / 2.0 for i in range(len(tenkan)))
            result = list(spanA)
        else:
            result = talib.SMA(data, timeperiod=period).tolist()

        # Replace NaN with None
        result = [None if x != x else x for x in result]  # NaN check
        values[name] = result
        last_values[name] = result[-1] if result else None

    return IndicatorResponse(values=values, last_values=last_values)
