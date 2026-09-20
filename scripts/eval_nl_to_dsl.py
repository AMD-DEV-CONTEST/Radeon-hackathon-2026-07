"""NL → DSL Generation Quality Evaluation Script.

Tests the fine-tuned LLM's ability to generate valid strategy DSL
from natural language input. Runs with or without a live vLLM server.

Usage:
    # Online mode (requires vLLM running at localhost:8000)
    python scripts/eval_nl_to_dsl.py --vllm-url http://localhost:8000/v1

    # Offline mode (uses curated expected outputs for pipeline validation)
    python scripts/eval_nl_to_dsl.py --offline

Metrics reported:
    - DSL extraction rate (did we get valid YAML?)
    - Schema validation rate (does it pass JSON Schema?)
    - Semantic validation rate (are indicators/expressions valid?)
    - Transpilation rate (can it convert to Freqtrade + Backtrader?)
    - Per-test-case pass/fail with error details
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml


# --- Test prompts ---

TEST_PROMPTS: list[dict] = [
    {
        "id": "ema_cross",
        "nl": "BTC EMA20上穿EMA50时做多，下穿时平仓，止损3%",
        "expected_indicators": {"ema_fast", "ema_slow"},
        "expected_name_pattern": r"EMA|Cross|Trend",
        "category": "trend_following",
    },
    {
        "id": "rsi_oversold",
        "nl": "RSI超卖反弹策略，BTC/USDT 1小时线，RSI低于30买入，高于70卖出",
        "expected_indicators": {"rsi"},
        "expected_name_pattern": r"RSI|Mean|Reversion",
        "category": "mean_reversion",
    },
    {
        "id": "bb_bounce",
        "nl": "布林带策略，ETH/USDT，价格触及下轨买入，上轨卖出，止损3%",
        "expected_indicators": {"bb"},
        "expected_name_pattern": r"BB|Bollinger|Bounce",
        "category": "mean_reversion",
    },
    {
        "id": "macd_cross",
        "nl": "MACD金叉策略，BTC/USDT 4小时线，MACD大于0买入，小于0卖出，止损5%",
        "expected_indicators": {"macd"},
        "expected_name_pattern": r"MACD|Momentum",
        "category": "momentum",
    },
    {
        "id": "volume_breakout",
        "nl": "放量突破策略，EMA20金叉EMA50且成交量大于均量1.5倍确认，止损3%",
        "expected_indicators": {"ema_fast", "ema_slow", "vol_ma"},
        "expected_name_pattern": r"Volume|Breakout|Break",
        "category": "breakout",
    },
    {
        "id": "multi_confluence",
        "nl": "多指标共振策略：EMA金叉 + RSI低于35 + 放量1.5倍确认",
        "expected_indicators": {"ema_fast", "ema_slow", "rsi", "vol_ma"},
        "expected_name_pattern": r"Confluence|Multi|共振",
        "category": "confluence",
    },
    {
        "id": "short_strategy",
        "nl": "做空策略：EMA死叉且RSI超买时做空，止损4%",
        "expected_indicators": {"ema_fast", "ema_slow", "rsi"},
        "expected_name_pattern": r"Short|Bear|做空",
        "category": "short",
    },
    {
        "id": "atr_volatility",
        "nl": "用ATR指标做止损的EMA趋势策略，BTC/USDT 1h",
        "expected_indicators": {"ema_fast", "ema_slow", "atr"},
        "expected_name_pattern": r"ATR|Volatility|Trend",
        "category": "risk_based",
    },
    {
        "id": "adx_filter",
        "nl": "ADX趋势过滤策略：ADX大于25时EMA金叉才入场",
        "expected_indicators": {"ema_fast", "ema_slow", "adx"},
        "expected_name_pattern": r"ADX|Filter|Trend",
        "category": "filtered",
    },
    {
        "id": "supertrend_simple",
        "nl": "Supertrend策略，BTC/USDT 1h，价格在Supertrend之上做多",
        "expected_indicators": {"supertrend"},
        "expected_name_pattern": r"Super|Trend",
        "category": "trend_following",
    },
]


@dataclass
class TestResult:
    """Result of a single NL→DSL test case."""
    test_id: str
    nl_input: str
    category: str
    raw_output: str = ""
    extracted_dsl: dict | None = None
    schema_valid: bool = False
    semantic_valid: bool = False
    freqtrade_transpile: bool = False
    backtrader_transpile: bool = False
    indicators_match: bool = False
    errors: list[str] = field(default_factory=list)
    repairs: list[str] = field(default_factory=list)
    passed: bool = False


def call_vllm(vllm_url: str, system_prompt: str, user_msg: str, model: str = "qwen-trader-merged") -> str:
    """Call vLLM OpenAI-compatible API."""
    import httpx
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                f"{vllm_url}/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1024,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[VLLM_ERROR] {e}"


def extract_yaml(text: str) -> dict | None:
    """Extract YAML from LLM response (same logic as chat_app.py)."""
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


def validate_dsl(dsl: dict) -> tuple[bool, bool, list[str], list]:
    """Validate DSL with canonicalization — returns (schema_valid, semantic_valid, errors, repairs).

    The dsl dict is replaced in-place with the canonicalized version.
    """
    import copy
    from src.dsl.canonicalizer import canonicalize_dsl
    from src.dsl.validator import validate_dsl as _raw_validate

    # Canonicalize on a copy to avoid mutating dsl before we have the result
    canon_dsl = copy.deepcopy(dsl)
    canon_dsl, repairs, canon_errors = canonicalize_dsl(canon_dsl)

    if canon_errors:
        return False, False, canon_errors, repairs

    # Validate the canonicalized version
    is_valid, errors = _raw_validate(canon_dsl)

    # Replace original dict contents with canonicalized version
    dsl.clear()
    dsl.update(canon_dsl)

    return is_valid, is_valid, errors, repairs


def transpile_check(dsl: dict) -> tuple[bool, bool]:
    """Try transpiling to Freqtrade and Backtrader."""
    import ast
    from src.dsl.transpiler import transpile_to_freqtrade
    from src.dsl.transpiler_backtrader import transpile_to_backtrader

    ft_ok = False
    bt_ok = False
    try:
        ft_code = transpile_to_freqtrade(dsl)
        ast.parse(ft_code)
        ft_ok = True
    except Exception:
        pass
    try:
        bt_code = transpile_to_backtrader(dsl)
        ast.parse(bt_code)
        bt_ok = True
    except Exception:
        pass
    return ft_ok, bt_ok


def run_tests(vllm_url: str | None, offline: bool = False, model: str = "qwen-trader-merged") -> list[TestResult]:
    """Run all NL→DSL test cases."""
    results: list[TestResult] = []

    # Load system prompt
    system_prompt = """You are an expert crypto trading strategist. Convert the user's natural language trading idea into a YAML strategy DSL specification. Output ONLY valid YAML, no explanations."""

    for tc in TEST_PROMPTS:
        result = TestResult(
            test_id=tc["id"],
            nl_input=tc["nl"],
            category=tc["category"],
        )

        if offline:
            result.raw_output = "[OFFLINE MODE — skipped LLM call]"
            result.errors.append("Offline mode: LLM not called")
            results.append(result)
            continue

        if vllm_url is None:
            result.raw_output = "[NO VLLM URL]"
            result.errors.append("No vLLM URL provided")
            results.append(result)
            continue

        # Call LLM
        result.raw_output = call_vllm(vllm_url, system_prompt, tc["nl"], model=model)

        if result.raw_output.startswith("[VLLM_ERROR]") or result.raw_output.startswith("[LLM Error]"):
            result.errors.append(result.raw_output)
            results.append(result)
            continue

        # Extract YAML
        result.extracted_dsl = extract_yaml(result.raw_output)
        if result.extracted_dsl is None:
            result.errors.append("Failed to extract YAML from LLM output")
            results.append(result)
            continue

        # Validate with canonicalization
        schema_ok, semantic_ok, errors, repairs = validate_dsl(result.extracted_dsl)

        # Check for unrecoverable errors → retry once
        unrecoverable_keywords = ("cannot parse", "Missing 'indicators'", "expression", "Missing 'strategy'")
        has_unrecoverable = any(any(kw in e for kw in unrecoverable_keywords) for e in errors)

        if has_unrecoverable and not schema_ok:
            log_msg = f"Unrecoverable errors on first attempt, retrying: {errors[:2]}"
            retry_prompt = (
                f"{tc['nl']}\n\n"
                f"Your previous output had these errors:\n"
                + "\n".join(f"- {e}" for e in errors[:3])
                + "\n\nPlease fix and output ONLY valid YAML. "
                "stop_loss must be a negative number (e.g. -0.03). "
                "indicators must be a non-empty list. "
                "entry/exit must only have 'long' and 'short' keys."
            )
            result.raw_output = call_vllm(vllm_url, system_prompt, retry_prompt, model=model)
            result.extracted_dsl = extract_yaml(result.raw_output)
            if result.extracted_dsl is not None:
                # Re-validate the retry output
                schema_ok, semantic_ok, errors, retry_repairs = validate_dsl(result.extracted_dsl)
                repairs.extend(retry_repairs)
                result.repairs.append(f"[RETRY] Attempted retry after unrecoverable errors")
            else:
                result.errors.append("Retry: Failed to extract YAML")
                results.append(result)
                continue

        result.schema_valid = schema_ok
        result.semantic_valid = semantic_ok
        if errors:
            result.errors.extend(errors)
        if repairs:
            result.repairs.extend([f"{r.field}: {r.raw} → {r.normalized} ({r.repair_type})" for r in repairs])

        # Transpile
        ft_ok, bt_ok = transpile_check(result.extracted_dsl)
        result.freqtrade_transpile = ft_ok
        result.backtrader_transpile = bt_ok

        # Check indicators
        if result.extracted_dsl and "strategy" in result.extracted_dsl:
            strategy = result.extracted_dsl["strategy"]
            actual_inds = {i["name"] for i in strategy.get("indicators", [])} if isinstance(strategy.get("indicators"), list) else set()
            expected = tc.get("expected_indicators", set())
            # Check if expected indicators are a subset (LLM may add extra)
            result.indicators_match = expected.issubset(actual_inds)
            if not result.indicators_match:
                missing = expected - actual_inds
                result.errors.append(f"Missing expected indicators: {missing}")

        # Overall pass
        result.passed = (
            result.extracted_dsl is not None
            and result.schema_valid
            and result.semantic_valid
            and result.freqtrade_transpile
            and result.backtrader_transpile
            and result.indicators_match
        )

        results.append(result)

    return results


def print_report(results: list[TestResult]) -> None:
    """Print evaluation report."""
    total = len(results)
    online_results = [r for r in results if not r.raw_output.startswith("[")]
    offline_skipped = total - len(online_results)

    print("=" * 70)
    print("  NL → DSL Generation Quality Evaluation")
    print("=" * 70)
    print()

    if offline_skipped == total:
        print(f"  ⚠️  OFFLINE MODE — {total} test cases defined, none executed")
        print("  Run with --vllm-url http://localhost:8000/v1 to execute tests")
        print()
        print("  Test cases cover:")
        for tc in TEST_PROMPTS:
            print(f"    • [{tc['category']}] {tc['id']}: {tc['nl'][:60]}...")
        print()
        return

    n = len(online_results)
    extracted = sum(1 for r in online_results if r.extracted_dsl is not None)
    schema_ok = sum(1 for r in online_results if r.schema_valid)
    semantic_ok = sum(1 for r in online_results if r.semantic_valid)
    ft_ok = sum(1 for r in online_results if r.freqtrade_transpile)
    bt_ok = sum(1 for r in online_results if r.backtrader_transpile)
    ind_match = sum(1 for r in online_results if r.indicators_match)
    passed = sum(1 for r in online_results if r.passed)

    print(f"  Tests executed:    {n}")
    print(f"  YAML extracted:    {extracted}/{n} ({extracted/n*100:.0f}%)")
    print(f"  Schema valid:      {schema_ok}/{n} ({schema_ok/n*100:.0f}%)")
    print(f"  Semantic valid:    {semantic_ok}/{n} ({semantic_ok/n*100:.0f}%)")
    print(f"  Freqtrade OK:      {ft_ok}/{n} ({ft_ok/n*100:.0f}%)")
    print(f"  Backtrader OK:     {bt_ok}/{n} ({bt_ok/n*100:.0f}%)")
    print(f"  Indicators match:  {ind_match}/{n} ({ind_match/n*100:.0f}%)")
    print(f"  ────────────────────────────────")
    print(f"  OVERALL PASS RATE: {passed}/{n} ({passed/n*100:.0f}%)")
    print()

    # Per-test details
    print("  Per-test results:")
    print("  " + "-" * 66)
    for r in online_results:
        status = "✅ PASS" if r.passed else "❌ FAIL"
        print(f"  {status} [{r.category}] {r.test_id}")
        if r.repairs:
            for rep in r.repairs[:3]:
                print(f"         🔧 {rep[:80]}")
        if r.errors:
            for err in r.errors[:3]:
                print(f"         → {err[:80]}")
    print()

    # Category breakdown
    categories: dict[str, list[bool]] = {}
    for r in online_results:
        categories.setdefault(r.category, []).append(r.passed)
    print("  By category:")
    for cat, passes in sorted(categories.items()):
        n_cat = len(passes)
        p_cat = sum(passes)
        print(f"    {cat:20s}: {p_cat}/{n_cat}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NL→DSL Generation Quality Evaluation")
    parser.add_argument("--vllm-url", type=str, default=None, help="vLLM API URL (e.g. http://localhost:8000/v1)")
    parser.add_argument("--offline", action="store_true", help="Offline mode (list test cases only)")
    parser.add_argument("--model", type=str, default="qwen-trader-merged", help="Model name in vLLM")
    args = parser.parse_args()

    if args.offline:
        results = run_tests(None, offline=True, model=args.model)
    elif args.vllm_url:
        results = run_tests(args.vllm_url, offline=False, model=args.model)
    else:
        print("Usage: python eval_nl_to_dsl.py --vllm-url http://localhost:8000/v1")
        print("       python eval_nl_to_dsl.py --offline")
        sys.exit(1)

    print_report(results)
