"""Experimental canonicalizer for Chinese market DSL — deterministic safe fixes only.

This is an INDEPENDENT experiment module. It does NOT modify the production
canonicalizer.py. It applies only deterministic, safe normalizations:

- Remove Markdown code fences
- Extract YAML/JSON body (handles `strategy":` prefix corruption)
- Coerce period strings to integers
- Fill missing risk/constraints with safe CN-market defaults
- Force allow_short: false, t_plus_one: true, lot_size: 100
- Force exchange: cn_stock when missing or wrong
- Force entry.short / exit.short to null
- Strip forbidden crypto terms
- Log every repair

Forbidden: modifying trade logic, user-specified instruments/periods, or
marking broken output as valid without actually fixing it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import yaml


@dataclass
class CNRepair:
    field: str
    raw: Any
    normalized: Any
    repair_type: str
    message: str = ""


FORBIDDEN_PATTERNS = re.compile(
    r"(?i)\b(btc|eth|usdt|binance|okx|bybit|kraken|crypto|"
    r"bitcoin|ethereum|比特币|以太坊|币安|合约交易)\b"
)


def extract_and_parse(raw_text: str) -> tuple[dict | None, list[CNRepair]]:
    """Extract a parseable dict from raw LLM output.

    Handles:
    - Markdown code fences (```yaml / ```json / ```)
    - `strategy":` prefix corruption (model adds stray quote)
    - Unquoted YAML keys (YAML 1.1 flow style)
    - Embedded JSON objects
    """
    repairs: list[CNRepair] = []
    text = raw_text.strip()

    # --- Remove Markdown code fences ---
    fence_match = re.match(r"```(?:ya?ml|json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
        repairs.append(CNRepair("markdown_fence", raw_text[:50], text[:50],
                                "strip_markdown", "Removed Markdown code fence"))

    # --- Fix `strategy":` prefix (stray quote after strategy) ---
    # Model sometimes outputs:  strategy": { ...  or  "strategy": { ...
    # We normalize to: strategy:
    strategy_prefix_pattern = re.compile(r'^["\']?strategy["\']?\s*:\s*', re.MULTILINE)
    has_bad_prefix = bool(re.match(r'^["\']?strategy["\']?\s*:\s*\{', text))

    if has_bad_prefix:
        # The output starts with strategy: { or strategy": { — it's a flow-style block
        # Wrap it in proper YAML by ensuring it's a valid mapping
        text_fixed = strategy_prefix_pattern.sub("strategy: ", text, count=1)
        repairs.append(CNRepair("strategy_prefix", text[:30], text_fixed[:30],
                                "fix_prefix", "Fixed strategy key prefix"))
        text = text_fixed

    # --- Try parsing strategies in order ---
    parsed = _try_parse(text)
    if parsed is None:
        # Try wrapping in braces if it looks like strategy: { ... }
        if re.match(r'^strategy\s*:\s*\{', text):
            # Convert flow to block: strategy: { ... } -> { strategy: { ... } }
            wrapped = "{ " + text + " }"
            parsed = _try_parse(wrapped)
            if parsed:
                repairs.append(CNRepair("root_wrap", None, "wrapped",
                                        "fix_structure", "Wrapped strategy in root braces"))

    if parsed is None:
        # Try extracting JSON object from text
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            fragment = text[start:end + 1]
            # If the fragment is just the inner strategy content, wrap it
            if not fragment.strip().startswith('{"strategy"') and not fragment.strip().startswith('{"strategy"'):
                # Check if it looks like strategy content
                if '"name"' in fragment or "'name'" in fragment:
                    fragment = '{"strategy": ' + fragment + '}'
                    repairs.append(CNRepair("strategy_wrap", None, "wrapped",
                                            "fix_structure", "Wrapped inner content as strategy"))
            parsed = _try_parse(fragment)

    if parsed is None:
        # Last resort: try treating entire text as a YAML mapping
        parsed = _try_parse(text)

    if parsed is None:
        repairs.append(CNRepair("parse", raw_text[:100], None,
                                "parse_failure", "Could not parse output as YAML or JSON"))
        return None, repairs

    # Ensure strategy key exists
    if "strategy" not in parsed:
        # Maybe the parsed dict IS the strategy content
        if any(k in parsed for k in ("name", "market", "indicators")):
            parsed = {"strategy": parsed}
            repairs.append(CNRepair("strategy_key", None, "created",
                                    "fix_structure", "Wrapped content in strategy key"))
        else:
            repairs.append(CNRepair("strategy_key", None, None,
                                    "missing_strategy", "No strategy key found"))
            return parsed, repairs

    return parsed, repairs


def _try_parse(text: str) -> dict | None:
    """Try multiple parsing strategies."""
    text = text.strip()
    # Try YAML first (handles both flow and block style, unquoted keys)
    try:
        result = yaml.safe_load(text)
        if isinstance(result, dict):
            return result
    except yaml.YAMLError:
        pass

    # Try JSON
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Try a JSON fragment
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            result = json.loads(text[start:end + 1])
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    return None


def canonicalize_cn_dsl(
    dsl: dict[str, Any],
    expected_instrument: str | None = None,
    expected_timeframe: str | None = None,
) -> tuple[dict[str, Any], list[CNRepair], list[str]]:
    """Canonicalize a parsed DSL dict for Chinese market constraints.

    Returns:
        (canonicalized_dsl, repairs, errors)
    """
    repairs: list[CNRepair] = []
    errors: list[str] = []

    if not isinstance(dsl, dict):
        errors.append("DSL root is not a dict")
        return dsl, repairs, errors

    if "strategy" not in dsl:
        errors.append("Missing 'strategy' key at root")
        return dsl, repairs, errors

    strat = dsl["strategy"]
    if not isinstance(strat, dict):
        errors.append("'strategy' is not a dict")
        return dsl, repairs, errors

    # --- Canonicalize name ---
    if "name" not in strat or not strat["name"]:
        strat["name"] = "GeneratedStrategy"
        repairs.append(CNRepair("strategy.name", None, "GeneratedStrategy",
                                "default_fill", "Missing name, filled default"))

    # --- Canonicalize market ---
    if "market" not in strat:
        strat["market"] = {}
        repairs.append(CNRepair("strategy.market", None, {},
                                "default_fill", "Missing market section"))

    market = strat["market"]

    # Force exchange to cn_stock
    if market.get("exchange") != "cn_stock":
        old = market.get("exchange")
        market["exchange"] = "cn_stock"
        repairs.append(CNRepair("strategy.market.exchange", old, "cn_stock",
                                "force_cn", f"Exchange was '{old}', forced to cn_stock"))

    # Instrument: preserve expected instrument if provided
    if expected_instrument and market.get("instrument") != expected_instrument:
        old = market.get("instrument")
        market["instrument"] = expected_instrument
        repairs.append(CNRepair("strategy.market.instrument", old, expected_instrument,
                                "restore_instrument", f"Instrument was '{old}', restored to '{expected_instrument}'"))
    elif "instrument" not in market:
        market["instrument"] = "510300.SH"
        repairs.append(CNRepair("strategy.market.instrument", None, "510300.SH",
                                "default_fill", "Missing instrument, filled default"))

    # Timeframe: preserve expected timeframe if provided
    if expected_timeframe and market.get("timeframe") != expected_timeframe:
        old = market.get("timeframe")
        market["timeframe"] = expected_timeframe
        repairs.append(CNRepair("strategy.market.timeframe", old, expected_timeframe,
                                "restore_timeframe", f"Timeframe was '{old}', restored to '{expected_timeframe}'"))
    elif "timeframe" not in market:
        market["timeframe"] = "1d"
        repairs.append(CNRepair("strategy.market.timeframe", None, "1d",
                                "default_fill", "Missing timeframe, filled default"))

    # --- Canonicalize indicators ---
    if "indicators" not in strat or not isinstance(strat["indicators"], list) or len(strat["indicators"]) == 0:
        if "indicators" not in strat:
            errors.append("Missing 'indicators' — cannot infer strategy logic")
        else:
            errors.append("indicators is empty or not a list")
    else:
        for i, ind in enumerate(strat["indicators"]):
            if not isinstance(ind, dict):
                errors.append(f"Indicator {i} is not a dict")
                continue
            _canonicalize_indicator_cn(ind, i, repairs, errors)

    # --- Canonicalize entry ---
    if "entry" not in strat:
        strat["entry"] = {}
        repairs.append(CNRepair("strategy.entry", None, {},
                                "default_fill", "Missing entry, created"))

    entry = strat["entry"]
    if "long" not in entry:
        entry["long"] = None
        repairs.append(CNRepair("strategy.entry.long", None, None,
                                "default_fill", "Missing entry.long"))
    # Force short to null
    if entry.get("short") is not None:
        old = entry.get("short")
        entry["short"] = None
        repairs.append(CNRepair("strategy.entry.short", old, None,
                                "force_null", "Forced entry.short to null (no shorting)"))
    elif "short" not in entry:
        entry["short"] = None
        repairs.append(CNRepair("strategy.entry.short", None, None,
                                "default_fill", "Missing entry.short, set to null"))

    # --- Canonicalize exit ---
    if "exit" not in strat:
        strat["exit"] = {}
        repairs.append(CNRepair("strategy.exit", None, {},
                                "default_fill", "Missing exit, created"))

    exit_section = strat["exit"]
    if "long" not in exit_section:
        exit_section["long"] = None
        repairs.append(CNRepair("strategy.exit.long", None, None,
                                "default_fill", "Missing exit.long"))
    if exit_section.get("short") is not None:
        old = exit_section.get("short")
        exit_section["short"] = None
        repairs.append(CNRepair("strategy.exit.short", old, None,
                                "force_null", "Forced exit.short to null"))
    elif "short" not in exit_section:
        exit_section["short"] = None
        repairs.append(CNRepair("strategy.exit.short", None, None,
                                "default_fill", "Missing exit.short, set to null"))

    # --- Canonicalize risk ---
    if "risk" not in strat:
        strat["risk"] = {}
        repairs.append(CNRepair("strategy.risk", None, {},
                                "default_fill", "Missing risk section, created"))

    risk = strat["risk"]
    if "stop_loss" not in risk:
        risk["stop_loss"] = -0.05
        repairs.append(CNRepair("strategy.risk.stop_loss", None, -0.05,
                                "default_fill", "Missing stop_loss, set to -0.05"))
    else:
        risk["stop_loss"] = _coerce_float_cn(risk["stop_loss"], "strategy.risk.stop_loss", repairs)
        if risk["stop_loss"] > 0:
            risk["stop_loss"] = -risk["stop_loss"]
            repairs.append(CNRepair("strategy.risk.stop_loss", abs(risk["stop_loss"]), risk["stop_loss"],
                                    "sign_fix", "Positive stop_loss negated"))
        if risk["stop_loss"] > -0.001:
            risk["stop_loss"] = -0.05
            repairs.append(CNRepair("strategy.risk.stop_loss", risk["stop_loss"], -0.05,
                                    "range_fix", "stop_loss too close to 0, set to -0.05"))

    if "max_position_pct" not in risk:
        risk["max_position_pct"] = 0.1
        repairs.append(CNRepair("strategy.risk.max_position_pct", None, 0.1,
                                "default_fill", "Missing max_position_pct, set to 0.1"))
    else:
        risk["max_position_pct"] = _coerce_float_cn(risk["max_position_pct"],
                                                      "strategy.risk.max_position_pct", repairs)

    if "max_drawdown" not in risk:
        risk["max_drawdown"] = 0.15
        repairs.append(CNRepair("strategy.risk.max_drawdown", None, 0.15,
                                "default_fill", "Missing max_drawdown, set to 0.15"))
    else:
        risk["max_drawdown"] = _coerce_float_cn(risk["max_drawdown"],
                                                  "strategy.risk.max_drawdown", repairs)

    # --- Canonicalize constraints (CN market specific) ---
    if "constraints" not in strat:
        strat["constraints"] = {}
        repairs.append(CNRepair("strategy.constraints", None, {},
                                "default_fill", "Missing constraints, created"))

    constraints = strat["constraints"]

    # Force t_plus_one: true
    if constraints.get("t_plus_one") is not True:
        old = constraints.get("t_plus_one")
        constraints["t_plus_one"] = True
        repairs.append(CNRepair("strategy.constraints.t_plus_one", old, True,
                                "force_value", "Forced t_plus_one to true"))

    # Force price_limit: 0.1
    if "price_limit" not in constraints or not isinstance(constraints.get("price_limit"), (int, float)):
        old = constraints.get("price_limit")
        constraints["price_limit"] = 0.1
        repairs.append(CNRepair("strategy.constraints.price_limit", old, 0.1,
                                "force_value", "Forced price_limit to 0.1"))
    else:
        constraints["price_limit"] = _coerce_float_cn(constraints["price_limit"],
                                                         "strategy.constraints.price_limit", repairs)

    # Force allow_short: false
    if constraints.get("allow_short") is not False:
        old = constraints.get("allow_short")
        constraints["allow_short"] = False
        repairs.append(CNRepair("strategy.constraints.allow_short", old, False,
                                "force_value", "Forced allow_short to false"))

    # Force lot_size: 100 (THIS IS THE MOST COMMON FAILURE)
    if constraints.get("lot_size") != 100:
        old = constraints.get("lot_size")
        constraints["lot_size"] = 100
        repairs.append(CNRepair("strategy.constraints.lot_size", old, 100,
                                "force_value", f"lot_size was '{old}', forced to 100"))

    # --- Clean forbidden crypto terms ---
    _clean_forbidden_terms(strat, repairs)

    return dsl, repairs, errors


def _canonicalize_indicator_cn(ind: dict, idx: int, repairs: list[CNRepair], errors: list[str]) -> None:
    prefix = f"strategy.indicators.{idx}"

    if "name" not in ind:
        ind["name"] = f"indicator_{idx}"
        repairs.append(CNRepair(f"{prefix}.name", None, ind["name"],
                                "default_fill", "Missing indicator name"))

    if "type" not in ind:
        errors.append(f"{prefix}.type missing")
        return

    if "params" not in ind or not isinstance(ind["params"], dict):
        ind["params"] = {}
        repairs.append(CNRepair(f"{prefix}.params", None, {},
                                "default_fill", "Missing/invalid params"))

    params = ind["params"]

    # Coerce period to int (string "20" -> 20)
    for key in ("period", "fast_period", "slow_period", "signal_period"):
        if key in params:
            params[key] = _coerce_int_cn(params[key], f"{prefix}.params.{key}", repairs)

    for key in ("std_dev", "multiplier"):
        if key in params:
            params[key] = _coerce_float_cn(params[key], f"{prefix}.params.{key}", repairs)

    field_val = params.get("field", "close")
    if field_val not in ("open", "high", "low", "close", "volume"):
        params["field"] = "close"
        repairs.append(CNRepair(f"{prefix}.params.field", field_val, "close",
                                "default_fill", f"Invalid field '{field_val}', set to close"))


def _clean_forbidden_terms(strat: dict, repairs: list[CNRepair]) -> None:
    """Remove or replace forbidden crypto terms in all string values."""
    def _clean_value(obj: Any, path: str) -> Any:
        if isinstance(obj, str):
            if FORBIDDEN_PATTERNS.search(obj):
                cleaned = FORBIDDEN_PATTERNS.sub("", obj).strip()
                repairs.append(CNRepair(path, obj[:50], cleaned[:50],
                                        "strip_forbidden", "Removed forbidden crypto term"))
                return cleaned
            return obj
        elif isinstance(obj, dict):
            return {k: _clean_value(v, f"{path}.{k}") for k, v in obj.items()}
        elif isinstance(obj, list):
            return [_clean_value(v, f"{path}[{i}]") for i, v in enumerate(obj)]
        return obj

    for key in list(strat.keys()):
        strat[key] = _clean_value(strat[key], f"strategy.{key}")


def _coerce_int_cn(value: Any, field_path: str, repairs: list[CNRepair]) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        repairs.append(CNRepair(field_path, value, int(value),
                                "type_coerce", f"Float {value} → int {int(value)}"))
        return int(value)
    if isinstance(value, str):
        try:
            parsed = int(value)
            repairs.append(CNRepair(field_path, value, parsed,
                                    "type_coerce", f"String '{value}' → int {parsed}"))
            return parsed
        except ValueError:
            try:
                parsed = int(float(value))
                repairs.append(CNRepair(field_path, value, parsed,
                                        "type_coerce", f"String '{value}' → float → int"))
                return parsed
            except ValueError:
                repairs.append(CNRepair(field_path, value, 14,
                                        "default_fill", f"Cannot parse '{value}' as int, set 14"))
                return 14
    repairs.append(CNRepair(field_path, value, 14,
                            "default_fill", f"Unknown type {type(value).__name__}, set 14"))
    return 14


def _coerce_float_cn(value: Any, field_path: str, repairs: list[CNRepair]) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            parsed = float(value)
            repairs.append(CNRepair(field_path, value, parsed,
                                    "type_coerce", f"String '{value}' → float {parsed}"))
            return parsed
        except ValueError:
            repairs.append(CNRepair(field_path, value, 0.1,
                                    "default_fill", f"Cannot parse '{value}' as float, set 0.1"))
            return 0.1
    repairs.append(CNRepair(field_path, value, 0.1,
                            "default_fill", f"Unknown type, set 0.1"))
    return 0.1


def process_raw_output(
    raw_output: str,
    expected_instrument: str | None = None,
    expected_timeframe: str | None = None,
) -> dict[str, Any]:
    """Full pipeline: extract → parse → canonicalize → return result dict.

    Returns dict with keys:
        - raw_output: original LLM text
        - parsed: parsed dict (or None)
        - canonicalized: canonicalized dict (or None)
        - repairs: list of CNRepair objects
        - errors: list of error strings
        - parse_success: bool
        - canon_success: bool
    """
    parsed, extract_repairs = extract_and_parse(raw_output)

    if parsed is None:
        return {
            "raw_output": raw_output,
            "parsed": None,
            "canonicalized": None,
            "extract_repairs": [r.__dict__ for r in extract_repairs],
            "canon_repairs": [],
            "errors": ["Failed to parse output"],
            "parse_success": False,
            "canon_success": False,
        }

    canonicalized, canon_repairs, errors = canonicalize_cn_dsl(
        parsed, expected_instrument, expected_timeframe
    )

    return {
        "raw_output": raw_output,
        "parsed": parsed,
        "canonicalized": canonicalized,
        "extract_repairs": [r.__dict__ for r in extract_repairs],
        "canon_repairs": [r.__dict__ for r in canon_repairs],
        "errors": errors,
        "parse_success": True,
        "canon_success": len(errors) == 0,
    }
