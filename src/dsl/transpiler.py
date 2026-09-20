"""DSL → Freqtrade IStrategy transpiler.

Converts a validated strategy DSL dict into a Python source file
containing a Freqtrade IStrategy subclass, ready for backtesting.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


# Maps DSL indicator type → Freqtrade indicator import
_INDICATOR_MAP: dict[str, tuple[str, str]] = {
    # DSL type: (Freqtrade indicator class, import path)
    "SMA": ("SMAIndicator", "talipp.indicators.SMA"),
    "EMA": ("EMA", "talipp.indicators.EMA"),
    "RSI": ("RSI", "talipp.indicators.RSI"),
    "MACD": ("MACD", "talipp.indicators.MACD"),
    "ATR": ("ATR", "talipp.indicators.ATR"),
    "BollingerBands": ("BB", "talipp.indicators.BB"),
    "Stochastic": ("Stoch", "talipp.indicators.Stoch"),
    "ADX": ("ADX", "talipp.indicators.ADX"),
    "CCI": ("CCI", "talipp.indicators.CCI"),
    "OBV": ("OBV", "talipp.indicators.OBV"),
    "VWAP": ("VWAP", "talipp.indicators.VWAP"),
    "WMA": ("WMA", "talipp.indicators.WMA"),
    "HMA": ("HMA", "talipp.indicators.HMA"),
    "ZLEMA": ("ZLEMA", "talipp.indicators.ZLEMA"),
    "Supertrend": ("Supertrend", "talipp.indicators.Supertrend"),
    "ICHIMOKU": ("Ichimoku", "talipp.indicators.Ichimoku"),
}

# Boolean operator translation: DSL expr → pandas expression
_EXPR_TRANSLATIONS = [
    (" AND ", " & "),
    (" and ", " & "),
    (" OR ", " | "),
    (" or ", " | "),
    (" NOT ", " ~"),
    (" not ", " ~"),
    ("True", "True"),
    ("False", "False"),
    ("null", "None"),
    ("None", "None"),
]


def transpile_to_freqtrade(dsl: dict[str, Any]) -> str:
    """Transpile a validated DSL dict into Freqtrade IStrategy Python source.

    Args:
        dsl: Parsed strategy DSL dict (must pass validation).

    Returns:
        Python source code string for a Freqtrade strategy file.
    """
    strat = dsl["strategy"]
    name = strat["name"]
    indicators = strat["indicators"]
    entry = strat["entry"]
    exit_conf = strat.get("exit", {})
    risk = strat["risk"]

    lines: list[str] = []
    lines.append('"""')
    lines.append(f"Auto-generated Freqtrade strategy: {name}")
    lines.append(f"Generated: {datetime.now().isoformat()}")
    lines.append("Transpiled from trading strategy DSL.")
    lines.append('"""')
    lines.append("from freqtrade.strategy import IStrategy, DecimalParameter, IntParameter")
    lines.append("from pandas import DataFrame")
    lines.append("import pandas as pd")
    lines.append("import talipp.indicators as ti")
    lines.append("")
    lines.append("")
    lines.append(f"class {name}(IStrategy):")
    lines.append(f'    """{name} — auto-generated from DSL."""')
    lines.append("")

    # --- Strategy parameters ---
    lines.append("    # Strategy version")
    lines.append("    INTERFACE_VERSION = 3")
    lines.append("")

    # --- Timeframe ---
    timeframe = strat["market"]["timeframe"]
    lines.append(f"    timeframe = '{timeframe}'")
    lines.append("")

    # --- Risk parameters ---
    lines.append("    # Risk management")
    lines.append(f"    stoploss = {risk['stop_loss']}")
    if risk.get("take_profit"):
        lines.append(
            f"    minimal_roi = {{0: {risk['take_profit']}}}"
        )
    else:
        lines.append("    minimal_roi = {'0': 0.10}")
    lines.append(f"    max_open_trades = {risk['max_open_trades']}")
    lines.append(f"    stake_amount = {repr(risk['stake_amount'])}")
    lines.append(f"    trailing_stop = {risk.get('trailing_stop', False)}")
    if risk.get("trailing_stop_positive"):
        lines.append(
            f"    trailing_stop_positive = {risk['trailing_stop_positive']}"
        )
    if risk.get("trailing_stop_positive_offset"):
        lines.append(
            f"    trailing_stop_positive_offset = "
            f"{risk['trailing_stop_positive_offset']}"
        )
    lines.append("    use_exit_signal = True")
    lines.append("    can_short = " + ("True" if entry.get("short") else "False"))
    lines.append("")

    # --- populate_indicators ---
    lines.append("    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:")
    for ind in indicators:
        ind_name = ind["name"]
        ind_type = ind["type"]
        params = ind.get("params", {})
        field = params.get("field", "close")
        period = params.get("period", 14)

        if ind_type == "MACD":
            fast = params.get("fast_period", 12)
            slow = params.get("slow_period", 26)
            signal = params.get("signal_period", 9)
            lines.append(
                f"        macd_{ind_name} = ti.MACD("
                f"input_values=dataframe['close'].tolist(), "
                f"fast_period={fast}, slow_period={slow}, "
                f"signal_period={signal})"
            )
            lines.append(
                f"        dataframe['{ind_name}'] = "
                f"[v.macd_line if v else None for v in macd_{ind_name}]"
            )
        elif ind_type == "BollingerBands":
            std = params.get("std_dev", 2.0)
            lines.append(
                f"        bb_{ind_name} = ti.BB("
                f"input_values=dataframe['{field}'].tolist(), "
                f"period={period}, std_dev={std})"
            )
            lines.append(
                f"        dataframe['{ind_name}_upper'] = "
                f"[v.upper_bb if v else None for v in bb_{ind_name}]"
            )
            lines.append(
                f"        dataframe['{ind_name}_lower'] = "
                f"[v.lower_bb if v else None for v in bb_{ind_name}]"
            )
        elif ind_type == "Stochastic":
            lines.append(
                f"        stoch_{ind_name} = ti.Stoch("
                f"high=dataframe['high'].tolist(), "
                f"low=dataframe['low'].tolist(), "
                f"close=dataframe['close'].tolist(), "
                f"period={period})"
            )
            lines.append(
                f"        dataframe['{ind_name}'] = "
                f"[v.k if v else None for v in stoch_{ind_name}]"
            )
        elif ind_type == "Supertrend":
            # Supertrend: ATR-based trend following indicator
            multiplier = params.get("multiplier", 3.0)
            lines.append(f"        atr_{ind_name} = ti.ATR(")
            lines.append(f"            input_values_high=dataframe['high'].tolist(),")
            lines.append(f"            input_values_low=dataframe['low'].tolist(),")
            lines.append(f"            input_values_close=dataframe['close'].tolist(),")
            lines.append(f"            period={period})")
            lines.append(f"        # Supertrend calculation")
            lines.append(f"        hl2_{ind_name} = (dataframe['high'] + dataframe['low']) / 2.0")
            lines.append(f"        atr_vals_{ind_name} = [v if v else 0.0 for v in atr_{ind_name}]")
            lines.append(f"        upper_{ind_name} = hl2_{ind_name} + {multiplier} * pd.Series(atr_vals_{ind_name})")
            lines.append(f"        lower_{ind_name} = hl2_{ind_name} - {multiplier} * pd.Series(atr_vals_{ind_name})")
            lines.append(f"        # Determine trend direction")
            lines.append(f"        st_{ind_name} = pd.Series(index=dataframe.index, dtype=float)")
            lines.append(f"        direction_{ind_name} = 1")
            lines.append(f"        for i in range(len(dataframe)):")
            lines.append(f"            if i == 0:")
            lines.append(f"                st_{ind_name}.iloc[i] = lower_{ind_name}.iloc[i]")
            lines.append(f"                continue")
            lines.append(f"            if dataframe['close'].iloc[i] > upper_{ind_name}.iloc[i-1]:")
            lines.append(f"                direction_{ind_name} = 1")
            lines.append(f"            elif dataframe['close'].iloc[i] < lower_{ind_name}.iloc[i-1]:")
            lines.append(f"                direction_{ind_name} = -1")
            lines.append(f"            if direction_{ind_name} == 1:")
            lines.append(f"                st_{ind_name}.iloc[i] = max(lower_{ind_name}.iloc[i], st_{ind_name}.iloc[i-1]) if pd.notna(st_{ind_name}.iloc[i-1]) else lower_{ind_name}.iloc[i]")
            lines.append(f"            else:")
            lines.append(f"                st_{ind_name}.iloc[i] = min(upper_{ind_name}.iloc[i], st_{ind_name}.iloc[i-1]) if pd.notna(st_{ind_name}.iloc[i-1]) else upper_{ind_name}.iloc[i]")
            lines.append(f"        dataframe['{ind_name}'] = st_{ind_name}")
        elif ind_type == "ICHIMOKU":
            # Ichimoku Cloud: Tenkan, Kijun, SpanA, SpanB
            conv_period = params.get("fast_period", 9)
            base_period = params.get("slow_period", 26)
            span_b_period = period * 2
            lines.append(f"        # Ichimoku Cloud components")
            lines.append(f"        high_s_{ind_name} = dataframe['high'].rolling({conv_period}).max()")
            lines.append(f"        low_s_{ind_name} = dataframe['low'].rolling({conv_period}).min()")
            lines.append(f"        dataframe['{ind_name}_tenkan'] = (high_s_{ind_name} + low_s_{ind_name}) / 2.0")
            lines.append(f"        high_b_{ind_name} = dataframe['high'].rolling({base_period}).max()")
            lines.append(f"        low_b_{ind_name} = dataframe['low'].rolling({base_period}).min()")
            lines.append(f"        dataframe['{ind_name}_kijun'] = (high_b_{ind_name} + low_b_{ind_name}) / 2.0")
            lines.append(f"        dataframe['{ind_name}_spanA'] = (dataframe['{ind_name}_tenkan'] + dataframe['{ind_name}_kijun']) / 2.0")
            lines.append(f"        high_sb_{ind_name} = dataframe['high'].rolling({span_b_period}).max()")
            lines.append(f"        low_sb_{ind_name} = dataframe['low'].rolling({span_b_period}).min()")
            lines.append(f"        dataframe['{ind_name}_spanB'] = (high_sb_{ind_name} + low_sb_{ind_name}) / 2.0")
            lines.append(f"        dataframe['{ind_name}'] = dataframe['{ind_name}_spanA']")
        else:
            class_name, _ = _INDICATOR_MAP.get(ind_type, (ind_type, ""))
            lines.append(
                f"        {ind_name}_result = ti.{class_name}("
                f"input_values=dataframe['{field}'].tolist(), "
                f"period={period})"
            )
            lines.append(
                f"        dataframe['{ind_name}'] = "
                f"[v if v else None for v in {ind_name}_result]"
            )
    lines.append("        return dataframe")
    lines.append("")

    # --- populate_entry_trend ---
    lines.append("    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:")
    long_expr = entry.get("long")
    short_expr = entry.get("short")

    if long_expr:
        py_expr = _translate_expr(long_expr)
        lines.append(f"        dataframe.loc[")
        lines.append(f"            ({py_expr}),")
        lines.append(f"            ['enter_long', 'enter_tag']")
        lines.append(f"        ] = (1, '{name}_long')")
    else:
        lines.append("        dataframe['enter_long'] = 0")

    if short_expr:
        py_expr = _translate_expr(short_expr)
        lines.append(f"        dataframe.loc[")
        lines.append(f"            ({py_expr}),")
        lines.append(f"            ['enter_short', 'enter_tag']")
        lines.append(f"        ] = (1, '{name}_short')")
    else:
        lines.append("        dataframe['enter_short'] = 0")

    lines.append("        return dataframe")
    lines.append("")

    # --- populate_exit_trend ---
    lines.append("    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:")
    exit_long = exit_conf.get("long")
    exit_short = exit_conf.get("short")

    if exit_long:
        py_expr = _translate_expr(exit_long)
        lines.append(f"        dataframe.loc[")
        lines.append(f"            ({py_expr}),")
        lines.append(f"            ['exit_long', 'exit_tag']")
        lines.append(f"        ] = (1, '{name}_exit_long')")
    else:
        lines.append("        dataframe['exit_long'] = 0")

    if exit_short:
        py_expr = _translate_expr(exit_short)
        lines.append(f"        dataframe.loc[")
        lines.append(f"            ({py_expr}),")
        lines.append(f"            ['exit_short', 'exit_tag']")
        lines.append(f"        ] = (1, '{name}_exit_short')")
    else:
        lines.append("        dataframe['exit_short'] = 0")

    lines.append("        return dataframe")
    lines.append("")

    return "\n".join(lines)


def _translate_expr(expr: str) -> str:
    """Translate a DSL boolean expression to a pandas-compatible expression."""
    result = expr
    for dsl_op, py_op in _EXPR_TRANSLATIONS:
        result = result.replace(dsl_op, py_op)
    # NaN handling: replace None with NaN for pandas
    result = result.replace("None", "float('nan')")
    return result


def transpile_to_file(dsl: dict[str, Any], output_path: str) -> None:
    """Transpile DSL and write to a Python strategy file."""
    source = transpile_to_freqtrade(dsl)
    with open(output_path, "w") as f:
        f.write(source)
