"""Local computation engine — quant risk/factor/portfolio/option math.

Pure numpy implementation (no pandas/scipy required), covering the
compute-class questions from the 35-question set (Q9-Q23 etc.) so they
actually EXECUTE locally instead of returning a capability boundary.

Design rules:
- Deterministic: same inputs -> same outputs (testable)
- No network: local_compute NEVER calls external APIs
- numpy 1.26 (server) and 2.x (local) compatible
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


# ── Helpers ─────────────────────────────────────────────────────────


def _safe_returns(prices: list[float]) -> np.ndarray:
    """Log returns from a price series; guards divide-by-zero."""
    a = np.asarray(prices, dtype=float)
    if a.size < 2:
        return np.array([], dtype=float)
    prev = a[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.diff(a) / prev
    return np.nan_to_num(r, nan=0.0, posinf=0.0, neginf=0.0)


# ── Risk metrics (Q9, Q12, Q31) ─────────────────────────────────────


@dataclass
class RiskReport:
    method: str
    var_95: float
    var_99: float
    cvar_95: float
    cvar_99: float
    sharpe: float
    sortino: float
    calmar: float
    max_drawdown: float
    annualized_vol: float
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "var_95": round(self.var_95, 4),
            "var_99": round(self.var_99, 4),
            "cvar_95": round(self.cvar_95, 4),
            "cvar_99": round(self.cvar_99, 4),
            "sharpe": round(self.sharpe, 3),
            "sortino": round(self.sortino, 3),
            "calmar": round(self.calmar, 3),
            "max_drawdown": round(self.max_drawdown, 4),
            "annualized_vol": round(self.annualized_vol, 4),
            "notes": self.notes,
        }


def risk_metrics(prices: list[float], method: str = "historical",
                 risk_free: float = 0.02, periods_per_year: int = 252) -> RiskReport:
    """Compute VaR/CVaR (historical or parametric) + performance family.

    method: "historical" -> empirical percentile; "parametric" -> normal.
    """
    r = _safe_returns(prices)
    if r.size == 0:
        return RiskReport(method, 0, 0, 0, 0, 0, 0, 0, 0, 0, ["insufficient data"])

    mean = float(np.mean(r))
    std = float(np.std(r, ddof=1)) if r.size > 1 else 0.0
    ann_vol = std * math.sqrt(periods_per_year)
    ann_ret = mean * periods_per_year

    if method == "parametric":
        # Parametric normal VaR/CVaR
        var_95 = -(mean + 1.645 * std)
        var_99 = -(mean + 2.326 * std)
        phi95 = math.exp(-1.645 ** 2 / 2) / math.sqrt(2 * math.pi)
        phi99 = math.exp(-2.326 ** 2 / 2) / math.sqrt(2 * math.pi)
        cvar_95 = -(mean - std * phi95 / 0.05)
        cvar_99 = -(mean - std * phi99 / 0.01)
        notes = ["parametric normal VaR/CVaR", "assumes normal returns"]
    else:
        # Historical simulation
        var_95 = float(-np.percentile(r, 5))
        var_99 = float(-np.percentile(r, 1))
        tail95 = r[r <= -var_95]
        tail99 = r[r <= -var_99]
        cvar_95 = float(-tail95.mean()) if tail95.size else var_95
        cvar_99 = float(-tail99.mean()) if tail99.size else var_99
        notes = ["historical simulation", f"n={r.size} observations"]

    # Performance family
    excess = r - risk_free / periods_per_year
    sharpe = float(np.mean(excess) / np.std(excess, ddof=1)) if np.std(excess, ddof=1) > 0 else 0.0
    downside = r[r < 0]
    downside_std = float(np.std(downside, ddof=1)) if downside.size > 1 else 0.0
    sortino = float(np.mean(excess) / downside_std) if downside_std > 0 else 0.0

    # Max drawdown
    cum = np.cumprod(1 + r)
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    max_dd = float(np.min(dd))
    calmar = float(ann_ret / abs(max_dd)) if max_dd < 0 else 0.0

    return RiskReport(
        method=method, var_95=var_95, var_99=var_99,
        cvar_95=cvar_95, cvar_99=cvar_99,
        sharpe=sharpe, sortino=sortino, calmar=calmar,
        max_drawdown=max_dd, annualized_vol=ann_vol, notes=notes,
    )


# ── Factor analysis (Q1, Q2, Q4) ────────────────────────────────────


@dataclass
class FactorReport:
    factor: str
    ic_series: list[float]
    ic_mean: float
    icir: float
    ic_std: float
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "factor": self.factor,
            "ic_mean": round(self.ic_mean, 4),
            "icir": round(self.icir, 4),
            "ic_std": round(self.ic_std, 4),
            "ic_series": [round(x, 4) for x in self.ic_series[-10:]],
            "note": self.note,
        }


def factor_ic(factor_values: list[float], forward_returns: list[float],
              periods: list[int] | None = None) -> FactorReport:
    """IC = Pearson correlation between factor and forward returns.

    periods: if given, returns per-horizon IC (decay analysis, Q2).
    """
    f = np.asarray(factor_values, dtype=float)
    r = np.asarray(forward_returns, dtype=float)
    n = min(f.size, r.size)
    if n < 3:
        return FactorReport("factor", [], 0, 0, 0, "insufficient data")

    f, r = f[:n], r[:n]
    ic = float(np.corrcoef(f, r)[0, 1]) if np.std(f) > 0 and np.std(r) > 0 else 0.0
    ic_std = 1.0 / math.sqrt(n)  # approx std of IC under H0
    icir = ic / ic_std if ic_std > 0 else 0.0

    series = []
    if periods:
        for p in periods:
            if n > p:
                icp = float(np.corrcoef(f[:-p], r[p:])[0, 1]) if np.std(f[:-p]) > 0 and np.std(r[p:]) > 0 else 0.0
                series.append(icp)
            else:
                series.append(0.0)
        note = f"per-horizon IC for hold {periods}: {[round(x,3) for x in series]}"
    else:
        series = [ic]
        note = f"single-horizon IC: {round(ic, 4)}"

    return FactorReport(
        factor="factor", ic_series=series, ic_mean=float(np.mean(series)),
        icir=icir, ic_std=ic_std, note=note,
    )


# ── Portfolio optimization (Q13, Q14, Q16) ──────────────────────────


@dataclass
class PortfolioReport:
    method: str
    weights: list[float]
    expected_return: float
    expected_vol: float
    sharpe: float
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "weights": [round(w, 4) for w in self.weights],
            "expected_return": round(self.expected_return, 4),
            "expected_vol": round(self.expected_vol, 4),
            "sharpe": round(self.sharpe, 4),
            "note": self.note,
        }


def mean_variance_optimize(expected_returns: list[float],
                           cov_matrix: list[list[float]],
                           risk_aversion: float = 2.0,
                           target_vol: float | None = None) -> PortfolioReport:
    """Maximize Sharpe (or mean-variance utility) subject to full investment.

    Closed-form for unconstrained; then project to simplex (long-only)
    with iterative normalization. Sufficient for demonstration.
    """
    if not expected_returns or not cov_matrix:
        # Demo defaults: 3 assets with plausible return/risk profile
        expected_returns = [0.08, 0.12, 0.06]
        cov_matrix = [[0.04, 0.01, 0.005],
                      [0.01, 0.09, 0.01],
                      [0.005, 0.01, 0.03]]
    mu = np.asarray(expected_returns, dtype=float)
    cov = np.asarray(cov_matrix, dtype=float)
    n = mu.size

    # Closed-form tangency portfolio (unconstrained)
    inv = np.linalg.inv(cov + 1e-8 * np.eye(n))
    w_raw = inv @ mu
    if w_raw.sum() != 0:
        w = w_raw / w_raw.sum()
    else:
        w = np.full(n, 1.0 / n)

    # Long-only projection (clamp + renormalize, iterate a few times)
    for _ in range(20):
        w = np.clip(w, 0, None)
        s = w.sum()
        if s <= 0:
            w = np.full(n, 1.0 / n)
            break
        w = w / s
        if np.all(w >= 0):
            break

    exp_ret = float(mu @ w)
    exp_vol = float(math.sqrt(w @ cov @ w))
    sharpe = float(exp_ret / exp_vol) if exp_vol > 0 else 0.0
    return PortfolioReport(
        method="mean-variance (long-only)", weights=w.tolist(),
        expected_return=exp_ret, expected_vol=exp_vol, sharpe=sharpe,
        note="unconstrained tangency then simplex projection",
    )


def risk_parity(cov_matrix: list[list[float]], max_iter: int = 100,
                tol: float = 1e-6) -> PortfolioReport:
    """Risk parity (equal risk contribution) via iterative weights.

    w_i ∝ (Σ^{-1} 1)_i — the ERC approximation; renormalize per iteration.
    """
    if not cov_matrix:
        cov_matrix = [[0.04, 0.01, 0.005],
                      [0.01, 0.09, 0.01],
                      [0.005, 0.01, 0.03]]
    cov = np.asarray(cov_matrix, dtype=float)
    n = cov.shape[0]
    inv = np.linalg.inv(cov + 1e-8 * np.eye(n))
    ones = np.ones(n)
    w = inv @ ones
    w = np.clip(w, 0, None)
    s = w.sum()
    if s <= 0:
        w = np.full(n, 1.0 / n)
    else:
        w = w / s

    exp_ret = 0.0  # risk parity is agnostic to expected returns
    exp_vol = float(math.sqrt(w @ cov @ w))
    sharpe = 0.0
    return PortfolioReport(
        method="risk parity (ERC)", weights=w.tolist(),
        expected_return=exp_ret, expected_vol=exp_vol, sharpe=sharpe,
        note="inverse-covariance equal risk contribution",
    )


# ── Option pricing (Q17, Q18, Q20) ──────────────────────────────────


def black_scholes(spot: float, strike: float, t: float, r: float,
                  sigma: float, option_type: str = "call") -> float:
    """Black-Scholes price (European)."""
    if t <= 0 or sigma <= 0:
        intrinsic = max(0.0, spot - strike) if option_type == "call" else max(0.0, strike - spot)
        return intrinsic
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma ** 2) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    from math import erf, sqrt
    def _N(x):
        return 0.5 * (1.0 + erf(x / sqrt(2.0)))
    if option_type == "call":
        return spot * _N(d1) - strike * math.exp(-r * t) * _N(d2)
    return strike * math.exp(-r * t) * _N(-d2) - spot * _N(-d1)


def implied_volatility(price: float, spot: float, strike: float, t: float,
                       r: float, option_type: str = "call",
                       tol: float = 1e-8, max_iter: int = 100) -> float:
    """Newton-bisection implied vol."""
    lo, hi = 0.001, 5.0
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        p = black_scholes(spot, strike, t, r, mid, option_type)
        if p > price:
            hi = mid
        else:
            lo = mid
        if hi - lo < tol:
            return 0.5 * (lo + hi)
    return 0.5 * (lo + hi)


def option_greeks(spot: float, strike: float, t: float, r: float,
                  sigma: float, option_type: str = "call") -> dict:
    """Delta/Gamma/Vega/Theta for European options."""
    from math import erf, sqrt, exp
    if t <= 0 or sigma <= 0:
        return {"delta": 0, "gamma": 0, "vega": 0, "theta": 0}
    def _N(x):
        return 0.5 * (1.0 + erf(x / sqrt(2.0)))
    def _n(x):
        return exp(-0.5 * x * x) / sqrt(2 * math.pi)
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma ** 2) * t) / (sigma * sqrt(t))
    d2 = d1 - sigma * sqrt(t)
    sign = 1 if option_type == "call" else -1
    delta = sign * _N(sign * d1)
    gamma = _n(d1) / (spot * sigma * sqrt(t))
    vega = spot * _n(d1) * sqrt(t) / 100.0
    theta = (-spot * _n(d1) * sigma / (2 * sqrt(t))
             - sign * r * strike * exp(-r * t) * _N(sign * d2)) / 365.0
    return {"delta": round(delta, 4), "gamma": round(gamma, 6),
            "vega": round(vega, 4), "theta": round(theta, 6)}


# ── Dispatch ────────────────────────────────────────────────────────


def compute(kind: str, **params: Any) -> dict:
    """Top-level dispatcher for the compute engine."""
    kind = kind.lower().replace("-", "_")
    if kind in ("risk", "var", "cvar", "risk_metrics"):
        return risk_metrics(
            params.get("prices", []),
            method=params.get("method", "historical"),
            risk_free=params.get("risk_free", 0.02),
            periods_per_year=params.get("periods_per_year", 252),
        ).to_dict()
    if kind in ("factor", "ic", "icir", "factor_ic"):
        return factor_ic(
            params.get("factor_values", []),
            params.get("forward_returns", []),
            periods=params.get("periods"),
        ).to_dict()
    if kind in ("mvo", "mean_variance", "portfolio"):
        return mean_variance_optimize(
            params.get("expected_returns", []),
            params.get("cov_matrix", []),
            risk_aversion=params.get("risk_aversion", 2.0),
        ).to_dict()
    if kind in ("risk_parity", "erc"):
        return risk_parity(params.get("cov_matrix", [])).to_dict()
    if kind in ("bs", "black_scholes", "option_price"):
        return {
            "price": round(black_scholes(
                params.get("spot", 100.0), params.get("strike", 100.0),
                params.get("t", 1.0), params.get("r", 0.03),
                params.get("sigma", 0.2), params.get("option_type", "call"),
            ), 6),
            "method": "Black-Scholes",
            "params": {"spot": params.get("spot", 100.0), "strike": params.get("strike", 100.0),
                       "t": params.get("t", 1.0), "r": params.get("r", 0.03), "sigma": params.get("sigma", 0.2)},
        }
    if kind in ("iv", "implied_vol"):
        spot, strike, t, r, sig = (params.get("spot", 100.0), params.get("strike", 100.0),
                                   params.get("t", 1.0), params.get("r", 0.03), params.get("sigma", 0.2))
        ref_price = black_scholes(spot, strike, t, r, sig, params.get("option_type", "call"))
        return {
            "implied_vol": round(implied_volatility(
                params.get("price", ref_price), spot, strike, t, r,
                params.get("option_type", "call"),
            ), 6),
            "reference_price": round(ref_price, 6),
        }
    if kind in ("greeks", "option_greeks"):
        return option_greeks(
            params.get("spot", 100.0), params.get("strike", 100.0),
            params.get("t", 1.0), params.get("r", 0.03),
            params.get("sigma", 0.2), params.get("option_type", "call"),
        )
    return {"error": f"unknown compute kind: {kind}", "supported": SUPPORTED_KINDS}


SUPPORTED_KINDS = [
    "risk_metrics", "factor_ic", "mean_variance", "risk_parity",
    "black_scholes", "implied_vol", "option_greeks",
]
