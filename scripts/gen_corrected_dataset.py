"""Generate corrected NL→DSL training data via model + canonicalizer pipeline.

Uses the fine-tuned model to generate DSL from diverse NL prompts,
then canonicalizes and validates. Only keeps validated samples.

Usage:
    python scripts/gen_corrected_dataset.py --vllm-url http://localhost:8000/v1 \
        --model models/qwen-trader-merged \
        --output /workspace/persistent/corrected_train.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml

SYSTEM_PROMPT = """You are an expert crypto trading strategist. Convert the user's natural language trading idea into a YAML strategy DSL specification.

Output ONLY valid YAML with this structure:
```yaml
strategy:
  name: StrategyName
  market:
    exchange: binance
    pair: BTC/USDT
    timeframe: 1h
  indicators:
    - name: ema_fast
      type: EMA
      params:
        period: 20
        field: close
  entry:
    long: "ema_fast > ema_slow"
    short: null
  exit:
    long: "ema_fast < ema_slow"
    short: null
  risk:
    stop_loss: -0.03
    max_open_trades: 3
    stake_amount: 0.1
```

Rules: stop_loss MUST be negative. period MUST be integer. Output ONLY YAML."""

# Diverse NL prompts for training data generation
GEN_PROMPTS = [
    "EMA crossover strategy for BTC/USDT, EMA 9 and 21, 1h timeframe, 3% stop loss",
    "RSI策略，BTC/USDT 1h，RSI低于28买入，高于72卖出，止损4%",
    "Bollinger Bands mean reversion, ETH/USDT 4h, period 20, std 2.0, 3% stop",
    "MACD crossover strategy, BTC/USDT 4h, fast 12 slow 26 signal 9, 5% stop loss",
    "Volume breakout: EMA 10 crosses EMA 50, volume > 2x average, RSI < 70",
    "做多做空双向：EMA金叉做多，死叉做空，BTC/USDT 1h，止损3%",
    "ATR-based stop loss EMA trend strategy, 2x ATR stop, BTC 1h",
    "ADX filter: only trade when ADX > 25, EMA 20/50 crossover, BTC 4h",
    "多指标共振：EMA金叉 + RSI < 35 + volume > 1.5x average",
    "Supertrend strategy, BTC/USDT 1h, price above supertrend go long",
    "EMA 5/15 crossover for SOL/USDT 15m timeframe, tight 2% stop loss",
    "RSI divergence strategy, BTC/USDT 4h, RSI < 30 with price making higher lows",
    "Bollinger squeeze breakout, ETH/USDT 1h, enter when bands expand after squeeze",
    "MACD + RSI combined, buy when MACD > 0 AND RSI < 50, BTC 1h",
    "做多ETH，EMA20上穿EMA50，放量1.5倍确认，RSI < 70，止损3%",
    "Short strategy: EMA death cross + RSI > 70, BTC/USDT 4h, 4% stop loss",
    "Trailing stop strategy, EMA 10/30 trend, 2% trailing, BTC 1h",
    "VWAP策略，价格在VWAP之上做多，之下做空，BTC/USDT 15m",
    "Ichimoku cloud strategy, buy when price above cloud, BTC 4h",
    "CCI策略，CCI低于-100买入，高于100卖出，BTC/USDT 1h",
    "EMA 20/200 golden cross for long-term, BTC/USDT 1d, 8% stop loss",
    "Stochastic策略，K线低于20买入，高于80卖出，ETH/USDT 1h",
    "Hull MA crossover, period 16, BTC/USDT 1h, 3% stop loss",
    "ZLEMA趋势策略，周期20，BTC/USDT 4h，止损4%",
    "做多BNB，EMA7/25交叉，1h周期，止损2%",
    "ADX > 30 strong trend filter, EMA 9/21, volume 1.8x, BTC 1h",
    "Bollinger + RSI combo: buy at lower band AND RSI < 30, BTC 1h",
    "EMA趋势 + ATR止损，周期14 ATR，2倍ATR止损，BTC 4h",
    "做空ETH，布林带上轨触及时做空，下轨平仓，4h周期",
    "MACD bearish crossover short strategy, BTC 4h, 5% stop loss",
    "Multi-timeframe: EMA 50 trend on 4h, entry on 1h EMA 20/50 cross",
    "OBV divergences: price up but OBV down, short signal, BTC 1h",
    "EMA 12/26 crossover with MACD histogram confirmation, BTC 1h",
    "RSI + Bollinger + volume triple confirmation, ETH/USDT 1h",
    "Supertrend + EMA trend filter, BTC/USDT 4h, 3% stop loss",
    "Ichimoku + RSI filter, buy above cloud AND RSI < 60, BTC 4h",
    "VWAP bounce strategy, buy near VWAP in uptrend, BTC 15m",
    "ADX trend strength + MACD momentum, BTC 1h, 3% stop",
    "EMA 50/200 death cross short, BTC 1d, 6% stop loss",
    "Bollinger squeeze + ADX > 25 + volume breakout, ETH 1h",
    "RSI 14 oversold bounce with volume confirmation, BTC 1h",
    "MACD zero-line crossover, buy when MACD turns positive, ETH 4h",
    "Hull MA + ATR trailing stop, BTC 1h, 2x ATR",
    "CCI overbought/oversold, ±100 threshold, BTC 1h",
    "EMA ribbon strategy, 8/13/21/34, trend alignment, BTC 4h",
    "Stochastic + MACD double confirmation, ETH/USDT 1h",
    "Bollinger bandwidth expansion breakout, BTC 1h, 3% stop",
    "VWAP + EMA trend combo, BTC 15m, 2% stop loss",
    "Ichimoku tenkan/kijun cross, BTC 4h, 4% stop loss",
    "做多SOL，Supertrend翻转做多，1h周期，止损3%",
    "做空BTC，MACD死叉且ADX > 25确认，4h周期，止损4%",
]


def call_vllm(vllm_url: str, prompt: str, model: str) -> str:
    import httpx
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(f"{vllm_url}/chat/completions", json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.4,
                "max_tokens": 1024,
            })
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[ERROR] {e}"


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


def main():
    parser = argparse.ArgumentParser(description="Generate corrected NL→DSL training data")
    parser.add_argument("--vllm-url", required=True)
    parser.add_argument("--model", default="models/qwen-trader-merged")
    parser.add_argument("--output", default="/workspace/persistent/corrected_train.jsonl")
    args = parser.parse_args()

    from src.dsl.canonicalizer import canonicalize_dsl
    from src.dsl.validator import validate_dsl as _validate
    import ast
    from src.dsl.transpiler import transpile_to_freqtrade

    total = 0
    valid = 0
    results: list[dict] = []

    print(f"Generating {len(GEN_PROMPTS)} NL→DSL pairs...")

    for i, nl_prompt in enumerate(GEN_PROMPTS):
        raw = call_vllm(args.vllm_url, nl_prompt, args.model)
        total += 1

        if raw.startswith("[ERROR]"):
            continue

        dsl = extract_yaml(raw)
        if dsl is None:
            continue

        # Canonicalize
        import copy
        canon = copy.deepcopy(dsl)
        canon, repairs, errors = canonicalize_dsl(canon)
        if errors:
            continue

        # Validate
        is_valid, verrors = _validate(canon)
        if not is_valid:
            continue

        # Transpile check
        try:
            code = transpile_to_freqtrade(canon)
            ast.parse(code)
        except Exception:
            continue

        # Valid sample — save as training pair
        dsl_yaml = yaml.dump(canon, default_flow_style=False, sort_keys=False, allow_unicode=True)
        results.append({
            "instruction": f"Convert this trading idea to DSL:\n\n{nl_prompt}",
            "input": "",
            "output": dsl_yaml,
            "source": "corrected-v2",
            "repairs": len(repairs),
        })
        valid += 1

        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{len(GEN_PROMPTS)}] Valid: {valid}/{total} ({valid/total*100:.0f}%)", flush=True)

    # Save
    with open(args.output, "w") as f:
        for item in results:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"\nDone: {valid}/{total} valid samples ({valid/total*100:.0f}%) → {args.output}")
    print(f"Average repairs per sample: {sum(r['repairs'] for r in results)/len(results):.1f}" if results else "No valid samples")


if __name__ == "__main__":
    main()
