#!/usr/bin/env python3
"""Track 2 — reproducible one-command demo: NL → DSL → canonicalize → validate → transpile → backtest → risk report.

CPU-only / no-GPU / no-network / no-model-weights. Any machine can run the full pipeline:

    python demos/run_track2_demo.py

- DSL generation: tries a local vLLM endpoint first (AMD ROCm machine). If unreachable,
  falls back to built-in deterministic DSL templates so the pipeline always runs.
- Backtest: in-process repository engine (src/backtest.runner). Market data is forced to
  deterministic synthetic OHLCV (no exchange API, no network).
- Fully DRY_RUN: no real orders, no external API, no model weights required.

Optional (real AMD ROCm + local vLLM):
    VLLM=http://127.0.0.1:8000/v1 MODEL=models/qwen-trader-merged python demos/run_track2_demo.py
"""

import ast
import copy
import os
import re
import sys
import time
from pathlib import Path

# --- repo root: works regardless of where the repo is cloned ---
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import yaml  # noqa: E402

from src.dsl.canonicalizer import canonicalize_dsl  # noqa: E402
from src.dsl.validator import validate_dsl  # noqa: E402
from src.dsl.transpiler import transpile_to_freqtrade  # noqa: E402
from src.dsl.transpiler_backtrader import transpile_to_backtrader  # noqa: E402
from src.backtest.runner import run_backtest  # noqa: E402
from src.backtest import runner as _runner  # noqa: E402
import src.backtest.data_fetcher as _data_fetcher  # noqa: E402
from src.backtest.data_fetcher import _generate_synthetic_ohlcv  # noqa: E402

VLLM = os.environ.get("VLLM", "http://localhost:8000/v1")
MODEL = os.environ.get("MODEL", "models/qwen-trader-merged")

LLM_SYSTEM = (
    "You are an expert trading strategist. Convert the user's natural language trading idea "
    "into a YAML strategy DSL. Output ONLY valid YAML.\n"
    "Rules: stop_loss MUST be negative in risk:. period MUST be integer. "
    "Only long/short in entry/exit. indicators MUST be non-empty list."
)

# --- built-in deterministic fallback DSL templates (used when no local vLLM) ---
FALLBACK_CASES = [
    {
        "nl": "BTC 1小时 EMA20/EMA50 金叉策略，回测并分析风险，止损2%",
        "dsl": {
            "strategy": {
                "name": "EMA_Trend_BTC",
                "market": {"exchange": "binance", "pair": "BTC/USDT", "timeframe": "1h"},
                "indicators": [
                    {"name": "ema_fast", "type": "EMA", "params": {"period": 20, "field": "close"}},
                    {"name": "ema_slow", "type": "EMA", "params": {"period": 50, "field": "close"}},
                ],
                "entry": {"long": "ema_fast > ema_slow", "short": None},
                "exit": {"long": "ema_fast < ema_slow", "short": None},
                "risk": {"stop_loss": -0.02, "max_open_trades": 3, "stake_amount": 0.1},
            }
        },
    },
    {
        "nl": "BTC 4小时 RSI 超卖均值回归：RSI<30 买入，RSI>70 卖出，止损2%",
        "dsl": {
            "strategy": {
                "name": "RSI_MeanRev_BTC",
                "market": {"exchange": "binance", "pair": "BTC/USDT", "timeframe": "4h"},
                "indicators": [
                    {"name": "rsi14", "type": "RSI", "params": {"period": 14}},
                ],
                "entry": {"long": "rsi14 < 30", "short": "rsi14 > 70"},
                "exit": {"long": "rsi14 > 55", "short": "rsi14 < 45"},
                "risk": {"stop_loss": -0.02, "max_open_trades": 3, "stake_amount": 0.1},
            }
        },
    },
]


def extract_yaml(text: str):
    """Pull the first `strategy:` YAML dict out of an LLM response."""
    for pattern in [r"```(?:ya?ml)?\s*\n(.*?)\n```", r"(^|\n)(strategy:\s*\n.*)"]:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                p = yaml.safe_load(m.group(1) if "```" in pattern else m.group(2))
                if isinstance(p, dict) and "strategy" in p:
                    return p
            except yaml.YAMLError:
                pass
    try:
        p = yaml.safe_load(text)
        if isinstance(p, dict) and "strategy" in p:
            return p
    except yaml.YAMLError:
        pass
    return None


def generate_dsl(nl: str, fallback: dict) -> tuple[dict, str]:
    """Try local vLLM (short timeout); fall back to a built-in deterministic template."""
    if os.environ.get("VLLM_DISABLE"):
        return fallback, "TEMPLATE"
    try:
        import httpx  # noqa: WPS433

        with httpx.Client(timeout=8) as c:
            r = c.post(
                f"{VLLM}/chat/completions",
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": LLM_SYSTEM},
                        {"role": "user", "content": nl},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 2048,
                },
            )
            content = r.json()["choices"][0]["message"]["content"]
        dsl = extract_yaml(content)
        if dsl:
            return dsl, "VLLM"
        print("    (vLLM output did not parse as DSL; using built-in template)")
    except Exception as e:  # noqa: BLE001
        print(f"    (vLLM unreachable: {type(e).__name__}; using built-in template)")
    return fallback, "TEMPLATE"


def risk_report(res) -> str:
    """Risk-agent style evaluation over backtest metrics (mirrors the live Agent)."""
    risks = []
    if res.sharpe_ratio >= 1.0:
        print(f"    [OK]   Sharpe >= 1.0: acceptable ({res.sharpe_ratio:.2f})")
    else:
        print(f"    [WARN] Sharpe < 1.0: low risk-adjusted return ({res.sharpe_ratio:.2f})")
        risks.append("Low Sharpe")
    if res.max_drawdown >= -0.20:
        print(f"    [OK]   Max drawdown < 20%: controlled ({res.max_drawdown:.2%})")
    else:
        print(f"    [WARN] Max drawdown > 20%: high risk ({res.max_drawdown:.2%})")
        risks.append("High drawdown")
    if res.alpha >= 0:
        print(f"    [OK]   Alpha >= 0: beats buy-and-hold ({res.alpha:+.2%})")
    else:
        print(f"    [WARN] Alpha < 0: underperforms buy-and-hold ({res.alpha:+.2%})")
        risks.append("Negative alpha")
    if res.max_consecutive_losses > 5:
        print(f"    [WARN] Consecutive losses > 5: sustainability risk ({res.max_consecutive_losses})")
        risks.append("Consecutive losses")
    if res.win_rate < 0.30:
        print(f"    [WARN] Win rate < 30%: low hit rate ({res.win_rate:.1%})")
        risks.append("Low win rate")

    if len(risks) >= 3:
        verdict = "REJECT"
    elif res.sharpe_ratio > 0 and res.alpha > 0 and res.max_drawdown > -0.30 and len(risks) <= 1:
        verdict = "APPROVE"
    else:
        verdict = "MODIFY"
    print(f"    VERDICT: {verdict}  (flags: {risks if risks else 'none'})")
    return verdict


def run_one_case(nl: str, fallback: dict, idx: int) -> dict:
    print("=" * 72)
    print(f"  CASE {idx}: {nl}")
    print("=" * 72)

    t0 = time.time()
    dsl, source = generate_dsl(nl, fallback)
    print(f"[1] DSL GENERATION  [{source}]  ({time.time() - t0:.1f}s)")
    print(f"    strategy.name = {dsl['strategy'].get('name')}")

    canon, repairs, errors = canonicalize_dsl(copy.deepcopy(dsl))
    print(f"[2] CANONICALIZE  repairs={len(repairs)} errors={len(errors)}")
    for r in repairs[:3]:
        print(f"      fix: {getattr(r, 'field', '?')} {getattr(r, 'raw', '')} -> {getattr(r, 'normalized', '')}")

    valid, verrors = validate_dsl(canon)
    print(f"[3] VALIDATE  schema={'PASS' if valid else 'FAIL'}")
    if not valid:
        print(f"    errors: {verrors[:3]}")
        print("    SKIP: invalid DSL — no backtest")
        return {"case": idx, "valid": False, "source": source}

    ft_ok = bt_ok = False
    try:
        ast.parse(transpile_to_freqtrade(canon))
        ft_ok = True
    except Exception:  # noqa: BLE001
        pass
    try:
        ast.parse(transpile_to_backtrader(canon))
        bt_ok = True
    except Exception:  # noqa: BLE001
        pass
    print(f"    freqtrade transpile: {'OK' if ft_ok else 'FAIL'}")
    print(f"    backtrader transpile: {'OK' if bt_ok else 'FAIL'}")

    t1 = time.time()
    res = run_backtest(canon, days=180, initial_balance=10000)
    print(f"[4] BACKTEST  (180d, deterministic synthetic OHLCV, {time.time() - t1:.1f}s)")
    print(f"    trades={res.total_trades}  win_rate={res.win_rate:.1%}  "
          f"return={res.total_return:.2%}  alpha={res.alpha:+.2%}")
    print(f"    max_drawdown={res.max_drawdown:.2%}  sharpe={res.sharpe_ratio:.2f}  "
          f"profit_factor={res.profit_factor:.2f}")
    print(f"    final_balance=${res.final_balance:,.2f}  (benchmark={res.benchmark_return:.2%})")

    print("[5] RISK REPORT")
    verdict = risk_report(res)
    print()
    return {"case": idx, "valid": True, "source": source, "verdict": verdict, "return": res.total_return}


def main() -> None:
    # Force deterministic synthetic data in-process (no network / exchange dependency).
    if not os.environ.get("DATA_MODE", "").lower() in ("live", "exchange"):
        def _synthetic(pair="BTC/USDT", timeframe="1h", exchange_name="binance",
                       days=180, since=None, limit=1000):
            return _generate_synthetic_ohlcv(pair, timeframe, days)

        # runner.py binds `fetch_ohlcv` at import time via `from .data_fetcher import fetch_ohlcv`,
        # so patch both module references to guarantee zero network attempts.
        _data_fetcher.fetch_ohlcv = _synthetic
        _runner.fetch_ohlcv = _synthetic
        print("data source: deterministic synthetic OHLCV (no network)  [DATA_MODE != live]\n")

    print("AMD ROCm Local Quantitative Investment Assistant — reproducible demo")
    print("Pipeline: natural language -> DSL -> canonicalize -> validate -> transpile -> backtest -> risk\n")

    results = []
    for i, case in enumerate(FALLBACK_CASES, 1):
        results.append(run_one_case(case["nl"], case["dsl"], i))

    print("=" * 72)
    print("  SUMMARY")
    for r in results:
        status = "OK" if r.get("valid") else "SKIP(INVALID)"
        print(f"    Case {r['case']}: source={r['source']}  status={status}  "
              f"verdict={r.get('verdict', '-')}  return={r.get('return', '-')}")
    print("=" * 72)
    print("\nDemo complete. This run used deterministic synthetic data and never touched real funds.")


if __name__ == "__main__":
    main()
