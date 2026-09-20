"""Large-scale NL→DSL evaluation: 100+ prompts across 7 categories.

Runs batch evaluation against vLLM, applies canonicalization + retry,
validates, transpiles, and generates a statistical report.

Usage:
    python scripts/gen_eval_dataset.py --vllm-url http://localhost:8000/v1 \
        --model models/qwen-trader-merged --output /workspace/persistent/batch_eval.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml


# === 100+ NL prompts across 7 categories ===

PROMPTS: list[dict] = []

# --- Trend Following (20) ---
for fast, slow in [(7,21),(9,21),(10,20),(12,26),(20,50),(20,200),(5,20),(9,50),(15,50),(10,30)]:
    PROMPTS.append({"nl": f"EMA{fast}上穿EMA{slow}时做多，下穿平仓，止损3%", "category": "trend_following", "expected": {"ema_fast","ema_slow"}})
    PROMPTS.append({"nl": f"When EMA{fast} crosses above EMA{slow}, go long. Exit on cross below. Stop loss 3%.", "category": "trend_following", "expected": {"ema_fast","ema_slow"}})

# --- Mean Reversion (20) ---
for oversold, overbought in [(25,75),(28,72),(30,70),(35,65),(20,80)]:
    PROMPTS.append({"nl": f"RSI低于{oversold}买入，高于{overbought}卖出，BTC/USDT 1h", "category": "mean_reversion", "expected": {"rsi"}})
    PROMPTS.append({"nl": f"RSI oversold at {oversold}, buy. Overbought at {overbought}, sell. BTC 1h.", "category": "mean_reversion", "expected": {"rsi"}})
    PROMPTS.append({"nl": f"Bollinger Bands strategy, buy at lower band, sell at upper. Period 20, std {2.0 if oversold==30 else 2.5}", "category": "mean_reversion", "expected": {"bb"}})
    PROMPTS.append({"nl": f"布林带策略，周期20，价格触及下轨买入上轨卖出，{oversold}%止损", "category": "mean_reversion", "expected": {"bb"}})

# --- Momentum (15) ---
for fast, slow, signal in [(12,26,9),(8,21,5),(10,20,9),(5,13,8),(12,30,9)]:
    PROMPTS.append({"nl": f"MACD策略，快线{fast}慢线{slow}信号线{signal}，金叉买入死叉卖出", "category": "momentum", "expected": {"macd"}})
    PROMPTS.append({"nl": f"MACD crossover: fast={fast}, slow={slow}, signal={signal}. Buy when MACD>0.", "category": "momentum", "expected": {"macd"}})
    PROMPTS.append({"nl": f"MACD金叉策略，BTC/USDT 4h，止损5%", "category": "momentum", "expected": {"macd"}})

# --- Breakout (15) ---
for mult in [1.2,1.5,1.8,2.0,2.5]:
    PROMPTS.append({"nl": f"放量突破策略，EMA20金叉EMA50且成交量大于均量{mult}倍确认", "category": "breakout", "expected": {"ema_fast","ema_slow","vol_ma"}})
    PROMPTS.append({"nl": f"Volume breakout: EMA20 crosses EMA50, volume > {mult}x average", "category": "breakout", "expected": {"ema_fast","ema_slow","vol_ma"}})
    PROMPTS.append({"nl": f"BTC突破策略，EMA金叉+放量{mult}倍确认+RSI过滤", "category": "breakout", "expected": {"ema_fast","ema_slow","vol_ma","rsi"}})

# --- Short Strategy (10) ---
PROMPTS.append({"nl": "做空策略：EMA死叉且RSI超买时做空，止损4%", "category": "short", "expected": {"ema_fast","ema_slow","rsi"}})
PROMPTS.append({"nl": "Short when EMA fast < EMA slow AND RSI > 70. Stop loss 4%.", "category": "short", "expected": {"ema_fast","ema_slow","rsi"}})
PROMPTS.append({"nl": "ETH做空，EMA9下穿EMA21，RSI>70确认，止损3%", "category": "short", "expected": {"ema_fast","ema_slow","rsi"}})
PROMPTS.append({"nl": "Bearish MACD strategy: sell when MACD<0, buy back when MACD>0", "category": "short", "expected": {"macd"}})
PROMPTS.append({"nl": "做空BTC，布林带触及上轨时做空，下轨平仓", "category": "short", "expected": {"bb"}})
PROMPTS.append({"nl": "Short BTC when Bollinger upper band touched, exit at lower band", "category": "short", "expected": {"bb"}})
PROMPTS.append({"nl": "RSI超买做空策略，RSI>75做空，RSI<30平仓", "category": "short", "expected": {"rsi"}})
PROMPTS.append({"nl": "Short when RSI>75, close when RSI<30, BTC 4h timeframe", "category": "short", "expected": {"rsi"}})
PROMPTS.append({"nl": "EMA50下穿EMA200做空（死叉），止损5%", "category": "short", "expected": {"ema_fast","ema_slow"}})
PROMPTS.append({"nl": "Death cross short: EMA50 < EMA200, stop loss 5%", "category": "short", "expected": {"ema_fast","ema_slow"}})

# --- Multi-indicator Confluence (10) ---
PROMPTS.append({"nl": "多指标共振：EMA金叉+RSI超卖+放量1.5倍确认", "category": "confluence", "expected": {"ema_fast","ema_slow","rsi","vol_ma"}})
PROMPTS.append({"nl": "Confluence: EMA cross + RSI oversold + volume 1.5x", "category": "confluence", "expected": {"ema_fast","ema_slow","rsi","vol_ma"}})
PROMPTS.append({"nl": "EMA交叉+MACD金叉+RSI确认的复合策略", "category": "confluence", "expected": {"ema_fast","ema_slow","macd","rsi"}})
PROMPTS.append({"nl": "EMA cross + MACD bullish + RSI filter combined strategy", "category": "confluence", "expected": {"ema_fast","ema_slow","macd","rsi"}})
PROMPTS.append({"nl": "布林带收窄后突破+放量确认+RSI方向确认", "category": "confluence", "expected": {"bb","vol_ma","rsi"}})
PROMPTS.append({"nl": "Bollinger squeeze breakout + volume + RSI direction", "category": "confluence", "expected": {"bb","vol_ma","rsi"}})
PROMPTS.append({"nl": "ATR止损+EMA趋势+ADX强度过滤的完整策略", "category": "confluence", "expected": {"ema_fast","ema_slow","atr","adx"}})
PROMPTS.append({"nl": "ATR stop + EMA trend + ADX filter complete strategy", "category": "confluence", "expected": {"ema_fast","ema_slow","atr","adx"}})
PROMPTS.append({"nl": "EMA趋势+成交量确认+RSI非超买的多重过滤", "category": "confluence", "expected": {"ema_fast","ema_slow","vol_ma","rsi"}})
PROMPTS.append({"nl": "EMA trend + volume confirm + RSI not overbought filter", "category": "confluence", "expected": {"ema_fast","ema_slow","vol_ma","rsi"}})

# --- Volatility / Risk-based (10) ---
PROMPTS.append({"nl": "用ATR指标做止损的EMA趋势策略，BTC/USDT 1h", "category": "volatility", "expected": {"ema_fast","ema_slow","atr"}})
PROMPTS.append({"nl": "ATR-based stop loss EMA trend strategy, BTC 1h", "category": "volatility", "expected": {"ema_fast","ema_slow","atr"}})
PROMPTS.append({"nl": "ATR动态止损策略，止损设为2倍ATR", "category": "volatility", "expected": {"atr"}})
PROMPTS.append({"nl": "Dynamic ATR stop loss, 2x ATR multiplier", "category": "volatility", "expected": {"atr"}})
PROMPTS.append({"nl": "高波动时放宽止损，低波动时收紧，用ATR判断", "category": "volatility", "expected": {"atr"}})
PROMPTS.append({"nl": "Widen stops in high vol, tighten in low vol, use ATR", "category": "volatility", "expected": {"atr"}})
PROMPTS.append({"nl": "布林带宽度判断波动率，收窄时等待突破", "category": "volatility", "expected": {"bb"}})
PROMPTS.append({"nl": "Bollinger bandwidth for volatility, wait for squeeze breakout", "category": "volatility", "expected": {"bb"}})
PROMPTS.append({"nl": "ADX判断趋势强度，ADX>25时才执行EMA策略", "category": "volatility", "expected": {"adx","ema_fast","ema_slow"}})
PROMPTS.append({"nl": "ADX trend strength filter, only trade when ADX>25", "category": "volatility", "expected": {"adx","ema_fast","ema_slow"}})

SYSTEM_PROMPT = "You are an expert crypto trading strategist. Convert the user's natural language trading idea into a YAML strategy DSL specification. Output ONLY valid YAML, no explanations."


@dataclass
class BatchResult:
    prompt_id: int
    nl: str
    category: str
    raw_output: str = ""
    extracted: bool = False
    canonicalized: bool = False
    schema_valid: bool = False
    transpile_ft: bool = False
    transpile_bt: bool = False
    indicators_match: bool = False
    passed: bool = False
    repairs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    retried: bool = False


def call_vllm(vllm_url: str, prompt: str, model: str) -> tuple[str, float]:
    import httpx
    t0 = time.time()
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(f"{vllm_url}/chat/completions", json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 1024,
            })
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"], (time.time() - t0) * 1000
    except Exception as e:
        return f"[ERROR] {e}", (time.time() - t0) * 1000


def extract_yaml(text: str) -> dict | None:
    yaml_match = re.search(r"```(?:ya?ml)?\s*\n(.*?)\n```", text, re.DOTALL)
    if yaml_match:
        try:
            parsed = yaml.safe_load(yaml_match.group(1))
            if isinstance(parsed, dict) and "strategy" in parsed:
                return parsed
        except yaml.YAMLError:
            pass
    strategy_match = re.search(r"(^|\n)(strategy:\s*\n.*)", text, re.DOTALL)
    if strategy_match:
        try:
            parsed = yaml.safe_load(strategy_match.group(2))
            if isinstance(parsed, dict) and "strategy" in parsed:
                return parsed
        except yaml.YAMLError:
            pass
    try:
        parsed = yaml.safe_load(text)
        if isinstance(parsed, dict) and "strategy" in parsed:
            return parsed
    except yaml.YAMLError:
        pass
    return None


def validate_and_canonicalize(dsl: dict) -> tuple[dict, bool, list[str], list[str]]:
    import copy, ast
    from src.dsl.canonicalizer import canonicalize_dsl
    from src.dsl.validator import validate_dsl as _raw_validate
    from src.dsl.transpiler import transpile_to_freqtrade
    from src.dsl.transpiler_backtrader import transpile_to_backtrader

    canon = copy.deepcopy(dsl)
    canon, repairs, canon_errors = canonicalize_dsl(canon)
    if canon_errors:
        return canon, False, canon_errors, [f"{r.field}: {r.raw}→{r.normalized}({r.repair_type})" for r in repairs]

    valid, errors = _raw_validate(canon)
    repair_strs = [f"{r.field}: {r.raw}→{r.normalized}({r.repair_type})" for r in repairs]

    if not valid:
        return canon, False, errors, repair_strs

    # Transpile check
    ft_ok = bt_ok = True
    try:
        ast.parse(transpile_to_freqtrade(canon))
    except Exception:
        ft_ok = False
    try:
        ast.parse(transpile_to_backtrader(canon))
    except Exception:
        bt_ok = False

    if not ft_ok or not bt_ok:
        return canon, False, ["Transpilation failed"], repair_strs

    return canon, True, [], repair_strs


def run_batch(vllm_url: str, model: str, max_prompts: int = 200) -> list[BatchResult]:
    results: list[BatchResult] = []
    prompts = PROMPTS[:max_prompts]

    for i, tc in enumerate(prompts):
        r = BatchResult(prompt_id=i, nl=tc["nl"], category=tc["category"])
        expected = tc.get("expected", set())

        # First attempt
        r.raw_output, r.latency_ms = call_vllm(vllm_url, tc["nl"], model)

        if r.raw_output.startswith("[ERROR]"):
            r.errors.append(r.raw_output[:100])
            results.append(r)
            continue

        dsl = extract_yaml(r.raw_output)
        if dsl is None:
            r.errors.append("YAML extraction failed")
            results.append(r)
            continue
        r.extracted = True

        canon, valid, errors, repairs = validate_and_canonicalize(dsl)
        r.repairs = repairs[:5]

        # Check for unrecoverable → retry
        unrecoverable = any(any(kw in e for kw in ("cannot parse", "Missing 'indicators'", "expression")) for e in errors)
        if unrecoverable:
            r.retried = True
            retry_prompt = (
                f"{tc['nl']}\n\nPrevious errors:\n" + "\n".join(f"- {e}" for e in errors[:3]) +
                "\n\nFix: stop_loss must be negative number, indicators must be non-empty list, entry/exit only long/short."
            )
            r.raw_output, r.latency_ms = call_vllm(vllm_url, retry_prompt, model)
            dsl = extract_yaml(r.raw_output)
            if dsl:
                canon, valid, errors, repairs2 = validate_and_canonicalize(dsl)
                r.repairs.extend(repairs2[:3])

        r.canonicalized = True
        r.schema_valid = valid
        if errors:
            r.errors = errors[:3]

        if valid:
            # Check transpile
            import ast
            from src.dsl.transpiler import transpile_to_freqtrade
            from src.dsl.transpiler_backtrader import transpile_to_backtrader
            try:
                ast.parse(transpile_to_freqtrade(canon)); r.transpile_ft = True
            except Exception: pass
            try:
                ast.parse(transpile_to_backtrader(canon)); r.transpile_bt = True
            except Exception: pass

            # Check indicators
            strat = canon.get("strategy", {})
            inds = strat.get("indicators", [])
            actual = {ind.get("name") for ind in inds if isinstance(ind, dict)}
            r.indicators_match = expected.issubset(actual) if expected else True

        r.passed = r.schema_valid and r.transpile_ft and r.transpile_bt and r.indicators_match

        if (i + 1) % 10 == 0:
            passed_so_far = sum(1 for x in results if x.passed)
            print(f"  [{i+1}/{len(prompts)}] Pass: {passed_so_far}/{i+1} ({passed_so_far/(i+1)*100:.0f}%)", flush=True)

        results.append(r)

    return results


def print_report(results: list[BatchResult]) -> None:
    n = len(results)
    if n == 0:
        print("No results."); return

    extracted = sum(1 for r in results if r.extracted)
    schema_ok = sum(1 for r in results if r.schema_valid)
    ft_ok = sum(1 for r in results if r.transpile_ft)
    bt_ok = sum(1 for r in results if r.transpile_bt)
    ind_match = sum(1 for r in results if r.indicators_match)
    passed = sum(1 for r in results if r.passed)
    retried = sum(1 for r in results if r.retried)

    latencies = [r.latency_ms for r in results if r.latency_ms > 0]
    avg_lat = sum(latencies) / len(latencies) if latencies else 0
    latencies_sorted = sorted(latencies)
    p95_idx = int(len(latencies_sorted) * 0.95)
    p95_lat = latencies_sorted[p95_idx] if p95_idx < len(latencies_sorted) else 0

    print("=" * 70)
    print("  Large-Scale NL→DSL Evaluation Report")
    print("=" * 70)
    print()
    print(f"  Total prompts:    {n}")
    print(f"  YAML extracted:   {extracted}/{n} ({extracted/n*100:.0f}%)")
    print(f"  Schema valid:     {schema_ok}/{n} ({schema_ok/n*100:.0f}%)")
    print(f"  Freqtrade OK:     {ft_ok}/{n} ({ft_ok/n*100:.0f}%)")
    print(f"  Backtrader OK:    {bt_ok}/{n} ({bt_ok/n*100:.0f}%)")
    print(f"  Indicators match: {ind_match}/{n} ({ind_match/n*100:.0f}%)")
    print(f"  Retried:          {retried}/{n}")
    print(f"  ────────────────────────────────────")
    print(f"  OVERALL PASS:     {passed}/{n} ({passed/n*100:.1f}%)")
    print()
    print(f"  Latency: avg={avg_lat:.0f}ms, p95={p95_lat:.0f}ms")
    print()

    # By category
    cats: dict[str, list[bool]] = {}
    for r in results:
        cats.setdefault(r.category, []).append(r.passed)
    print("  By category:")
    for cat in sorted(cats):
        passes = sum(cats[cat])
        total = len(cats[cat])
        print(f"    {cat:20s}: {passes}/{total} ({passes/total*100:.0f}%)")
    print()


def save_results(results: list[BatchResult], path: str) -> None:
    data = [asdict(r) for r in results]
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  Results saved to {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Large-scale NL→DSL evaluation")
    parser.add_argument("--vllm-url", required=True)
    parser.add_argument("--model", default="models/qwen-trader-merged")
    parser.add_argument("--max", type=int, default=200, help="Max prompts to run")
    parser.add_argument("--output", default="/workspace/persistent/batch_eval.json")
    args = parser.parse_args()

    print(f"Running {min(args.max, len(PROMPTS))} prompts against {args.vllm_url}...")
    results = run_batch(args.vllm_url, args.model, args.max)
    print_report(results)
    save_results(results, args.output)
