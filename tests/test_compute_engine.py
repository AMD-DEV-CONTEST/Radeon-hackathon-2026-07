"""Tests for the local compute engine (Q9-Q23 compute-class questions)."""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tools.compute.engine import (
    risk_metrics, factor_ic, mean_variance_optimize, risk_parity,
    black_scholes, implied_volatility, option_greeks, compute,
)
from src.tools.compute import resolve_compute


def _noisy_prices(n=60, seed=42):
    import random
    random.seed(seed)
    p = 100.0
    out = []
    for _ in range(n):
        p *= 1 + random.uniform(-0.03, 0.03)
        out.append(p)
    return out


def test_risk_metrics_historical():
    r = risk_metrics(_noisy_prices(), method="historical")
    assert r.var_95 > 0
    assert r.max_drawdown <= 0
    assert r.sharpe != 0


def test_risk_metrics_parametric():
    r = risk_metrics(_noisy_prices(), method="parametric")
    # Parametric VaR can be negative for drift-heavy series (a "gain" at 95%)
    # CVaR in tail terms must be positive; method note must be set.
    assert r.cvar_95 > 0
    assert "parametric" in r.notes[0]
    assert r.method == "parametric"


def test_factor_ic():
    f = [i for i in range(30)]
    ret = [0.01 * (i % 3 - 1) for i in range(30)]
    r = factor_ic(f, ret)
    assert -1 <= r.ic_mean <= 1
    assert r.icir != 0
    assert "IC" in r.note


def test_factor_ic_horizons():
    f = [i for i in range(40)]
    ret = [0.01 * (i % 2) for i in range(40)]
    r = factor_ic(f, ret, periods=[1, 5, 10])
    assert len(r.ic_series) == 3


def test_mean_variance():
    mu = [0.08, 0.12, 0.06]
    cov = [[0.04, 0.01, 0.005],
           [0.01, 0.09, 0.01],
           [0.005, 0.01, 0.03]]
    p = mean_variance_optimize(mu, cov)
    assert abs(sum(p.weights) - 1.0) < 1e-6
    assert all(w >= -1e-6 for w in p.weights)
    assert p.expected_vol > 0


def test_risk_parity():
    cov = [[0.04, 0.01], [0.01, 0.09]]
    p = risk_parity(cov)
    assert abs(sum(p.weights) - 1.0) < 1e-6


def test_black_scholes():
    price = black_scholes(100, 100, 1.0, 0.03, 0.2, "call")
    assert price > 0
    put = black_scholes(100, 100, 1.0, 0.03, 0.2, "put")
    assert put > 0


def test_implied_vol():
    from math import isclose
    p = black_scholes(100, 100, 1.0, 0.03, 0.25, "call")
    iv = implied_volatility(p, 100, 100, 1.0, 0.03, "call")
    assert isclose(iv, 0.25, abs_tol=0.02)


def test_greeks():
    g = option_greeks(100, 100, 1.0, 0.03, 0.2, "call")
    assert 0 < g["delta"] < 1
    assert g["gamma"] > 0
    assert g["vega"] > 0


def test_compute_dispatch():
    r = compute("risk_metrics", prices=[100 + i for i in range(30)])
    assert "var_95" in r
    r2 = compute("black_scholes", spot=100, strike=100, t=1, r=0.03, sigma=0.2)
    assert r2["price"] > 0
    bad = compute("nonsense")
    assert "error" in bad


def test_resolve_compute():
    r = resolve_compute("算一下最大回撤和VaR", kind="risk_metrics",
                        params={"prices": [100 + i for i in range(30)]})
    assert r["success"]
    assert r["kind"] == "risk_metrics"
    assert "sharpe" in r["result"]


def test_resolve_compute_autodetect():
    r = resolve_compute("计算沪深300的夏普比率和最大回撤",
                        params={"prices": [100 + i for i in range(30)]})
    assert r["success"]
    assert "sharpe" in r["result"]
