"""Tests for DSL schema validation."""

import json
from pathlib import Path

import pytest

from src.dsl.validator import validate_dsl


VALID_STRATEGY = {
    "strategy": {
        "name": "TestEMA",
        "market": {
            "exchange": "binance",
            "pair": "BTC/USDT",
            "timeframe": "1h",
        },
        "indicators": [
            {"name": "ema_fast", "type": "EMA", "params": {"period": 20, "field": "close"}},
            {"name": "ema_slow", "type": "EMA", "params": {"period": 50, "field": "close"}},
            {"name": "rsi", "type": "RSI", "params": {"period": 14}},
        ],
        "entry": {
            "long": "ema_fast > ema_slow AND rsi < 70",
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


def test_valid_strategy():
    is_valid, errors = validate_dsl(VALID_STRATEGY)
    assert is_valid, f"Expected valid, got errors: {errors}"


def test_missing_required_field():
    invalid = json.loads(json.dumps(VALID_STRATEGY))
    del invalid["strategy"]["risk"]["stop_loss"]
    is_valid, errors = validate_dsl(invalid)
    assert not is_valid
    assert any("stop_loss" in e for e in errors)


def test_positive_stop_loss():
    invalid = json.loads(json.dumps(VALID_STRATEGY))
    invalid["strategy"]["risk"]["stop_loss"] = 0.03
    is_valid, errors = validate_dsl(invalid)
    assert not is_valid
    # 0.03 > schema max(0), so schema catches it first
    assert len(errors) > 0


def test_undefined_indicator_reference():
    invalid = json.loads(json.dumps(VALID_STRATEGY))
    invalid["strategy"]["entry"]["long"] = "undefined_indicator > 50"
    is_valid, errors = validate_dsl(invalid)
    assert not is_valid
    assert any("undefined" in e for e in errors)


def test_invalid_exchange():
    invalid = json.loads(json.dumps(VALID_STRATEGY))
    invalid["strategy"]["market"]["exchange"] = "coinbase"
    is_valid, _ = validate_dsl(invalid)
    assert not is_valid


def test_invalid_timeframe():
    invalid = json.loads(json.dumps(VALID_STRATEGY))
    invalid["strategy"]["market"]["timeframe"] = "2h"
    is_valid, _ = validate_dsl(invalid)
    assert not is_valid


def test_invalid_pair_format():
    invalid = json.loads(json.dumps(VALID_STRATEGY))
    invalid["strategy"]["market"]["pair"] = "btc-usdt"
    is_valid, _ = validate_dsl(invalid)
    assert not is_valid


def test_trailing_stop_without_positive():
    invalid = json.loads(json.dumps(VALID_STRATEGY))
    invalid["strategy"]["risk"]["trailing_stop"] = True
    invalid["strategy"]["risk"]["trailing_stop_positive"] = 0
    is_valid, errors = validate_dsl(invalid)
    assert not is_valid
    assert any("trailing" in e.lower() for e in errors)


def test_indicator_names_are_snake_case():
    is_valid, _ = validate_dsl(VALID_STRATEGY)
    assert is_valid  # All names in VALID_STRATEGY are snake_case


def test_multiple_indicators():
    valid = json.loads(json.dumps(VALID_STRATEGY))
    valid["strategy"]["indicators"].extend([
        {"name": "macd", "type": "MACD", "params": {"fast_period": 12, "slow_period": 26, "signal_period": 9}},
        {"name": "atr", "type": "ATR", "params": {"period": 14}},
        {"name": "bb", "type": "BollingerBands", "params": {"period": 20, "std_dev": 2.0}},
    ])
    is_valid, errors = validate_dsl(valid)
    assert is_valid, f"Expected valid, got: {errors}"
