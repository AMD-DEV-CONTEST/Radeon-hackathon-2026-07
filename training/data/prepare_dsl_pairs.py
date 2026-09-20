"""Generate NL→DSL instruction pairs for fine-tuning.

These pairs teach the LLM to convert natural language trading ideas
into structured YAML strategy DSL specifications using Chain-of-Thought
reasoning.

We use template-based generation to cover common strategy patterns:
- Moving average crossover
- RSI mean reversion
- Bollinger Bands squeeze
- Volume breakout
- MACD divergence
- Multi-indicator confluence

Each training pair includes a reasoning trace that walks through:
1. Strategy type identification
2. Indicator selection rationale
3. Entry/exit logic design
4. Risk parameter justification
"""

from __future__ import annotations

import json
import random
from pathlib import Path


OUTPUT_DIR = Path(__file__).parent.parent / "data" / "processed"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# --- Strategy templates ---

STRATEGY_TEMPLATES: list[dict] = [
    # 1. EMA Crossover
    {
        "nl_patterns": [
            "BTC EMA{fast}上穿EMA{slow}时做多，下穿时平仓",
            "When EMA{fast} crosses above EMA{slow} on BTC, go long. Exit on cross below.",
            "以太坊均线交叉策略，快线{fast}慢线{slow}，金叉买入死叉卖出",
            "Create an EMA crossover strategy: fast={fast}, slow={slow}, pair={pair}",
            "帮我做一个EMA{fast}和EMA{slow}交叉的策略，交易对{pair}",
        ],
        "dsl": {
            "strategy": {
                "name": "EMA_Crossover_{fast}_{slow}",
                "market": {
                    "exchange": "binance",
                    "pair": "{pair}",
                    "timeframe": "{timeframe}",
                },
                "indicators": [
                    {"name": "ema_fast", "type": "EMA", "params": {"period": "{fast}", "field": "close"}},
                    {"name": "ema_slow", "type": "EMA", "params": {"period": "{slow}", "field": "close"}},
                ],
                "entry": {
                    "long": "ema_fast > ema_slow",
                    "short": None,
                },
                "exit": {
                    "long": "ema_fast < ema_slow",
                    "short": None,
                },
                "risk": {
                    "stop_loss": -0.03,
                    "max_open_trades": 3,
                    "stake_amount": 0.1,
                },
            }
        },
    },
    # 2. RSI Mean Reversion
    {
        "nl_patterns": [
            "RSI低于{oversold}时买入，高于{overbought}时卖出",
            "RSI oversold at {oversold}, buy; overbought at {overbought}, sell",
            "RSI超卖策略，{pair}，RSI低于{oversold}做多",
            "Create RSI mean reversion: oversold={oversold}, overbought={overbought}",
            "做一个RSI策略，{pair}，超卖线{oversold}，超买线{overbought}",
        ],
        "dsl": {
            "strategy": {
                "name": "RSI_MeanReversion_{oversold}_{overbought}",
                "market": {
                    "exchange": "binance",
                    "pair": "{pair}",
                    "timeframe": "{timeframe}",
                },
                "indicators": [
                    {"name": "rsi", "type": "RSI", "params": {"period": 14}},
                ],
                "entry": {
                    "long": "rsi < {oversold}",
                    "short": None,
                },
                "exit": {
                    "long": "rsi > {overbought}",
                    "short": None,
                },
                "risk": {
                    "stop_loss": -0.05,
                    "max_open_trades": 2,
                    "stake_amount": 0.1,
                },
            }
        },
    },
    # 3. Bollinger Bands
    {
        "nl_patterns": [
            "布林带策略，价格触及下轨买入，触及上轨卖出",
            "Bollinger Bands strategy: buy at lower band, sell at upper band",
            "BB策略 {pair}，标准差{std}，周期{period}",
            "Create a Bollinger Bands strategy with period={period}, std={std}",
            "做个布林带策略，周期{period}，{pair}，止损3%",
        ],
        "dsl": {
            "strategy": {
                "name": "BB_MeanReversion_{period}",
                "market": {
                    "exchange": "binance",
                    "pair": "{pair}",
                    "timeframe": "{timeframe}",
                },
                "indicators": [
                    {"name": "bb", "type": "BollingerBands", "params": {"period": "{period}", "std_dev": "{std}"}},
                ],
                "entry": {
                    "long": "close < bb_lower",
                    "short": None,
                },
                "exit": {
                    "long": "close > bb_upper",
                    "short": None,
                },
                "risk": {
                    "stop_loss": -0.03,
                    "max_open_trades": 3,
                    "stake_amount": 0.1,
                },
            }
        },
    },
    # 4. Volume Breakout
    {
        "nl_patterns": [
            "放量突破策略，成交量大于均量{multi}倍时入场",
            "Volume breakout: enter when volume > {multi}× average",
            "BTC突破策略，EMA{fast}金叉EMA{slow}且放量{multi}倍确认",
            "Create a volume-confirmed breakout: EMA fast={fast}, slow={slow}, vol multiplier={multi}",
            "做一个放量的EMA突破策略，{pair}，止损3%，成交量{multi}倍确认",
        ],
        "dsl": {
            "strategy": {
                "name": "Volume_Breakout_{fast}_{slow}",
                "market": {
                    "exchange": "binance",
                    "pair": "{pair}",
                    "timeframe": "{timeframe}",
                },
                "indicators": [
                    {"name": "ema_fast", "type": "EMA", "params": {"period": "{fast}", "field": "close"}},
                    {"name": "ema_slow", "type": "EMA", "params": {"period": "{slow}", "field": "close"}},
                    {"name": "vol_ma", "type": "SMA", "params": {"period": 20, "field": "volume"}},
                    {"name": "rsi", "type": "RSI", "params": {"period": 14}},
                ],
                "entry": {
                    "long": "ema_fast > ema_slow AND volume > vol_ma * {multi} AND rsi < 70",
                    "short": None,
                },
                "exit": {
                    "long": "ema_fast < ema_slow",
                    "short": None,
                },
                "risk": {
                    "stop_loss": -0.03,
                    "trailing_stop": True,
                    "trailing_stop_positive": 0.02,
                    "max_open_trades": 3,
                    "stake_amount": 0.1,
                },
            }
        },
    },
    # 5. MACD Strategy
    {
        "nl_patterns": [
            "MACD策略，金叉买入死叉卖出",
            "MACD crossover strategy: buy on bullish crossover, sell on bearish",
            "MACD策略 {pair}，快线{fast}慢线{slow}信号线{signal}",
            "Create MACD strategy: fast={fast}, slow={slow}, signal={signal}",
            "做个MACD策略，{pair}，止损5%",
        ],
        "dsl": {
            "strategy": {
                "name": "MACD_Crossover_{fast}_{slow}",
                "market": {
                    "exchange": "binance",
                    "pair": "{pair}",
                    "timeframe": "{timeframe}",
                },
                "indicators": [
                    {"name": "macd", "type": "MACD", "params": {"fast_period": "{fast}", "slow_period": "{slow}", "signal_period": "{signal}"}},
                ],
                "entry": {
                    "long": "macd > 0",
                    "short": None,
                },
                "exit": {
                    "long": "macd < 0",
                    "short": None,
                },
                "risk": {
                    "stop_loss": -0.05,
                    "max_open_trades": 2,
                    "stake_amount": 0.1,
                },
            }
        },
    },
    # 6. Multi-indicator Confluence
    {
        "nl_patterns": [
            "多指标共振策略，EMA金叉+RSI超卖+放量确认",
            "Multi-indicator confluence: EMA cross + RSI oversold + volume confirmation",
            "复合策略：EMA{fast}/{slow}交叉，RSI低于{oversold}，成交量{multi}倍放量",
            "Create a confluence strategy: EMA crossover + RSI + volume, pair={pair}",
            "做一个多指标确认的策略，{pair}，EMA快{fast}慢{slow}，RSI超卖{oversold}，放量{multi}倍",
        ],
        "dsl": {
            "strategy": {
                "name": "Confluence_EMA_RSI_Vol",
                "market": {
                    "exchange": "binance",
                    "pair": "{pair}",
                    "timeframe": "{timeframe}",
                },
                "indicators": [
                    {"name": "ema_fast", "type": "EMA", "params": {"period": "{fast}", "field": "close"}},
                    {"name": "ema_slow", "type": "EMA", "params": {"period": "{slow}", "field": "close"}},
                    {"name": "rsi", "type": "RSI", "params": {"period": 14}},
                    {"name": "vol_ma", "type": "SMA", "params": {"period": 20, "field": "volume"}},
                    {"name": "atr", "type": "ATR", "params": {"period": 14}},
                ],
                "entry": {
                    "long": "ema_fast > ema_slow AND rsi < {oversold} AND volume > vol_ma * {multi}",
                    "short": None,
                },
                "exit": {
                    "long": "ema_fast < ema_slow OR rsi > 70",
                    "short": None,
                },
                "risk": {
                    "stop_loss": -0.03,
                    "trailing_stop": True,
                    "trailing_stop_positive": 0.02,
                    "max_open_trades": 2,
                    "stake_amount": 0.1,
                },
            }
        },
    },
]

# Parameter ranges for template expansion
PARAM_RANGES = {
    "fast": [5, 7, 9, 10, 12, 15, 20],
    "slow": [20, 21, 26, 30, 50, 55, 60, 100],
    "oversold": [25, 28, 30, 35],
    "overbought": [65, 70, 72, 75, 80],
    "period": [14, 20, 21, 26, 50],
    "std": [1.5, 2.0, 2.5, 3.0],
    "multi": [1.2, 1.5, 1.8, 2.0, 2.5],
    "signal": [5, 9, 12],
    "pair": ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT"],
    "timeframe": ["15m", "1h", "4h", "1d"],
}


def generate_dsl_pairs(
    total_pairs: int = 2000,
    output_path: str | None = None,
) -> str:
    """Generate NL→DSL instruction pairs.

    Args:
        total_pairs: Total number of pairs to generate.
        output_path: Custom output path.

    Returns:
        Path to the output JSONL file.
    """
    random.seed(42)
    pairs: list[dict] = []

    for _ in range(total_pairs):
        template = random.choice(STRATEGY_TEMPLATES)
        params = {k: random.choice(v) for k, v in PARAM_RANGES.items()}

        # Ensure fast < slow
        if params["fast"] >= params["slow"]:
            params["slow"] = params["fast"] + random.choice([10, 15, 30])

        # Pick a natural language pattern
        nl_pattern = random.choice(template["nl_patterns"])
        nl_text = nl_pattern.format(**params)

        # Format the DSL
        dsl_str = _format_dsl(template["dsl"], params)

        # Create instruction pair in ChatML format
        pairs.append({
            "instruction": (
                "You are a crypto trading strategy expert. "
                "Convert the following natural language strategy description "
                "into a YAML strategy DSL specification.\n\n"
                "Think step by step: identify the strategy type, select indicators, "
                "design entry/exit logic, and set appropriate risk parameters. "
                "Then output ONLY the final YAML.\n\n"
                f"Strategy description: {nl_text}"
            ),
            "input": "",
            "output": _build_cot_output(template, params, dsl_str),
            "source": "dsl-pairs",
        })

    output = output_path or str(OUTPUT_DIR / "dsl_pairs.jsonl")
    with open(output, "w") as f:
        for item in pairs:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"[DSL Pairs] Generated {len(pairs)} samples → {output}")
    return output


def _format_dsl(dsl_template: dict, params: dict) -> str:
    """Recursively format a DSL template with parameters."""
    import yaml

    formatted = _recursive_format(dsl_template, params)
    return yaml.dump(formatted, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _build_cot_output(template: dict, params: dict, dsl_str: str) -> str:
    """Build a Chain-of-Thought output with reasoning trace before final YAML."""
    template_idx = STRATEGY_TEMPLATES.index(template)
    strategy_types = [
        "trend following (MA crossover)", "mean reversion (RSI oversold)",
        "mean reversion (Bollinger Bands)", "breakout (volume confirmed)",
        "momentum (MACD crossover)", "multi-indicator confluence",
    ]
    strat_type = strategy_types[template_idx]
    stop_loss = -0.03
    if "stop_loss" in dsl_str:
        import re
        m = re.search(r"stop_loss:\s*(-?[\d.]+)", dsl_str)
        if m:
            stop_loss = float(m.group(1))

    reasoning = (
        f"Step 1: Strategy type — {strat_type}\n"
        f"Step 2: Indicators selected based on the described pattern\n"
        f"Step 3: Entry condition captures the core signal\n"
        f"Step 4: Exit condition reverses or complements entry\n"
        f"Step 5: Stop-loss set to {abs(stop_loss)*100:.0f}% based on strategy volatility\n"
        f"Step 6: Validation — stop_loss is negative, names are snake_case\n\n"
    )
    return reasoning + dsl_str


def _recursive_format(obj, params: dict):
    """Recursively format string values in nested structures."""
    if isinstance(obj, str):
        return obj.format(**params) if "{" in obj else obj
    elif isinstance(obj, dict):
        return {k: _recursive_format(v, params) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_recursive_format(item, params) for item in obj]
    elif obj is None:
        return None
    else:
        return obj


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate NL→DSL instruction pairs")
    parser.add_argument("--total", type=int, default=2000)
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    generate_dsl_pairs(total_pairs=args.total, output_path=args.output)
