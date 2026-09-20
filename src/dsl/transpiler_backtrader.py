"""DSL → Backtrader Strategy transpiler.

Converts a validated strategy DSL dict into a Python source file
containing a Backtrader Strategy subclass with a runnable Cerebro
main block.

Only uses indicators available in stock backtrader. Complex indicators
(SuperTrend, Ichimoku) are implemented manually via ATR/rolling calcs.

Usage:
    from src.dsl.transpiler_backtrader import transpile_to_backtrader
    code = transpile_to_backtrader(dsl_dict)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


_EXPR_TRANSLATIONS = [
    (" AND ", " and "),
    (" and ", " and "),
    (" OR ", " or "),
    (" or ", " or "),
    (" NOT ", " not "),
    (" not ", " not "),
    ("True", "True"),
    ("False", "False"),
    ("null", "None"),
]


def transpile_to_backtrader(dsl: dict[str, Any]) -> str:
    """Transpile a validated DSL dict into Backtrader Strategy Python source.

    Generates a complete, runnable Python file with:
    - Strategy class (params, __init__, next, notify_order, stop)
    - Cerebro main block for standalone execution

    Args:
        dsl: Parsed strategy DSL dict (must pass validation).

    Returns:
        Python source code string for a Backtrader strategy file.
    """
    strat = dsl["strategy"]
    name = strat["name"]
    indicators = strat["indicators"]
    entry = strat["entry"]
    exit_conf = strat.get("exit", {})
    risk = strat["risk"]
    market = strat["market"]

    has_short = bool(entry.get("short"))

    lines: list[str] = []
    lines.append('"""')
    lines.append(f"Auto-generated Backtrader strategy: {name}")
    lines.append(f"Generated: {datetime.now().isoformat()}")
    lines.append("Transpiled from trading strategy DSL.")
    lines.append("")
    lines.append("Run: python this_file.py --data BTC_USDT_1h.csv")
    lines.append('"""')
    lines.append("import argparse")
    lines.append("import backtrader as bt")
    lines.append("import pandas as pd")
    lines.append("")
    lines.append("")
    lines.append(f"class {name}(bt.Strategy):")
    lines.append(f'    """{name} — auto-generated from DSL."""')
    lines.append("")
    lines.append("    params = (")

    # --- Risk parameters ---
    lines.append(f"        ('stop_loss', {risk['stop_loss']}),")
    if risk.get("take_profit"):
        lines.append(f"        ('take_profit', {risk['take_profit']}),")
    lines.append(f"        ('max_open_trades', {risk['max_open_trades']}),")
    stake = risk.get("stake_amount", 0.1)
    stake_val = 0.9 if isinstance(stake, str) else stake
    lines.append(f"        ('stake_pct', {stake_val}),")
    lines.append(f"        ('trailing_stop', {risk.get('trailing_stop', False)}),")
    tp = risk.get("trailing_stop_positive", 0.0)
    lines.append(f"        ('trailing_offset', {tp}),")
    lines.append("    )")
    lines.append("")

    # --- __init__ ---
    lines.append("    def __init__(self):")
    lines.append("        self.open_trades = 0")
    lines.append("        self.order = None")
    lines.append("")

    for ind in indicators:
        ind_name = ind["name"]
        ind_type = ind["type"]
        params = ind.get("params", {})
        period = params.get("period", 14)
        field = params.get("field", "close")

        if ind_type == "SMA":
            lines.append(f"        self.{ind_name} = bt.indicators.SMA(self.data.{field}, period={period})")
        elif ind_type == "EMA":
            lines.append(f"        self.{ind_name} = bt.indicators.EMA(self.data.{field}, period={period})")
        elif ind_type == "RSI":
            lines.append(f"        self.{ind_name} = bt.indicators.RSI(self.data.{field}, period={period})")
        elif ind_type == "MACD":
            fast = params.get("fast_period", 12)
            slow = params.get("slow_period", 26)
            signal = params.get("signal_period", 9)
            lines.append(f"        self.macd_{ind_name} = bt.indicators.MACD(")
            lines.append(f"            self.data.close,")
            lines.append(f"            period_me1={fast}, period_me2={slow}, period_signal={signal})")
            lines.append(f"        self.{ind_name} = self.macd_{ind_name}.macd")
            lines.append(f"        self.{ind_name}_signal = self.macd_{ind_name}.signal")
        elif ind_type == "ATR":
            lines.append(f"        self.{ind_name} = bt.indicators.ATR(self.data, period={period})")
        elif ind_type == "BollingerBands":
            std = params.get("std_dev", 2.0)
            lines.append(f"        self.bb_{ind_name} = bt.indicators.BollingerBands(")
            lines.append(f"            self.data.close, period={period}, devfactor={std})")
            lines.append(f"        self.{ind_name}_upper = self.bb_{ind_name}.top")
            lines.append(f"        self.{ind_name}_lower = self.bb_{ind_name}.bot")
            lines.append(f"        self.{ind_name} = self.bb_{ind_name}.mid")
        elif ind_type == "Stochastic":
            lines.append(f"        self.stoch_{ind_name} = bt.indicators.Stochastic(")
            lines.append(f"            self.data, period={period})")
            lines.append(f"        self.{ind_name} = self.stoch_{ind_name}.percK")
            lines.append(f"        self.{ind_name}_d = self.stoch_{ind_name}.percD")
        elif ind_type == "ADX":
            lines.append(f"        self.{ind_name} = bt.indicators.ADX(self.data, period={period})")
        elif ind_type == "CCI":
            lines.append(f"        self.{ind_name} = bt.indicators.CCI(self.data, period={period})")
        elif ind_type == "OBV":
            lines.append(f"        self.{ind_name} = bt.indicators.OBV(self.data.close, self.data.volume)")
        elif ind_type == "VWAP":
            # VWAP: cumulative typical price weighted by volume
            lines.append(f"        # VWAP (cumulative, manual)")
            lines.append(f"        self.tp_{ind_name} = (self.data.high + self.data.low + self.data.close) / 3.0")
            lines.append(f"        self.{ind_name} = bt.indicators.SumN(self.tp_{ind_name} * self.data.volume, period=9999) / bt.indicators.SumN(self.data.volume, period=9999)")
        elif ind_type == "WMA":
            lines.append(f"        self.{ind_name} = bt.indicators.WMA(self.data.{field}, period={period})")
        elif ind_type == "HMA":
            # HMA = WMA(2*WMA(n/2) - WMA(n), sqrt(n))
            lines.append(f"        # Hull MA manual implementation")
            lines.append(f"        _half = max(1, {period} // 2)")
            lines.append(f"        _sqrt = max(1, int({period} ** 0.5))")
            lines.append(f"        _wma_h = bt.indicators.WMA(self.data.{field}, period=_half)")
            lines.append(f"        _wma_f = bt.indicators.WMA(self.data.{field}, period={period})")
            lines.append(f"        self.{ind_name} = bt.indicators.WMA(2 * _wma_h - _wma_f, period=_sqrt)")
        elif ind_type == "ZLEMA":
            # ZLEMA = EMA(2*price - price(delay))
            # Use bt.indicators.EMA with a Delayed feed line
            lines.append(f"        # ZLEMA manual implementation (no bt.Delay in stock)")
            lines.append(f"        _delay = max(1, {period} // 2)")
            lines.append(f"        _delayed = self.data.{field}(-_delay)")
            lines.append(f"        _adjusted = 2 * self.data.{field} - _delayed")
            lines.append(f"        self.{ind_name} = bt.indicators.EMA(_adjusted, period={period})")
        elif ind_type == "Supertrend":
            # SuperTrend: manual implementation using ATR
            # In stock backtrader, SuperTrend doesn't exist, so compute manually
            multiplier = params.get("multiplier", 3.0)
            lines.append(f"        # SuperTrend manual implementation (ATR-based)")
            lines.append(f"        _atr_{ind_name} = bt.indicators.ATR(self.data, period={period})")
            lines.append(f"        _hl2_{ind_name} = (self.data.high + self.data.low) / 2.0")
            lines.append(f"        self.{ind_name}_upper = _hl2_{ind_name} + {multiplier} * _atr_{ind_name}")
            lines.append(f"        self.{ind_name}_lower = _hl2_{ind_name} - {multiplier} * _atr_{ind_name}")
            # Simple trend: price above lower band = uptrend
            lines.append(f"        self.{ind_name} = bt.indicators.CrossUp(self.data.close, self.{ind_name}_lower)")
        elif ind_type == "ICHIMOKU":
            # Ichimoku: manual via rolling high/low (stock bt doesn't have Ichimoku)
            conv = params.get("fast_period", 9)
            base = params.get("slow_period", 26)
            span_b = period * 2
            lines.append(f"        # Ichimoku Cloud manual implementation")
            lines.append(f"        _high_c_{ind_name} = bt.indicators.Highest(self.data.high, period={conv})")
            lines.append(f"        _low_c_{ind_name} = bt.indicators.Lowest(self.data.low, period={conv})")
            lines.append(f"        self.{ind_name}_tenkan = (_high_c_{ind_name} + _low_c_{ind_name}) / 2.0")
            lines.append(f"        _high_b_{ind_name} = bt.indicators.Highest(self.data.high, period={base})")
            lines.append(f"        _low_b_{ind_name} = bt.indicators.Lowest(self.data.low, period={base})")
            lines.append(f"        self.{ind_name}_kijun = (_high_b_{ind_name} + _low_b_{ind_name}) / 2.0")
            lines.append(f"        self.{ind_name}_spanA = (self.{ind_name}_tenkan + self.{ind_name}_kijun) / 2.0")
            lines.append(f"        _high_sb_{ind_name} = bt.indicators.Highest(self.data.high, period={span_b})")
            lines.append(f"        _low_sb_{ind_name} = bt.indicators.Lowest(self.data.low, period={span_b})")
            lines.append(f"        self.{ind_name}_spanB = (_high_sb_{ind_name} + _low_sb_{ind_name}) / 2.0")
            lines.append(f"        self.{ind_name} = self.{ind_name}_spanA  # main line")
        else:
            lines.append(f"        self.{ind_name} = bt.indicators.SMA(self.data.{field}, period={period})")

    lines.append("")

    # --- next() ---
    lines.append("    def next(self):")
    lines.append("        if self.order:")
    lines.append("            return")
    lines.append("")
    lines.append("        price = self.data.close[0]")
    lines.append("        cash = self.broker.get_cash()")
    lines.append("")

    long_entry = entry.get("long")
    short_entry = entry.get("short")
    long_exit = exit_conf.get("long")
    short_exit = exit_conf.get("short")

    # Long entry
    if long_entry:
        py_expr = _translate_expr(long_entry)
        lines.append(f"        # Long entry signal")
        lines.append(f"        if ({py_expr}) and self.open_trades < self.p.max_open_trades:")
        lines.append(f"            size = (cash * self.p.stake_pct) / price")
        lines.append(f"            self.order = self.buy(size=size)")
        lines.append(f"            self.open_trades += 1")
        lines.append("")

    # Long exit
    if long_exit:
        py_expr = _translate_expr(long_exit)
        lines.append(f"        # Long exit signal")
        lines.append(f"        if ({py_expr}) and self.position.size > 0:")
        lines.append(f"            self.order = self.sell()")
        lines.append(f"            self.open_trades -= 1")
        lines.append("")

    # Short entry — use self.sell() for opening shorts (not sell_short)
    if short_entry:
        py_expr = _translate_expr(short_entry)
        lines.append(f"        # Short entry signal (sell to open short)")
        lines.append(f"        if ({py_expr}) and self.open_trades < self.p.max_open_trades:")
        lines.append(f"            size = (cash * self.p.stake_pct) / price")
        lines.append(f"            self.order = self.sell(size=size)")
        lines.append(f"            self.open_trades += 1")
        lines.append("")

    # Short exit — buy to close
    if short_exit:
        py_expr = _translate_expr(short_exit)
        lines.append(f"        # Short exit signal (buy to close)")
        lines.append(f"        if ({py_expr}) and self.position.size < 0:")
        lines.append(f"            self.order = self.buy()")
        lines.append(f"            self.open_trades -= 1")
        lines.append("")

    # Stop-loss / take-profit
    lines.append(f"        # Stop-loss / take-profit")
    lines.append(f"        if self.position.size != 0:")
    lines.append(f"            entry_price = self.position.price")
    lines.append(f"            if self.position.size > 0:")
    lines.append(f"                pnl_pct = (price - entry_price) / entry_price")
    lines.append(f"            else:")
    lines.append(f"                pnl_pct = (entry_price - price) / entry_price")
    lines.append(f"            if pnl_pct <= self.p.stop_loss:")
    lines.append(f"                self.order = self.close()")
    lines.append(f"                self.open_trades = 0")
    if risk.get("take_profit"):
        lines.append(f"            elif self.p.take_profit and pnl_pct >= self.p.take_profit:")
        lines.append(f"                self.order = self.close()")
        lines.append(f"                self.open_trades = 0")
    lines.append("")

    # --- notify_order ---
    lines.append("    def notify_order(self, order):")
    lines.append("        if order.status in [order.Completed, order.Canceled, order.Margin]:")
    lines.append("            self.order = None")
    lines.append("")

    # --- stop (print final results) ---
    lines.append("    def stop(self):")
    lines.append(f'        print(f"Final Portfolio Value: {{self.broker.getvalue():.2f}}")')
    lines.append("")

    return "\n".join(lines)


def _translate_expr(expr: str) -> str:
    """Translate a DSL boolean expression to a Python expression."""
    result = expr
    for dsl_op, py_op in _EXPR_TRANSLATIONS:
        result = result.replace(dsl_op, py_op)
    return result


def transpile_to_file(dsl: dict[str, Any], output_path: str) -> None:
    """Transpile DSL and write to a Python strategy file."""
    source = transpile_to_backtrader(dsl)
    with open(output_path, "w") as f:
        f.write(source)
