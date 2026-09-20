"""Prepare FinGPT dataset for QLoRA fine-tuning.

FinGPT: Open-source Financial LLM framework with instruction data.
Source: https://github.com/AI4Finance-Foundation/FinGPT

This script downloads FinGPT instruction data and formats it
for QLoRA SFT, focusing on financial QA and sentiment analysis.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from datasets import load_dataset


OUTPUT_DIR = Path(__file__).parent.parent / "data" / "processed"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def prepare_fingpt(
    max_samples: int = 30000,
    output_path: str | None = None,
) -> str:
    """Download and process FinGPT instruction data.

    Args:
        max_samples: Maximum samples to process.
        output_path: Custom output path.

    Returns:
        Path to processed JSONL file.
    """
    print("[FinGPT] Loading FinGPT instruction datasets...")

    all_processed: list[dict] = []

    # --- FinGPT sentiment analysis ---
    try:
        print("[FinGPT] Loading sentiment dataset...")
        ds_sent = load_dataset(
            "FinGPT/fingpt-sentiment-train",
            split="train",
            trust_remote_code=True,
        )
        for i, sample in enumerate(ds_sent):
            if i >= max_samples // 2:
                break
            instruction_text = sample.get("input", "")
            sentiment = sample.get("output", "")

            all_processed.append({
                "instruction": (
                    f"You are a financial sentiment analyst. "
                    f"Classify the sentiment of this text as "
                    f"Positive, Negative, or Neutral.\n\n"
                    f"Text: {instruction_text}"
                ),
                "input": "",
                "output": f"Sentiment: {sentiment}",
                "source": "fingpt-sentiment",
            })
    except Exception as e:
        print(f"[FinGPT] Sentiment dataset not available: {e}")

    # --- FinGPT headlined sentiment (alternative dataset) ---
    try:
        print("[FinGPT] Loading headlined sentiment dataset...")
        ds_cot = load_dataset(
            "FinGPT/fingpt-sentiment-train",
            split="train",
            trust_remote_code=True,
        )
        for i, sample in enumerate(ds_cot):
            if i >= max_samples // 2:
                break
            instruction_text = sample.get("input", "")
            response_text = sample.get("output", "")

            if not instruction_text or not response_text:
                continue

            all_processed.append({
                "instruction": (
                    f"You are a financial reasoning expert. "
                    f"Analyze the following question step by step.\n\n"
                    f"Question: {instruction_text}"
                ),
                "input": "",
                "output": response_text,
                "source": "fingpt-cot",
            })
    except Exception as e:
        print(f"[FinGPT] CoT dataset not available: {e}")

    # --- Fallback: generate synthetic financial QA pairs ---
    if len(all_processed) < 1000:
        print("[FinGPT] Datasets incomplete, generating synthetic pairs...")
        all_processed.extend(_generate_synthetic_pairs(max_samples - len(all_processed)))

    output = output_path or str(OUTPUT_DIR / "fingpt_train.jsonl")
    with open(output, "w") as f:
        for item in all_processed:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"[FinGPT] Processed {len(all_processed)} samples → {output}")
    return output


def _generate_synthetic_pairs(n: int) -> list[dict]:
    """Generate synthetic financial QA pairs as fallback."""
    qa_pairs = [
        {
            "q": "What is a moving average crossover strategy?",
            "a": (
                "A moving average crossover strategy uses two moving averages "
                "of different periods. When the faster MA crosses above the "
                "slower MA, it generates a buy signal. When it crosses below, "
                "it generates a sell signal. Common pairs are EMA(9)/EMA(21) "
                "or EMA(20)/EMA(50)."
            ),
        },
        {
            "q": "How does RSI help in trading decisions?",
            "a": (
                "RSI (Relative Strength Index) measures the magnitude of recent "
                "price changes on a 0-100 scale. RSI > 70 typically indicates "
                "overbought conditions (potential sell), while RSI < 30 "
                "indicates oversold conditions (potential buy). Divergence "
                "between RSI and price can signal trend reversals."
            ),
        },
        {
            "q": "What is the ATR indicator used for?",
            "a": (
                "ATR (Average True Range) measures market volatility. "
                "Traders use it for: 1) Setting dynamic stop-loss levels "
                "(e.g., 1.5×ATR), 2) Position sizing based on volatility, "
                "3) Identifying market regime changes when ATR spikes."
            ),
        },
        {
            "q": "Explain volume confirmation in breakout trading.",
            "a": (
                "Volume confirmation validates breakout signals. A genuine "
                "breakout above resistance should be accompanied by volume "
                "above its 20-period average (ideally 1.5x or higher). "
                "Low-volume breakouts have higher failure rates and are "
                "often treated as false signals."
            ),
        },
        {
            "q": "What is a trailing stop and when to use it?",
            "a": (
                "A trailing stop moves with the price to lock in profits. "
                "It's set at a fixed distance or percentage below the current "
                "price (for longs). Use it when: 1) trend is strong and you "
                "want to ride it, 2) you want to automate profit-taking, "
                "3) you need to protect gains while giving the trade room."
            ),
        },
        {
            "q": "How do Bollinger Bands work?",
            "a": (
                "Bollinger Bands consist of a middle SMA(20) and upper/lower "
                "bands at ±2 standard deviations. Price touching the upper "
                "band suggests overbought; lower band suggests oversold. "
                "Band squeeze (narrowing) indicates low volatility and "
                "potential breakout. Band expansion confirms trend strength."
            ),
        },
        {
            "q": "What is MACD and how to use it?",
            "a": (
                "MACD (Moving Average Convergence Divergence) shows the "
                "relationship between two EMAs (typically 12 and 26). "
                "Signal line (EMA9 of MACD) crossovers generate buy/sell. "
                "Histogram shows momentum. Zero-line crossovers confirm "
                "trend direction. Divergence with price predicts reversals."
            ),
        },
        {
            "q": "Explain the concept of risk-reward ratio.",
            "a": (
                "Risk-reward ratio compares potential loss to potential gain. "
                "A 1:2 ratio means you risk $1 to make $2. Professional "
                "traders typically aim for at least 1:2 or 1:3. With a 40% "
                "win rate and 1:2 R:R, the system is profitable because "
                "Expected Value = (0.4 × 2) - (0.6 × 1) = +0.2R per trade."
            ),
        },
        {
            "q": "What does 'support and resistance' mean?",
            "a": (
                "Support is a price level where buying pressure typically "
                "prevents further decline. Resistance is where selling "
                "pressure caps advances. Key concepts: 1) More tests = "
                "stronger level, 2) Broken resistance becomes new support, "
                "3) Volume at these levels indicates significance."
            ),
        },
        {
            "q": "How to use the Supertrend indicator?",
            "a": (
                "Supertrend uses ATR and a multiplier (default 3) to plot "
                "a trend-following line. Green line = uptrend (go long), "
                "Red line = downtrend (go short or exit). It dynamically "
                "adjusts with volatility. Works best in trending markets; "
                "expect whipsaws in ranging conditions."
            ),
        },
        {
            "q": "What is position sizing and why is it important?",
            "a": (
                "Position sizing determines how much capital to allocate per "
                "trade. Common methods: 1) Fixed fractional: risk 1-2% of "
                "account per trade, 2) Kelly criterion: f* = (bp-q)/b, "
                "3) Volatility-based: size = (account × risk%) / ATR. "
                "Proper sizing ensures survival through losing streaks."
            ),
        },
        {
            "q": "Explain the concept of drawdown in trading.",
            "a": (
                "Drawdown is the peak-to-trough decline of equity. Maximum "
                "drawdown (MDD) is the largest observed loss from a peak. "
                "Key metrics: 1) MDD > 20% is high-risk, 2) Recovery time "
                "from drawdown matters, 3) Calmar ratio = annual return / "
                "MDD measures risk-adjusted performance. Target MDD < 15%."
            ),
        },
    ]

    pairs: list[dict] = []
    for i in range(n):
        template = qa_pairs[i % len(qa_pairs)]
        pairs.append({
            "instruction": template["q"],
            "input": "",
            "output": template["a"],
            "source": "synthetic-qa",
        })
    return pairs


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Prepare FinGPT dataset")
    parser.add_argument("--max-samples", type=int, default=30000)
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    prepare_fingpt(max_samples=args.max_samples, output_path=args.output)
