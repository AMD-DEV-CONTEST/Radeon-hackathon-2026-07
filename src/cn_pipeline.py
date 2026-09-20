"""Domestic-market prompt and safe DSL post-processing entry point."""

from __future__ import annotations

from pathlib import Path

from .dsl.canonicalizer_cn_experiment import process_raw_output


_ROOT = Path(__file__).resolve().parent
CN_PROMPT_PATH = _ROOT / "prompts" / "cn_market_dsl_prompt_v2.txt"
CN_MARKET_DSL_PROMPT = CN_PROMPT_PATH.read_text(encoding="utf-8")


def process_cn_model_output(
    raw_output: str,
    instrument: str | None = None,
    timeframe: str | None = None,
) -> dict:
    """Parse and safely canonicalize a domestic-market model response."""
    return process_raw_output(
        raw_output,
        expected_instrument=instrument,
        expected_timeframe=timeframe,
    )
