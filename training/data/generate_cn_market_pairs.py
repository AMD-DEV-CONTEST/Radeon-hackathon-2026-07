"""Generate deterministic mainland-China stock/ETF NL-to-DSL training pairs."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import yaml


SYSTEM = (
    "你是中国境内证券市场量化策略 DSL 生成器。只输出合法 YAML，不输出解释或 Markdown。"
    "仅支持 A 股、场内 ETF 和指数；遵守 T+1、100 股一手、涨跌停和禁止裸卖空约束。"
    "period 必须为整数，stop_loss 必须为负数。"
)

INSTRUMENTS = [
    ("510300.SH", "沪深300ETF"),
    ("510500.SH", "中证500ETF"),
    ("159915.SZ", "创业板ETF"),
    ("512100.SH", "中证1000ETF"),
    ("000300.SH", "沪深300指数"),
    ("000905.SH", "中证500指数"),
]
TIMEFRAMES = [("1d", "日线"), ("30m", "30分钟")]
FAMILIES = [
    ("ema_cross", "EMA", "EMA", "ema_fast > ema_slow", "ema_fast < ema_slow"),
    ("sma_cross", "SMA", "SMA", "ma_fast > ma_slow", "ma_fast < ma_slow"),
]


def make_sample(rng: random.Random, index: int) -> dict:
    instrument, label = rng.choice(INSTRUMENTS)
    timeframe, timeframe_cn = rng.choice(TIMEFRAMES)
    family, fast_type, slow_type, entry, exit_ = rng.choice(FAMILIES)
    fast, slow = rng.choice([(5, 20), (10, 30), (20, 50), (30, 60)])
    stop_loss = rng.choice([-0.02, -0.03, -0.05, -0.08])
    max_position = rng.choice([0.2, 0.3, 0.5])
    prefix = "ema" if family == "ema_cross" else "ma"
    strategy = {
        "strategy": {
            "name": f"CN_{family}_{fast}_{slow}_{index:04d}",
            "market": {
                "exchange": "cn_stock",
                "instrument": instrument,
                "timeframe": timeframe,
            },
            "indicators": [
                {"name": f"{prefix}_fast", "type": fast_type, "params": {"period": fast, "field": "close"}},
                {"name": f"{prefix}_slow", "type": slow_type, "params": {"period": slow, "field": "close"}},
            ],
            "entry": {"long": entry, "short": None},
            "exit": {"long": exit_, "short": None},
            "constraints": {
                "t_plus_one": True,
                "price_limit": 0.1,
                "allow_short": False,
                "lot_size": 100,
            },
            "risk": {
                "stop_loss": stop_loss,
                "max_position_pct": max_position,
                "max_drawdown": -0.15,
            },
        }
    }
    instruction = (
        f"为{label}（{instrument}）生成{timeframe_cn}{fast}/{slow}{fast_type}金叉策略，"
        f"止损{abs(stop_loss) * 100:.0f}%，单标的仓位不超过{max_position * 100:.0f}%，只返回 DSL YAML。"
    )
    return {
        "system": SYSTEM,
        "instruction": instruction,
        "input": "",
        "output": yaml.safe_dump(strategy, allow_unicode=True, sort_keys=False),
        "source": "cn_market_deterministic_v1",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--count", type=int, default=400)
    parser.add_argument("--seed", type=int, default=20260730)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for i in range(args.count):
            handle.write(json.dumps(make_sample(rng, i), ensure_ascii=False) + "\n")
    print(f"wrote {args.count} samples to {output}")


if __name__ == "__main__":
    main()
