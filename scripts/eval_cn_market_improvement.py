"""Independent evaluation script for CN market DSL pass-rate improvement.

Runs three comparison experiments:
  A: current prompt + current evaluator (baseline re-run)
  B: prompt v2 + current evaluator
  C: prompt v2 + experimental canonicalizer

Uses the SAME 24 test cases, same random seed, same vLLM endpoint.
Does NOT restart or modify vLLM. Does NOT touch production files.

Usage:
  python3 eval_cn_market_improvement.py \
    --vllm-url http://127.0.0.1:8000/v1 \
    --model models/qwen-trader-merged \
    --output-dir /persistent/track2/eval/improvement_exp
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

import httpx
import yaml

# --- Import experimental canonicalizer ---
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.dsl.canonicalizer_cn_experiment import process_raw_output

# =============================================================================
# Test cases (identical to eval_cn_market.py)
# =============================================================================

INSTRUMENTS = [
    ("510300.SH", "沪深300ETF"),
    ("510050.SH", "上证50ETF"),
    ("510500.SH", "中证500ETF"),
    ("159915.SZ", "创业板ETF"),
]

TEMPLATES = [
    ("请为{label}设计日线EMA20/EMA50趋势策略，最大仓位30%，止损5%", "1d", [20, 50]),
    ("生成{label}的30分钟RSI均值回归策略，RSI低于30入场、高于70退出，禁止做空", "30m", [14]),
    ("为{label}生成日线布林带反转策略，周期20，标准差2，单次仓位20%", "1d", [20]),
    ("设计{label}的日线MACD趋势策略，参数12、26、9，回撤超过15%停止模拟", "1d", [12, 26, 9]),
    ("生成{label}的30分钟EMA9/EMA21策略，必须遵守T+1、100股整数手和10%涨跌停", "30m", [9, 21]),
    ("为{label}设计ADX过滤的日线EMA策略，仅ADX大于25时入场，不能融券做空", "1d", [14, 20, 50]),
]

FORBIDDEN_TERMS = (
    "btc", "eth", "usdt", "binance", "okx", "bybit", "kraken", "crypto",
    "比特币", "以太坊", "币安", "合约交易",
)

# =============================================================================
# Prompts
# =============================================================================

# Current prompt (from eval_cn_market.py — unchanged)
CURRENT_SYSTEM_PROMPT = """你是部署在 AMD ROCm GPU 上的中国市场策略 DSL 生成模型。
把用户需求转换为合法 JSON，只输出 JSON，不要 Markdown 或解释。
禁止输出任何加密货币、数字货币交易所、合约或永续内容。
用户给出的证券代码和周期具有最高优先级。
顶层必须是 strategy，结构如下：
{
  "strategy": {
    "name": "StrategyName",
    "market": {
      "exchange": "cn_stock",
      "instrument": "510300.SH",
      "timeframe": "1d"
    },
    "indicators": [
      {"name": "ema_fast", "type": "EMA", "params": {"period": 20, "field": "close"}}
    ],
    "entry": {"long": "condition", "short": null},
    "exit": {"long": "condition", "short": null},
    "risk": {"stop_loss": -0.05, "max_position_pct": 0.3, "max_drawdown": 0.15},
    "constraints": {"t_plus_one": true, "price_limit": 0.1, "allow_short": false, "lot_size": 100}
  }
}
period 和 lot_size 必须是整数；风险比例必须是数字；allow_short 必须为 false。
"""

# Prompt v2 is loaded from file
def load_prompt_v2(prompts_dir: Path) -> str:
    prompt_file = prompts_dir / "cn_market_dsl_prompt_v2.txt"
    return prompt_file.read_text(encoding="utf-8")


# =============================================================================
# Evaluation logic
# =============================================================================

def build_cases() -> list[dict]:
    cases: list[dict] = []
    for instrument, label in INSTRUMENTS:
        for template, timeframe, periods in TEMPLATES:
            cases.append({
                "prompt": template.format(label=f"{label}（{instrument}）"),
                "instrument": instrument,
                "timeframe": timeframe,
                "periods": periods,
            })
    return cases


def extract_json(text: str) -> dict | None:
    """Original extract_json from eval_cn_market.py (for experiments A and B)."""
    cleaned = text.strip().removeprefix("```json").removeprefix("```yaml").removesuffix("```").strip()
    try:
        value = yaml.safe_load(cleaned)
        if isinstance(value, dict):
            return value
    except yaml.YAMLError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def evaluate_case_original(case: dict, raw: str) -> dict:
    """Original evaluator (experiments A and B)."""
    lower = raw.lower()
    parsed = extract_json(raw)
    checks = {
        "json_valid": parsed is not None,
        "no_forbidden_terms": not any(term in lower for term in FORBIDDEN_TERMS),
        "instrument_match": False,
        "timeframe_match": False,
        "domestic_exchange": False,
        "short_disabled": False,
        "constraints_valid": False,
        "numeric_types_valid": False,
    }
    if parsed:
        strategy = parsed.get("strategy", {})
        market = strategy.get("market", {})
        constraints = strategy.get("constraints", {})
        risk = strategy.get("risk", {})
        checks["instrument_match"] = market.get("instrument") == case["instrument"]
        checks["timeframe_match"] = market.get("timeframe") == case["timeframe"]
        checks["domestic_exchange"] = market.get("exchange") == "cn_stock"
        checks["short_disabled"] = (
            strategy.get("entry", {}).get("short") is None
            and constraints.get("allow_short") is False
        )
        checks["constraints_valid"] = (
            constraints.get("t_plus_one") is True
            and constraints.get("lot_size") == 100
            and isinstance(constraints.get("price_limit"), (int, float))
        )
        periods = [
            item.get("params", {}).get("period")
            for item in strategy.get("indicators", [])
            if "period" in item.get("params", {})
        ]
        checks["numeric_types_valid"] = (
            all(isinstance(period, int) and not isinstance(period, bool) for period in periods)
            and isinstance(risk.get("stop_loss"), (int, float))
            and not isinstance(risk.get("stop_loss"), bool)
        )
    return {"checks": checks, "passed": all(checks.values())}


def evaluate_case_canonicalized(case: dict, raw: str) -> dict:
    """Evaluator with experimental canonicalizer (experiment C).

    Records: raw model pass, canonicalized pass, and final pass.
    """
    # Step 1: Check raw model output (same as original evaluator)
    raw_eval = evaluate_case_original(case, raw)
    raw_passed = raw_eval["passed"]

    # Step 2: Run through experimental canonicalizer
    result = process_raw_output(
        raw,
        expected_instrument=case["instrument"],
        expected_timeframe=case["timeframe"],
    )
    canon_parsed = result["canonicalized"]
    canon_repairs = result["canon_repairs"] + result.get("extract_repairs", [])
    canon_errors = result["errors"]
    parse_success = result["parse_success"]

    # Step 3: Evaluate canonicalized output
    canon_checks = {
        "json_valid": canon_parsed is not None,
        "no_forbidden_terms": not any(term in raw.lower() for term in FORBIDDEN_TERMS),
        "instrument_match": False,
        "timeframe_match": False,
        "domestic_exchange": False,
        "short_disabled": False,
        "constraints_valid": False,
        "numeric_types_valid": False,
    }

    if canon_parsed:
        strategy = canon_parsed.get("strategy", {})
        market = strategy.get("market", {})
        constraints = strategy.get("constraints", {})
        risk = strategy.get("risk", {})

        canon_checks["instrument_match"] = market.get("instrument") == case["instrument"]
        canon_checks["timeframe_match"] = market.get("timeframe") == case["timeframe"]
        canon_checks["domestic_exchange"] = market.get("exchange") == "cn_stock"
        canon_checks["short_disabled"] = (
            strategy.get("entry", {}).get("short") is None
            and constraints.get("allow_short") is False
        )
        canon_checks["constraints_valid"] = (
            constraints.get("t_plus_one") is True
            and constraints.get("lot_size") == 100
            and isinstance(constraints.get("price_limit"), (int, float))
        )
        periods = [
            item.get("params", {}).get("period")
            for item in strategy.get("indicators", [])
            if "period" in item.get("params", {})
        ]
        canon_checks["numeric_types_valid"] = (
            all(isinstance(p, int) and not isinstance(p, bool) for p in periods)
            and isinstance(risk.get("stop_loss"), (int, float))
            and not isinstance(risk.get("stop_loss"), bool)
        )

    canon_passed = all(canon_checks.values())

    return {
        "checks": canon_checks,
        "passed": canon_passed,
        "raw_passed": raw_passed,
        "canon_passed": canon_passed,
        "parse_success": parse_success,
        "repair_count": len(canon_repairs),
        "repairs": canon_repairs[:10],
        "errors": canon_errors,
    }


def call_vllm(client: httpx.Client, vllm_url: str, model: str,
              system_prompt: str, user_prompt: str) -> tuple[str, float]:
    """Call vLLM and return (raw_output, latency_ms)."""
    started = time.perf_counter()
    response = client.post(
        f"{vllm_url}/chat/completions",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 900,
            "seed": 42,
        },
    )
    response.raise_for_status()
    raw = response.json()["choices"][0]["message"]["content"]
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    return raw, latency_ms


def run_experiment(
    client: httpx.Client,
    vllm_url: str,
    model: str,
    system_prompt: str,
    cases: list[dict],
    experiment_name: str,
    use_canonicalizer: bool = False,
) -> list[dict]:
    """Run a single experiment over all cases."""
    results: list[dict] = []
    for index, case in enumerate(cases, 1):
        raw, latency_ms = call_vllm(client, vllm_url, model, system_prompt, case["prompt"])

        if use_canonicalizer:
            assessment = evaluate_case_canonicalized(case, raw)
        else:
            assessment = evaluate_case_original(case, raw)

        results.append({
            "id": index,
            **case,
            "latency_ms": latency_ms,
            "raw_output": raw[:500],
            **assessment,
        })
        status = "PASS" if assessment["passed"] else "FAIL"
        raw_status = ""
        if use_canonicalizer:
            raw_status = f" (raw={'P' if assessment.get('raw_passed') else 'F'})"
        print(f"  [{experiment_name}] [{index:02d}/{len(cases)}] {status}{raw_status} {latency_ms:.0f}ms {case['instrument']}", flush=True)

    return results


def compute_summary(results: list[dict], experiment_name: str, use_canonicalizer: bool) -> dict:
    total = len(results)
    passed = sum(r["passed"] for r in results)
    check_names = list(results[0]["checks"].keys())

    summary = {
        "experiment": experiment_name,
        "total": total,
        "passed": passed,
        "pass_rate": round(passed / total, 4),
        "avg_latency_ms": round(statistics.mean(r["latency_ms"] for r in results), 2),
        "p95_latency_ms": round(sorted(r["latency_ms"] for r in results)[int(total * 0.95) - 1], 2),
        "check_rates": {
            name: round(sum(r["checks"][name] for r in results) / total, 4)
            for name in check_names
        },
    }

    if use_canonicalizer:
        raw_passed = sum(r.get("raw_passed", False) for r in results)
        canon_passed = sum(r.get("canon_passed", False) for r in results)
        parse_success = sum(r.get("parse_success", False) for r in results)
        summary["raw_pass_rate"] = round(raw_passed / total, 4)
        summary["canon_pass_rate"] = round(canon_passed / total, 4)
        summary["parse_rate"] = round(parse_success / total, 4)
        summary["raw_vs_canon_delta"] = round((canon_passed - raw_passed) / total, 4)

    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vllm-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model", default="models/qwen-trader-merged")
    parser.add_argument("--output-dir", default="/persistent/track2/eval/improvement_exp")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    prompts_dir = Path(__file__).resolve().parent.parent / "src" / "prompts"
    prompt_v2 = load_prompt_v2(prompts_dir)

    cases = build_cases()
    print(f"Total test cases: {len(cases)}", flush=True)
    print(f"vLLM URL: {args.vllm_url}", flush=True)
    print(f"Model: {args.model}", flush=True)
    print(f"Output dir: {output_dir}", flush=True)
    print("=" * 60, flush=True)

    all_summaries = {}
    all_results = {}

    with httpx.Client(timeout=180.0) as client:
        # --- Experiment A: current prompt + original evaluator ---
        print("\n[Experiment A] Current prompt + current evaluator", flush=True)
        results_a = run_experiment(
            client, args.vllm_url, args.model,
            CURRENT_SYSTEM_PROMPT, cases, "A", use_canonicalizer=False
        )
        summary_a = compute_summary(results_a, "A_current_prompt_current_eval", False)
        all_summaries["A"] = summary_a
        all_results["A"] = results_a
        print(json.dumps(summary_a, ensure_ascii=False, indent=2), flush=True)

        # --- Experiment B: prompt v2 + original evaluator ---
        print("\n[Experiment B] Prompt v2 + current evaluator", flush=True)
        results_b = run_experiment(
            client, args.vllm_url, args.model,
            prompt_v2, cases, "B", use_canonicalizer=False
        )
        summary_b = compute_summary(results_b, "B_prompt_v2_current_eval", False)
        all_summaries["B"] = summary_b
        all_results["B"] = results_b
        print(json.dumps(summary_b, ensure_ascii=False, indent=2), flush=True)

        # --- Experiment C: prompt v2 + experimental canonicalizer ---
        print("\n[Experiment C] Prompt v2 + experimental canonicalizer", flush=True)
        results_c = run_experiment(
            client, args.vllm_url, args.model,
            prompt_v2, cases, "C", use_canonicalizer=True
        )
        summary_c = compute_summary(results_c, "C_prompt_v2_canonicalizer", True)
        all_summaries["C"] = summary_c
        all_results["C"] = results_c
        print(json.dumps(summary_c, ensure_ascii=False, indent=2), flush=True)

    # --- Save comparison.json ---
    comparison = {
        "baseline": {
            "source": "cn_market_eval_after.json",
            "total": 24,
            "passed": 11,
            "pass_rate": 0.4583,
            "check_rates": {
                "json_valid": 0.75,
                "no_forbidden_terms": 1.0,
                "instrument_match": 0.7083,
                "timeframe_match": 0.7083,
                "domestic_exchange": 0.7083,
                "short_disabled": 0.7083,
                "constraints_valid": 0.4583,
                "numeric_types_valid": 0.7083,
            },
        },
        "experiments": all_summaries,
    }

    comparison_path = output_dir / "comparison.json"
    comparison_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved comparison to {comparison_path}", flush=True)

    # --- Save detailed results (experiment C) ---
    eval_v2_path = output_dir / "cn_market_eval_v2.json"
    eval_v2_payload = {
        "summary": summary_c,
        "results": results_c,
    }
    eval_v2_path.write_text(json.dumps(eval_v2_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved detailed C results to {eval_v2_path}", flush=True)

    # --- Print final comparison ---
    print("\n" + "=" * 60, flush=True)
    print("FINAL COMPARISON", flush=True)
    print("=" * 60, flush=True)
    print(f"Baseline:  {comparison['baseline']['pass_rate']:.2%} ({comparison['baseline']['passed']}/{comparison['baseline']['total']})", flush=True)
    print(f"Exp A:     {summary_a['pass_rate']:.2%} ({summary_a['passed']}/{summary_a['total']})", flush=True)
    print(f"Exp B:     {summary_b['pass_rate']:.2%} ({summary_b['passed']}/{summary_b['total']})", flush=True)
    print(f"Exp C:     {summary_c['pass_rate']:.2%} ({summary_c['passed']}/{summary_c['total']})", flush=True)
    if "raw_pass_rate" in summary_c:
        print(f"  C raw:   {summary_c['raw_pass_rate']:.2%}", flush=True)
        print(f"  C canon: {summary_c['canon_pass_rate']:.2%}", flush=True)


if __name__ == "__main__":
    main()
