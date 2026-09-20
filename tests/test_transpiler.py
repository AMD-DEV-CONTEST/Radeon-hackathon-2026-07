"""Tests for DSL → Freqtrade strategy transpiler."""

import json

import pytest

from src.dsl.transpiler import transpile_to_freqtrade
from src.dsl.validator import validate_dsl


VALID_DSL = {
    "strategy": {
        "name": "TestStrategy",
        "market": {"exchange": "binance", "pair": "BTC/USDT", "timeframe": "4h"},
        "indicators": [
            {"name": "ema_fast", "type": "EMA", "params": {"period": 20, "field": "close"}},
            {"name": "ema_slow", "type": "EMA", "params": {"period": 50, "field": "close"}},
            {"name": "rsi", "type": "RSI", "params": {"period": 14}},
            {"name": "vol_ma", "type": "SMA", "params": {"period": 20, "field": "volume"}},
        ],
        "entry": {
            "long": "ema_fast > ema_slow AND volume > vol_ma * 1.5 AND rsi < 70",
            "short": None,
        },
        "exit": {
            "long": "ema_fast < ema_slow",
            "short": None,
        },
        "risk": {
            "stop_loss": -0.03,
            "max_open_trades": 3,
            "stake_amount": 0.1,
            "trailing_stop": True,
            "trailing_stop_positive": 0.02,
        },
    }
}


def test_generates_class_definition():
    code = transpile_to_freqtrade(VALID_DSL)
    assert "class TestStrategy(IStrategy):" in code


def test_generates_populate_indicators():
    code = transpile_to_freqtrade(VALID_DSL)
    assert "def populate_indicators" in code
    assert "ema_fast" in code
    assert "ema_slow" in code
    assert "rsi" in code
    assert "vol_ma" in code


def test_generates_entry_trend():
    code = transpile_to_freqtrade(VALID_DSL)
    assert "def populate_entry_trend" in code
    assert "enter_long" in code


def test_generates_exit_trend():
    code = transpile_to_freqtrade(VALID_DSL)
    assert "def populate_exit_trend" in code
    assert "exit_long" in code


def test_includes_risk_parameters():
    code = transpile_to_freqtrade(VALID_DSL)
    assert "stoploss = -0.03" in code
    assert "max_open_trades = 3" in code
    assert "trailing_stop = True" in code
    assert "trailing_stop_positive = 0.02" in code


def test_includes_timeframe():
    code = transpile_to_freqtrade(VALID_DSL)
    assert "timeframe = '4h'" in code


def test_translates_boolean_expressions():
    code = transpile_to_freqtrade(VALID_DSL)
    # AND should be translated to &
    assert "&" in code
    # The original AND should not appear in Python expressions
    assert "ema_fast > ema_slow &" in code or "ema_fast > ema_slow" in code


def test_handles_short_strategy():
    dsl = json.loads(json.dumps(VALID_DSL))
    dsl["strategy"]["entry"]["short"] = "ema_fast < ema_slow AND rsi > 70"
    dsl["strategy"]["exit"]["short"] = "ema_fast > ema_slow"
    code = transpile_to_freqtrade(dsl)
    assert "enter_short" in code
    assert "exit_short" in code
    assert "can_short = True" in code


def test_handles_no_trailing_stop():
    dsl = json.loads(json.dumps(VALID_DSL))
    dsl["strategy"]["risk"]["trailing_stop"] = False
    code = transpile_to_freqtrade(dsl)
    assert "trailing_stop = False" in code


def test_validates_before_transpile():
    # The transpiler expects pre-validated DSL
    is_valid, _ = validate_dsl(VALID_DSL)
    assert is_valid
    code = transpile_to_freqtrade(VALID_DSL)
    assert len(code) > 100
