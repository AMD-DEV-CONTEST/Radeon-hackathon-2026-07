#!/usr/bin/env python3
"""Independent standard-library references for selected Tier 0 golden cases."""

from __future__ import annotations

import json
import math
import statistics
from decimal import Decimal, getcontext
from pathlib import Path

getcontext().prec = 34


def load_cases() -> dict[str, dict]:
    path = Path(__file__).resolve().parents[1] / "fixtures" / "tier0-golden-cases.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {case["operation_id"]: case for case in payload["cases"]}


def check_decimal(actual: Decimal, expected: str) -> None:
    if actual != Decimal(expected):
        raise AssertionError(f"{actual} != {expected}")


def check_close(actual: float, expected: float, tolerance: float) -> None:
    if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance):
        raise AssertionError(f"{actual} != {expected} within {tolerance}")


def main() -> None:
    cases = load_cases()

    dcf = cases["valuation.fcff_dcf"]
    flows = [Decimal(value) for value in dcf["inputs"]["fcff_forecast"]]
    rate = Decimal(dcf["inputs"]["discount_rate"])
    growth = Decimal(dcf["inputs"]["terminal_growth"])
    explicit = sum(value / ((Decimal(1) + rate) ** year) for year, value in enumerate(flows, 1))
    terminal = flows[-1] * (Decimal(1) + growth) / (rate - growth)
    terminal_pv = terminal / ((Decimal(1) + rate) ** len(flows))
    check_decimal(explicit, dcf["expected"]["explicit_present_value"])
    check_decimal(terminal_pv, dcf["expected"]["terminal_present_value"])
    check_decimal(explicit + terminal_pv, dcf["expected"]["enterprise_value"])

    real = cases["economics.real_rate"]
    nominal = Decimal(real["inputs"]["nominal_rate"])
    inflation = Decimal(real["inputs"]["inflation_measure"])
    check_decimal((Decimal(1) + nominal) / (Decimal(1) + inflation) - Decimal(1), real["expected"]["real_rate"])

    volatility = cases["market.volatility"]
    annualized = statistics.stdev(volatility["inputs"]["returns"]) * math.sqrt(volatility["inputs"]["periods_per_year"])
    check_close(annualized, volatility["expected"]["volatility"], volatility["expected"]["tolerance"])

    beta = cases["market.beta"]
    security = beta["inputs"]["security_returns"]
    benchmark = beta["inputs"]["benchmark_returns"]
    covariance = statistics.covariance(security, benchmark)
    result = covariance / statistics.variance(benchmark)
    check_close(result, beta["expected"]["beta"], beta["expected"]["tolerance"])

    drawdown = cases["market.drawdown"]
    peak = -math.inf
    series = []
    for value in drawdown["inputs"]["wealth_index"]:
        peak = max(peak, value)
        series.append(value / peak - 1.0)
    for actual, expected in zip(series, drawdown["expected"]["drawdown_series"], strict=True):
        check_close(actual, expected, drawdown["expected"]["tolerance"])
    check_close(min(series), drawdown["expected"]["maximum_drawdown"], drawdown["expected"]["tolerance"])

    print("reference_finance: 5 selected complex methods verified")


if __name__ == "__main__":
    main()
