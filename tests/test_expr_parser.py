"""Tests for the AST-based DSL expression parser."""

import pandas as pd
import numpy as np
import pytest

from src.dsl.expr_parser import (
    parse_expression,
    evaluate_expression,
    validate_expression,
    get_expression_references,
)


# --- Reference extraction tests ---

def test_simple_reference():
    refs = get_expression_references("ema_fast > ema_slow")
    assert refs == {"ema_fast", "ema_slow"}


def test_multiple_references():
    refs = get_expression_references("ema_fast > ema_slow AND volume > vol_ma * 1.5 AND rsi < 70")
    assert refs == {"ema_fast", "ema_slow", "vol_ma", "rsi"}


def test_builtin_columns_excluded():
    refs = get_expression_references("close > open AND high > low")
    assert refs == set()  # Built-in columns are not returned


def test_not_or_parsing():
    refs = get_expression_references("NOT (rsi > 70 OR close < ema_slow)")
    assert "rsi" in refs and "ema_slow" in refs


# --- Validation tests ---

def test_valid_expression():
    errors = validate_expression("ema_fast > ema_slow AND rsi < 70", {"ema_fast", "ema_slow", "rsi"})
    assert len(errors) == 0


def test_undefined_reference():
    errors = validate_expression("undefined_ind > 50", {"ema_fast"})
    assert len(errors) > 0
    assert "undefined_ind" in errors[0]


def test_syntax_error():
    errors = validate_expression("ema_fast > AND rsi < 70", {"ema_fast", "rsi"})
    assert len(errors) > 0
    assert "Syntax error" in errors[0]


def test_injection_blocked():
    errors = validate_expression('__import__("os").system("ls")', set())
    assert len(errors) > 0


def test_attribute_access_blocked():
    errors = validate_expression("rsi.__class__", {"rsi"})
    assert len(errors) > 0


# --- Evaluation tests ---

def test_evaluate_simple_comparison():
    df = pd.DataFrame({"close": [10, 20, 30, 40, 50]})
    result = evaluate_expression(df, "close > 25")
    assert result.tolist() == [False, False, True, True, True]


def test_evaluate_with_indicators():
    df = pd.DataFrame({
        "ema_fast": [15, 25, 35],
        "ema_slow": [20, 20, 30],
    })
    result = evaluate_expression(df, "ema_fast > ema_slow")
    assert result.tolist() == [False, True, True]


def test_evaluate_and_logic():
    df = pd.DataFrame({
        "rsi": [25, 50, 75],
        "ema_fast": [1, 2, 3],
        "ema_slow": [0, 2, 2],
    })
    result = evaluate_expression(df, "rsi < 30 AND ema_fast > ema_slow")
    assert result.tolist() == [True, False, False]


def test_evaluate_invalid_returns_false():
    df = pd.DataFrame({"close": [10, 20]})
    result = evaluate_expression(df, "INVALID SYNTAX !!!")
    assert result.tolist() == [False, False]


def test_evaluate_arithmetic():
    df = pd.DataFrame({
        "close": [100, 200, 300],
        "vol_ma": [50, 100, 150],
        "volume": [100, 200, 300],
    })
    result = evaluate_expression(df, "volume > vol_ma * 1.5")
    assert result.tolist() == [True, True, True]
