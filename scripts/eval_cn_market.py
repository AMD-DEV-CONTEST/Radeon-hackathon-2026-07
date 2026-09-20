"""Evaluate the AMD-served QLoRA model on domestic ETF strategy requests.

This is intentionally independent of the legacy crypto-oriented JSON Schema.
It measures whether the model can follow a domestic-market contract before we
change the production DSL and decide whether incremental QLoRA is necessary.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import httpx
import yaml


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

SYSTEM_PROMPT = """你是部署在 AMD ROCm GPU 上的中国市场策略 DSL 生成模型。
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


def evaluate_case(case: dict, raw: str) -> dict:
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vllm-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model", default="models/qwen-trader-merged")
    parser.add_argument("--output", default="/persistent/cn_market_eval.json")
    args = parser.parse_args()

    cases = build_cases()
    results: list[dict] = []
    with httpx.Client(timeout=120.0) as client:
        for index, case in enumerate(cases, 1):
            started = time.perf_counter()
            response = client.post(
                f"{args.vllm_url}/chat/completions",
                json={
                    "model": args.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": case["prompt"]},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 900,
                },
            )
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"]
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            assessment = evaluate_case(case, raw)
            results.append({
                "id": index,
                **case,
                "latency_ms": latency_ms,
                "raw_output": raw,
                **assessment,
            })
            print(f"[{index:02d}/{len(cases)}] {'PASS' if assessment['passed'] else 'FAIL'} {latency_ms:.0f}ms {case['instrument']}", flush=True)

    check_names = list(results[0]["checks"])
    summary = {
        "model": args.model,
        "total": len(results),
        "passed": sum(item["passed"] for item in results),
        "pass_rate": round(sum(item["passed"] for item in results) / len(results), 4),
        "avg_latency_ms": round(statistics.mean(item["latency_ms"] for item in results), 2),
        "p95_latency_ms": round(sorted(item["latency_ms"] for item in results)[int(len(results) * 0.95) - 1], 2),
        "check_rates": {
            name: round(sum(item["checks"][name] for item in results) / len(results), 4)
            for name in check_names
        },
    }
    payload = {"summary": summary, "results": results}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
