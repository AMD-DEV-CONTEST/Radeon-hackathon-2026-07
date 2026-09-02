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


def load_financial_intelligence_cases() -> dict[str, dict]:
    path = Path(__file__).resolve().parents[1] / "fixtures" / "financial-intelligence-reference-cases.json"
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


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

    advanced = load_financial_intelligence_cases()

    nopat = advanced["nopat"]
    operating_income = Decimal(nopat["inputs"]["operating_income"])
    tax_rate = Decimal(nopat["inputs"]["tax_rate"])
    check_decimal(operating_income * (Decimal(1) - tax_rate), nopat["expected"]["nopat"])

    capital = advanced["invested_capital"]
    capital_inputs = {key: Decimal(value) for key, value in capital["inputs"].items()}
    operating_approach = capital_inputs["operating_assets"] - capital_inputs["non_interest_bearing_operating_liabilities"]
    financing_approach = capital_inputs["debt"] + capital_inputs["equity"] - capital_inputs["cash_and_equivalents"] - capital_inputs["non_operating_assets"]
    check_decimal(operating_approach, capital["expected"]["operating_approach"])
    check_decimal(financing_approach, capital["expected"]["financing_approach"])
    check_decimal(operating_approach - financing_approach, capital["expected"]["difference"])

    allocation = advanced["capital_allocation"]
    allocation_inputs = {key: Decimal(value) for key, value in allocation["inputs"].items()}
    total_sources = sum(allocation_inputs[key] for key in ("operating_cash_flow", "debt_issuance", "equity_issuance", "asset_sales"))
    total_uses = sum(allocation_inputs[key] for key in ("capital_expenditure", "acquisitions", "debt_repayment", "dividends", "repurchases"))
    implied_change = total_sources - total_uses
    check_decimal(total_sources, allocation["expected"]["total_sources"])
    check_decimal(total_uses, allocation["expected"]["total_uses"])
    check_decimal(implied_change, allocation["expected"]["implied_change_in_cash"])
    check_decimal(implied_change - allocation_inputs["reported_change_in_cash"], allocation["expected"]["reconciliation_gap"])

    capm = advanced["capm"]
    capm_inputs = {key: Decimal(value) for key, value in capm["inputs"].items()}
    check_decimal(capm_inputs["risk_free_rate"] + capm_inputs["beta"] * capm_inputs["equity_risk_premium"], capm["expected"]["cost_of_equity"])

    advanced_dcf = advanced["multistage_dcf"]
    advanced_flows = [Decimal(value) for value in advanced_dcf["inputs"]["forecast"]]
    advanced_rate = Decimal(advanced_dcf["inputs"]["discount_rate"])
    advanced_growth = Decimal(advanced_dcf["inputs"]["terminal_growth"])
    advanced_explicit = sum(value / ((Decimal(1) + advanced_rate) ** year) for year, value in enumerate(advanced_flows, 1))
    advanced_terminal = advanced_flows[-1] * (Decimal(1) + advanced_growth) / (advanced_rate - advanced_growth)
    advanced_terminal_pv = advanced_terminal / ((Decimal(1) + advanced_rate) ** len(advanced_flows))
    check_decimal(advanced_explicit, advanced_dcf["expected"]["explicit_present_value"])
    check_decimal(advanced_terminal_pv, advanced_dcf["expected"]["terminal_present_value"])
    check_decimal(advanced_explicit + advanced_terminal_pv, advanced_dcf["expected"]["enterprise_value"])

    dupont = advanced["dupont"]
    dupont_inputs = dupont["inputs"]
    net_margin = dupont_inputs["net_income"] / dupont_inputs["revenue"]
    asset_turnover = dupont_inputs["revenue"] / dupont_inputs["average_assets"]
    leverage = dupont_inputs["average_assets"] / dupont_inputs["average_equity"]
    check_close(net_margin, dupont["expected"]["net_margin"], 1e-12)
    check_close(asset_turnover, dupont["expected"]["asset_turnover"], 1e-12)
    check_close(leverage, dupont["expected"]["financial_leverage"], 1e-12)
    check_close(net_margin * asset_turnover * leverage, dupont["expected"]["return_on_equity"], 1e-12)

    peer = advanced["peer_statistics"]
    peer_values = sorted(peer["inputs"]["peers"])
    peer_median = statistics.median(peer_values)
    peer_percentile = sum(value <= peer["inputs"]["subject"] for value in peer_values) / len(peer_values)
    peer_mad = statistics.median(abs(value - peer_median) for value in peer_values)
    check_close(peer_median, peer["expected"]["median"], 1e-12)
    check_close(peer_percentile, peer["expected"]["percentile"], 1e-12)
    check_close(peer_mad, peer["expected"]["median_absolute_deviation"], 1e-12)

    print("reference_finance: 12 selected complex methods verified across independent implementations")


if __name__ == "__main__":
    main()
