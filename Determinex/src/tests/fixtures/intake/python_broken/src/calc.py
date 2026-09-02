"""Intentionally wrong arithmetic — fixture for CODEBASE_EXPLORER_SMOKE_LOCK_001."""


def add(a: int, b: int) -> int:
    # BUG: subtracts instead of adds — caught by tests/test_calc.py
    return a - b


def multiply(a: int, b: int) -> int:
    return a * b
