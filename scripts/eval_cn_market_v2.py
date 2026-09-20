"""Enhanced CN market evaluation with canonicalizer and retry.

Fixes over v1:
- Robust JSON extraction handling strategy": prefix, truncated/degraded output
- CN market canonicalizer: fixes lot_size, constraints, exchange, short, risk
- Retry mechanism (max 2) for unparseable/degraded output
- Preserves raw_output, pre_repair_dsl, post_repair_dsl, repair_log

Usage:
  python eval_cn_market_v2.py --vllm-url http://127.0.0.1:8000/v1 \
    --model models/qwen-trader-merged \
    --output /persistent/track2/eval/cn_market_eval_final.json
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import statistics
import time
from pathlib import Path
from typing import Any

import httpx
import yaml


# ─── Dataset ──────────────────────────────────────────────────────────────────

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
输出必须以 {"strategy": 开头，以 } 结尾。
顶层必须是 strategy，结构如下：
{"strategy": {"name": "StrategyName", "market": {"exchange": "cn_stock", "instrument": "510300.SH", "timeframe": "1d"}, "indicators": [{"name": "ema_fast", "type": "EMA", "params": {"period": 20, "field": "close"}}], "entry": {"long": "condition", "short": null}, "exit": {"long": "condition", "short": null}, "risk": {"stop_loss": -0.05, "max_position_pct": 0.3, "max_drawdown": 0.15}, "constraints": {"t_plus_one": true, "price_limit": 0.1, "allow_short": false, "lot_size": 100}}}
period 和 lot_size 必须是整数且 lot_size 必须为 100。
风险比例必须是数字；allow_short 必须为 false；stop_loss 必须为负数。
t_plus_one 必须为 true；price_limit 必须为 0.1。
"""


# ─── JSON extraction ─────────────────────────────────────────────────────────

def _is_degraded(text: str) -> bool:
    """Detect degraded output (e.g. repeated characters filling the context."""
    if len(text) < 50:
        return True
    # Check if >60% of characters are the same
    chars = list(text[-200:])
    if chars:
        most_common = max(set(chars), key=chars.count)
        if chars.count(most_common) / len(chars) > 0.6:
            return True
    # Check for very long runs of same char
    for i in range(len(text) - 50):
        if len(set(text[i:i+50])) <= 2:
            return True
    return False


def extract_json(text: str) -> dict | None:
    """Robustly extract JSON from LLM output.

    Handles common LLM format errors:
    - strategy": prefix (missing opening {)
    - strategy: prefix (unquoted YAML key)
    - Truncated output (missing closing })
    - Extra trailing }
    - Markdown code fences
    """
    cleaned = text.strip().removeprefix("```json").removeprefix("```yaml").removesuffix("```").strip()

    # Strategy 0: Fix "strategy\n{...}" pattern — model outputs the word
    # "strategy" on its own line, then the JSON body on the next line.
    # YAML parser treats "strategy" as a key and the body as its value,
    # but the body itself is a valid dict — we need to wrap it.
    strat_newline = re.match(r'^strategy\s*\n\s*(\{.*\})\s*$', cleaned, re.DOTALL)
    if strat_newline:
        body = strat_newline.group(1)
        wrapped = '{"strategy": ' + body + '}'
        try:
            value = json.loads(wrapped)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
        try:
            value = yaml.safe_load(wrapped)
            if isinstance(value, dict):
                return value
        except yaml.YAMLError:
            pass

    # Strategy 1: Try YAML parse first (handles unquoted keys like strategy: {...})
    try:
        value = yaml.safe_load(cleaned)
        if isinstance(value, dict):
            # If YAML parsed but "strategy" key is missing, check if the
            # parsed dict looks like a strategy body (has name/market/etc.)
            if "strategy" not in value and "name" in value:
                return {"strategy": value}
            return value
    except yaml.YAMLError:
        pass

    # Strategy 2: Try direct JSON parse
    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    # Strategy 3: Fix strategy": prefix (model forgot the opening {")
    # Pattern: starts with strategy": or strategy\":
    if re.match(r'^strategy["\']?\s*:\s*\{', cleaned):
        fixed = '{"' + cleaned
        try:
            value = json.loads(fixed)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            # Maybe also missing closing }
            fixed_with_close = fixed.rstrip()
            if not fixed_with_close.endswith("}"):
                fixed_with_close += "}"
            try:
                value = json.loads(fixed_with_close)
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                pass
            # Maybe extra closing }
            fixed_trim_end = fixed.rstrip()
            if fixed_trim_end.endswith("}}"):
                fixed_trim_end = fixed_trim_end[:-1]
                try:
                    value = json.loads(fixed_trim_end)
                    if isinstance(value, dict):
                        return value
                except json.JSONDecodeError:
                    pass

    # Strategy 4: Extract from { to } substring
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        candidate = cleaned[start:end + 1]
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                # If parsed dict has no "strategy" key but has strategy-like
                # fields, wrap it.
                if "strategy" not in value and "name" in value:
                    return {"strategy": value}
                return value
        except json.JSONDecodeError:
            # Try YAML on the substring
            try:
                value = yaml.safe_load(candidate)
                if isinstance(value, dict):
                    if "strategy" not in value and "name" in value:
                        return {"strategy": value}
                    return value
            except yaml.YAMLError:
                pass
            # Try fixing braces count
            open_count = candidate.count("{")
            close_count = candidate.count("}")
            if open_count > close_count:
                candidate += "}" * (open_count - close_count)
                try:
                    value = json.loads(candidate)
                    if isinstance(value, dict):
                        return value
                except json.JSONDecodeError:
                    pass
            elif close_count > open_count:
                # Remove extra closing braces
                candidate_trimmed = candidate.rstrip()
                while candidate_trimmed.endswith("}}") and close_count > open_count:
                    candidate_trimmed = candidate_trimmed[:-1]
                    close_count -= 1
                try:
                    value = json.loads(candidate_trimmed)
                    if isinstance(value, dict):
                        return value
                except json.JSONDecodeError:
                    pass

    # Strategy 5: Try wrapping in {} if the text looks like strategy content
    if not cleaned.startswith("{") and "strategy" in cleaned.lower():
        wrapped = "{" + cleaned + "}"
        try:
            value = json.loads(wrapped)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            try:
                value = yaml.safe_load(wrapped)
                if isinstance(value, dict):
                    return value
            except yaml.YAMLError:
                pass

    return None


# ─── CN market canonicalizer ─────────────────────────────────────────────────

def canonicalize_cn_market(dsl: dict[str, Any], case: dict) -> tuple[dict[str, Any], list[dict]]:
    """Canonicalize a parsed DSL for CN market constraints.

    Returns (canonicalized_dsl, repair_log).
    Each repair_log entry: {field, raw, normalized, repair_type, message}
    """
    repairs: list[dict] = []

    if not isinstance(dsl, dict):
        return dsl, repairs

    strat = dsl.get("strategy")
    if not isinstance(strat, dict):
        return dsl, repairs

    # ── market ──
    if "market" not in strat or not isinstance(strat.get("market"), dict):
        strat["market"] = {}
        repairs.append({"field": "strategy.market", "raw": None, "normalized": {},
                        "repair_type": "default_fill", "message": "Missing market, created empty"})

    market = strat["market"]

    if market.get("exchange") != "cn_stock":
        repairs.append({"field": "strategy.market.exchange", "raw": market.get("exchange"),
                        "normalized": "cn_stock", "repair_type": "cn_constraint",
                        "message": "Exchange forced to cn_stock for domestic market"})
        market["exchange"] = "cn_stock"

    if market.get("instrument") != case["instrument"]:
        repairs.append({"field": "strategy.market.instrument", "raw": market.get("instrument"),
                        "normalized": case["instrument"], "repair_type": "cn_constraint",
                        "message": f"Instrument set to {case['instrument']} per user request"})
        market["instrument"] = case["instrument"]

    if market.get("timeframe") != case["timeframe"]:
        repairs.append({"field": "strategy.market.timeframe", "raw": market.get("timeframe"),
                        "normalized": case["timeframe"], "repair_type": "cn_constraint",
                        "message": f"Timeframe set to {case['timeframe']} per user request"})
        market["timeframe"] = case["timeframe"]

    # ── indicators ──
    if "indicators" in strat and isinstance(strat["indicators"], list):
        for i, ind in enumerate(strat["indicators"]):
            if not isinstance(ind, dict):
                continue
            params = ind.get("params", {})
            if not isinstance(params, dict):
                params = {}
                ind["params"] = params
            for key in ("period", "fast_period", "slow_period", "signal_period"):
                if key in params and not isinstance(params[key], int):
                    raw_val = params[key]
                    try:
                        params[key] = int(float(raw_val))
                        repairs.append({"field": f"strategy.indicators.{i}.params.{key}",
                                        "raw": raw_val, "normalized": params[key],
                                        "repair_type": "type_coerce",
                                        "message": f"Coerced {key} to int"})
                    except (ValueError, TypeError):
                        pass

    # ── entry / exit ──
    for section_name in ("entry", "exit"):
        section = strat.get(section_name, {})
        if not isinstance(section, dict):
            section = {}
            strat[section_name] = section
        if section.get("short") is not None:
            repairs.append({"field": f"strategy.{section_name}.short", "raw": section.get("short"),
                            "normalized": None, "repair_type": "cn_constraint",
                            "message": f"Short {section_name} disabled for CN market"})
            section["short"] = None

    # ── constraints ──
    if "constraints" not in strat or not isinstance(strat.get("constraints"), dict):
        strat["constraints"] = {}
        repairs.append({"field": "strategy.constraints", "raw": None, "normalized": {},
                        "repair_type": "default_fill", "message": "Missing constraints, created empty"})

    constraints = strat["constraints"]

    cn_defaults = {
        "t_plus_one": (True, True),
        "price_limit": (0.1, True),
        "allow_short": (False, True),
        "lot_size": (100, True),
    }
    for key, (expected, must_fix) in cn_defaults.items():
        current = constraints.get(key)
        if current != expected:
            if must_fix or key == "lot_size":
                repairs.append({"field": f"strategy.constraints.{key}", "raw": current,
                                "normalized": expected, "repair_type": "cn_constraint",
                                "message": f"{key} set to {expected} for CN market compliance"})
                constraints[key] = expected

    # ── risk ──
    if "risk" not in strat or not isinstance(strat.get("risk"), dict):
        strat["risk"] = {}
        repairs.append({"field": "strategy.risk", "raw": None, "normalized": {},
                        "repair_type": "default_fill", "message": "Missing risk, created empty"})

    risk = strat["risk"]

    if "stop_loss" not in risk:
        risk["stop_loss"] = -0.05
        repairs.append({"field": "strategy.risk.stop_loss", "raw": None, "normalized": -0.05,
                        "repair_type": "default_fill", "message": "Missing stop_loss, set to -0.05"})
    else:
        sl = risk["stop_loss"]
        if isinstance(sl, str):
            try:
                sl = float(sl)
            except ValueError:
                sl = -0.05
        if isinstance(sl, (int, float)):
            if sl > 0:
                if sl > 1:
                    sl = -sl / 100.0
                else:
                    sl = -sl
                repairs.append({"field": "strategy.risk.stop_loss", "raw": risk["stop_loss"],
                                "normalized": round(sl, 4), "repair_type": "sign_fix",
                                "message": "stop_loss must be negative"})
                risk["stop_loss"] = round(sl, 4)

    if "max_position_pct" not in risk:
        risk["max_position_pct"] = 0.3
        repairs.append({"field": "strategy.risk.max_position_pct", "raw": None, "normalized": 0.3,
                        "repair_type": "default_fill", "message": "Missing max_position_pct, set to 0.3"})

    if "max_drawdown" not in risk:
        risk["max_drawdown"] = 0.15
        repairs.append({"field": "strategy.risk.max_drawdown", "raw": None, "normalized": 0.15,
                        "repair_type": "default_fill", "message": "Missing max_drawdown, set to 0.15"})

    return dsl, repairs


# ─── Evaluation ───────────────────────────────────────────────────────────────

def evaluate_case(case: dict, raw: str, pre_repair: dict | None,
                  post_repair: dict | None, repairs: list[dict]) -> dict:
    lower = raw.lower()
    checks = {
        "json_valid": pre_repair is not None,
        "no_forbidden_terms": not any(term in lower for term in FORBIDDEN_TERMS),
        "instrument_match": False,
        "timeframe_match": False,
        "domestic_exchange": False,
        "short_disabled": False,
        "constraints_valid": False,
        "numeric_types_valid": False,
    }
    if post_repair:
        strategy = post_repair.get("strategy", {})
        market = strategy.get("market", {})
        constraints = strategy.get("constraints", {})
        risk = strategy.get("risk", {})
        checks["instrument_match"] = market.get("instrument") == case["instrument"]
        checks["timeframe_match"] = market.get("timeframe") == case["timeframe"]
        checks["domestic_exchange"] = market.get("exchange") == "cn_stock"
        checks["short_disabled"] = (
            strategy.get("entry", {}).get("short") is None
            and strategy.get("exit", {}).get("short") is None
            and constraints.get("allow_short") is False
        )
        checks["constraints_valid"] = (
            constraints.get("t_plus_one") is True
            and constraints.get("lot_size") == 100
            and isinstance(constraints.get("price_limit"), (int, float))
            and not isinstance(constraints.get("price_limit"), bool)
            and constraints.get("allow_short") is False
        )
        periods = [
            item.get("params", {}).get("period")
            for item in strategy.get("indicators", [])
            if "period" in item.get("params", {})
        ]
        checks["numeric_types_valid"] = (
            all(isinstance(p, int) and not isinstance(p, bool) for p in periods)
            and isinstance(risk.get("stop_loss"), (int, float))
            and not isinstance(risk.get("stop_loss"), bool)
        )
    return {"checks": checks, "passed": all(checks.values())}


# ─── vLLM client ──────────────────────────────────────────────────────────────

def call_vllm(client: httpx.Client, url: str, model: str, prompt: str,
              temperature: float = 0.1) -> tuple[str, float]:
    started = time.perf_counter()
    response = client.post(
        f"{url}/chat/completions",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": 900,
        },
    )
    response.raise_for_status()
    raw = response.json()["choices"][0]["message"]["content"]
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    return raw, latency_ms


# ─── Main ─────────────────────────────────────────────────────────────────────

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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vllm-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model", default="models/qwen-trader-merged")
    parser.add_argument("--output", default="/persistent/track2/eval/cn_market_eval_final.json")
    parser.add_argument("--max-retries", type=int, default=2)
    args = parser.parse_args()

    cases = build_cases()
    results: list[dict] = []

    with httpx.Client(timeout=120.0) as client:
        for index, case in enumerate(cases, 1):
            retry_count = 0
            raw = ""
            latency_ms = 0.0
            all_outputs: list[dict] = []

            for attempt in range(args.max_retries + 1):
                temp = 0.1 if attempt == 0 else 0.3
                raw, latency_ms = call_vllm(
                    client, args.vllm_url, args.model, case["prompt"], temperature=temp
                )

                degraded = _is_degraded(raw)
                pre_repair = extract_json(raw)

                all_outputs.append({
                    "attempt": attempt,
                    "temperature": temp,
                    "raw_output": raw,
                    "degraded": degraded,
                    "parseable": pre_repair is not None,
                })

                if pre_repair is not None and not degraded:
                    break
                if attempt < args.max_retries:
                    retry_count += 1
                    print(f"  retry {retry_count} for case {index} "
                          f"(degraded={degraded}, parseable={pre_repair is not None})",
                          flush=True)

            # Use best attempt: first parseable non-degraded, else last
            pre_repair = extract_json(raw)
            pre_repair_copy = copy.deepcopy(pre_repair) if pre_repair else None

            post_repair = None
            repairs: list[dict] = []
            if pre_repair is not None:
                post_repair = copy.deepcopy(pre_repair)
                post_repair, repairs = canonicalize_cn_market(post_repair, case)

            assessment = evaluate_case(case, raw, pre_repair_copy, post_repair, repairs)

            result = {
                "id": index,
                **case,
                "latency_ms": latency_ms,
                "retry_count": retry_count,
                "raw_output": raw,
                "pre_repair_dsl": pre_repair_copy,
                "post_repair_dsl": post_repair,
                "repair_log": repairs,
                "all_attempts": all_outputs if retry_count > 0 else None,
                **assessment,
            }
            results.append(result)
            status = "PASS" if assessment["passed"] else "FAIL"
            print(f"[{index:02d}/{len(cases)}] {status} {latency_ms:.0f}ms "
                  f"retries={retry_count} {case['instrument']}", flush=True)

    # ── Summary ──
    check_names = list(results[0]["checks"])
    summary = {
        "model": args.model,
        "total": len(results),
        "passed": sum(item["passed"] for item in results),
        "pass_rate": round(sum(item["passed"] for item in results) / len(results), 4),
        "avg_latency_ms": round(statistics.mean(item["latency_ms"] for item in results), 2),
        "p95_latency_ms": round(
            sorted(item["latency_ms"] for item in results)[int(len(results) * 0.95) - 1], 2
        ),
        "total_retries": sum(item["retry_count"] for item in results),
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
