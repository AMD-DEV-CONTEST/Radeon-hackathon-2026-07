"""Local compute tools — local quant math engine (no external deps).

`compute(kind, **params)` runs the calculation and returns a plain dict;
the registry wraps it into a ToolResult (protocol lives in external/,
kept separate to avoid circular imports).
"""

from __future__ import annotations

from typing import Any

from .engine import compute, SUPPORTED_KINDS


def resolve_compute(query: str, kind: str | None = None,
                    params: dict[str, Any] | None = None) -> dict:
    """Resolve a compute request to a plain result dict.

    kind: optional explicit kind; auto-detected from query keywords.
    params: input data (prices, cov matrix, option params, ...).
    Returns {"success": bool, "kind": str, "result": dict} — registry
    wraps this into the auditable ToolResult.
    """
    params = params or {}
    kind = kind or _detect_kind(query)
    # Only inject demo prices into price-series kinds; option kinds use
    # their own defaults (spot/strike/t/sigma) to avoid zero-division.
    if "prices" in params and kind in ("black_scholes", "implied_vol", "option_greeks"):
        params = {k: v for k, v in params.items() if k != "prices"}
    result = compute(kind, **params)
    return {"success": "error" not in result, "kind": kind, "result": result}


_KIND_WORDS: list[tuple[str, list[str]]] = [
    # Most specific first (longer/more precise phrases) to avoid
    # risk_metrics' generic "风险/波动率" stealing them.
    ("risk_parity", ["风险平价", "risk parity", "erc", "等风险贡献"]),
    ("black_scholes", ["black-scholes", "bs模型", "bs定价", "期权定价", "option price", "期权理论价格"]),
    ("implied_vol", ["隐含波动率", "implied vol", "隐含vol"]),
    ("option_greeks", ["greeks", "期权delta", "期权gamma", "delta中性", "对冲"]),
    ("mean_variance", ["均值方差", "有效前沿", "组合优化", "mean-variance", "optimization", "最优权重"]),
    ("factor_ic", ["因子", "ic值", "icir", "factor", "相关性", "衰减", "信息系数"]),
    ("risk_metrics", ["var", "cvar", "夏普", "sharpe", "回撤", "drawdown", "sortino", "calmar", "风险", "波动率"]),
]


def _detect_kind(query: str) -> str:
    q = query.lower()
    for kind, words in _KIND_WORDS:
        if any(w in q for w in words):
            return kind
    return "risk_metrics"


__all__ = ["compute", "resolve_compute", "SUPPORTED_KINDS"]
