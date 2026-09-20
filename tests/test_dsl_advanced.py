"""Tests for advanced DSL features: short positions, new indicators, time_in_trade."""

import json

import pytest

from src.dsl.validator import validate_dsl
from src.dsl.transpiler import transpile_to_freqtrade
from src.dsl.expr_parser import (
    validate_expression,
    evaluate_expression,
    get_expression_references,
)


# --- Short position tests ---

def test_short_entry_passes_validation():
    """DSL with short entry should pass validation."""
    dsl = {
        "strategy": {
            "name": "ShortTest",
            "market": {"exchange": "binance", "pair": "BTC/USDT", "timeframe": "1h"},
            "indicators": [
                {"name": "ema_fast", "type": "EMA", "params": {"period": 20, "field": "close"}},
                {"name": "ema_slow", "type": "EMA", "params": {"period": 50, "field": "close"}},
                {"name": "rsi", "type": "RSI", "params": {"period": 14}},
            ],
            "entry": {
                "long": "ema_fast > ema_slow",
                "short": "ema_fast < ema_slow AND rsi > 70",
            },
            "exit": {
                "long": "ema_fast < ema_slow",
                "short": "ema_fast > ema_slow OR rsi < 30",
            },
            "risk": {"stop_loss": -0.03, "max_open_trades": 3, "stake_amount": 0.1},
        }
    }
    is_valid, errors = validate_dsl(dsl)
    assert is_valid, f"Short strategy should be valid: {errors}"


def test_short_transpiler_generates_can_short():
    """Transpiler should set can_short=True when short entry is defined."""
    dsl = {
        "strategy": {
            "name": "ShortTranspile",
            "market": {"exchange": "binance", "pair": "BTC/USDT", "timeframe": "1h"},
            "indicators": [
                {"name": "ema_fast", "type": "EMA", "params": {"period": 20, "field": "close"}},
                {"name": "ema_slow", "type": "EMA", "params": {"period": 50, "field": "close"}},
            ],
            "entry": {"long": None, "short": "ema_fast < ema_slow"},
            "exit": {"long": None, "short": "ema_fast > ema_slow"},
            "risk": {"stop_loss": -0.03, "max_open_trades": 2, "stake_amount": 0.1},
        }
    }
    code = transpile_to_freqtrade(dsl)
    assert "can_short = True" in code
    assert "enter_short" in code
    assert "exit_short" in code


# --- time_in_trade tests ---

def test_time_in_trade_passes_validation():
    """DSL with time_in_trade should pass validation."""
    dsl = {
        "strategy": {
            "name": "TimeLimitTest",
            "market": {"exchange": "binance", "pair": "BTC/USDT", "timeframe": "1h"},
            "indicators": [
                {"name": "ema_fast", "type": "EMA", "params": {"period": 20, "field": "close"}},
                {"name": "ema_slow", "type": "EMA", "params": {"period": 50, "field": "close"}},
            ],
            "entry": {"long": "ema_fast > ema_slow", "short": None},
            "exit": {"long": "ema_fast < ema_slow", "short": None},
            "risk": {
                "stop_loss": -0.03,
                "max_open_trades": 3,
                "stake_amount": 0.1,
                "time_in_trade": {"max_hours": 24},
            },
        }
    }
    is_valid, errors = validate_dsl(dsl)
    assert is_valid, f"time_in_trade should be valid: {errors}"


# --- New indicator validation tests ---

NEW_INDICATORS = [
    ("VWAP", {"period": 14}, ["vwap"]),
    ("HMA", {"period": 20, "field": "close"}, ["hma"]),
    ("ZLEMA", {"period": 20, "field": "close"}, ["zlema"]),
    ("Supertrend", {"period": 14, "multiplier": 3.0}, ["st"]),
    ("ICHIMOKU", {"period": 52, "fast_period": 9, "slow_period": 26}, ["ichi"]),
]


@pytest.mark.parametrize("ind_type,params,names", NEW_INDICATORS)
def test_new_indicator_passes_validation(ind_type, params, names):
    """Each new indicator type should pass DSL validation."""
    indicators = [
        {"name": n, "type": ind_type, "params": params}
        for n in [names[0]]
    ]
    indicators.append(
        {"name": "ema_slow", "type": "EMA", "params": {"period": 50, "field": "close"}}
    )
    dsl = {
        "strategy": {
            "name": f"Test{ind_type}",
            "market": {"exchange": "binance", "pair": "BTC/USDT", "timeframe": "1h"},
            "indicators": indicators,
            "entry": {"long": f"{names[0]} > ema_slow", "short": None},
            "exit": {"long": f"{names[0]} < ema_slow", "short": None},
            "risk": {"stop_loss": -0.03, "max_open_trades": 3, "stake_amount": 0.1},
        }
    }
    is_valid, errors = validate_dsl(dsl)
    assert is_valid, f"{ind_type} should be valid: {errors}"


@pytest.mark.parametrize("ind_type,params", [
    ("VWAP", {"period": 14}),
    ("HMA", {"period": 20, "field": "close"}),
    ("ZLEMA", {"period": 20, "field": "close"}),
    ("Supertrend", {"period": 14, "multiplier": 3.0}),
    ("ICHIMOKU", {"period": 52, "fast_period": 9, "slow_period": 26}),
])
def test_new_indicator_transpiles_valid_python(ind_type, params):
    """Each new indicator should transpile to valid Python."""
    import ast as _ast
    dsl = {
        "strategy": {
            "name": f"Transpile{ind_type}",
            "market": {"exchange": "binance", "pair": "BTC/USDT", "timeframe": "1h"},
            "indicators": [
                {"name": "ind", "type": ind_type, "params": params},
            ],
            "entry": {"long": "close > ind", "short": None},
            "exit": {"long": "close < ind", "short": None},
            "risk": {"stop_loss": -0.03, "max_open_trades": 3, "stake_amount": 0.1},
        }
    }
    code = transpile_to_freqtrade(dsl)
    _ast.parse(code)  # Raises SyntaxError if invalid
    assert "needs manual implementation" not in code


# --- Expression parser edge cases ---

def test_nested_parentheses():
    """Complex nested expression should parse correctly."""
    expr = "(ema_fast > ema_slow AND (rsi < 30 OR rsi > 70)) AND volume > 1000"
    errors = validate_expression(expr, {"ema_fast", "ema_slow", "rsi"})
    assert len(errors) == 0


def test_arithmetic_in_comparison():
    """Arithmetic operations inside comparisons should work."""
    expr = "volume > vol_ma * 1.5"
    errors = validate_expression(expr, {"vol_ma"})
    assert len(errors) == 0


def test_chained_comparisons():
    """Multiple comparisons should work."""
    expr = "rsi > 30 AND rsi < 70"
    errors = validate_expression(expr, {"rsi"})
    assert len(errors) == 0


def test_not_operator():
    """NOT operator should parse correctly."""
    expr = "NOT (rsi > 70 OR close < ema_slow)"
    errors = validate_expression(expr, {"rsi", "ema_slow"})
    assert len(errors) == 0


def test_no_attribute_access():
    """Attribute access like .system should be blocked."""
    errors = validate_expression("close.__class__", set())
    assert len(errors) > 0


def test_no_subscript():
    """Subscript access should be blocked."""
    errors = validate_expression("close[0]", set())
    assert len(errors) > 0


def test_no_call():
    """Function calls should be blocked."""
    errors = validate_expression("abs(close)", set())
    assert len(errors) > 0
