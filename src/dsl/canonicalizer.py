"""DSL canonicalizer — normalizes LLM output before schema validation.

Sits between YAML parsing and JSON Schema validation:

    LLM output → YAML parse → canonicalize_dsl() → validate_dsl() → backtest

Handles common LLM output errors:
- String numbers: "50" → 50, "2.0" → 2.0
- Positive stop_loss: 3.0 → -0.03 (interprets as 3% loss)
- Non-numeric expressions: "ema_fast - atr*3" → rejected
- Missing required fields: filled with safe defaults
- Missing indicators: rejected (critical, cannot infer)

Every modification is logged in a repairs list for transparency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Repair:
    """A single normalization repair applied to DSL."""
    field: str
    raw: Any
    normalized: Any
    repair_type: str
    message: str = ""


def canonicalize_dsl(dsl: dict[str, Any]) -> tuple[dict[str, Any], list[Repair], list[str]]:
    """Canonicalize a parsed DSL dict before schema validation.

    Args:
        dsl: Parsed YAML dict from LLM output.

    Returns:
        Tuple of (canonicalized_dsl, repairs, errors):
        - canonicalized_dsl: Normalized dict ready for schema validation
        - repairs: List of Repair objects documenting every change
        - errors: List of unrecoverable error messages (critical fields
          that cannot be safely fixed — caller should retry or reject)
    """
    repairs: list[Repair] = []
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
        repairs.append(Repair("strategy.name", strat.get("name"), "GeneratedStrategy",
                              "default_fill", "Missing strategy name, filled with default"))

    # --- Canonicalize indicators ---
    if "indicators" not in strat:
        errors.append("Missing 'indicators' — cannot infer strategy logic without indicators")
    elif not isinstance(strat["indicators"], list):
        errors.append("'indicators' is not a list")
    elif len(strat["indicators"]) == 0:
        errors.append("'indicators' is empty — at least one indicator required")
    else:
        for i, ind in enumerate(strat["indicators"]):
            if not isinstance(ind, dict):
                errors.append(f"Indicator at index {i} is not a dict")
                continue
            _canonicalize_indicator(ind, i, repairs, errors)

    # --- Canonicalize risk ---
    if "risk" not in strat:
        # Fill with safe defaults
        strat["risk"] = {
            "stop_loss": -0.03,
            "max_open_trades": 3,
            "stake_amount": 0.1,
        }
        repairs.append(Repair("strategy.risk", None, strat["risk"],
                              "default_fill",
                              "Missing risk section, filled with safe defaults: stop_loss=-0.03, max_open_trades=3, stake_amount=0.1"))
    else:
        _canonicalize_risk(strat["risk"], repairs, errors)

    # --- Canonicalize entry ---
    if "entry" not in strat:
        strat["entry"] = {"long": None, "short": None}
        repairs.append(Repair("strategy.entry", None, strat["entry"],
                              "default_fill", "Missing entry section, filled with nulls"))
    else:
        _canonicalize_entry_exit(strat["entry"], "entry", repairs, errors)

    # --- Canonicalize exit ---
    if "exit" not in strat:
        strat["exit"] = {"long": None, "short": None}
        repairs.append(Repair("strategy.exit", None, strat["exit"],
                              "default_fill", "Missing exit section, filled with nulls"))
    else:
        _canonicalize_entry_exit(strat["exit"], "exit", repairs, errors)

    # --- Canonicalize market ---
    if "market" not in strat:
        strat["market"] = {
            "exchange": "binance",
            "pair": "BTC/USDT",
            "timeframe": "1h",
        }
        repairs.append(Repair("strategy.market", None, strat["market"],
                              "default_fill", "Missing market section, filled with BTC/USDT 1h"))

    return dsl, repairs, errors


def _canonicalize_indicator(ind: dict, idx: int, repairs: list[Repair], errors: list[str]) -> None:
    """Canonicalize a single indicator spec."""
    prefix = f"strategy.indicators.{idx}"

    # Ensure required fields exist
    if "name" not in ind:
        errors.append(f"{prefix}.name missing")
        return
    if "type" not in ind:
        errors.append(f"{prefix}.type missing")
        return

    # Ensure params is a dict
    if "params" not in ind:
        ind["params"] = {}
        repairs.append(Repair(f"{prefix}.params", None, {},
                              "default_fill", "Missing params, filled with empty dict"))
    elif not isinstance(ind["params"], dict):
        ind["params"] = {}
        repairs.append(Repair(f"{prefix}.params", ind["params"], {},
                              "type_fix", "Params was not a dict, reset to empty"))

    params = ind["params"]

    # Coerce numeric string fields
    for key in ("period", "fast_period", "slow_period", "signal_period"):
        if key in params:
            params[key] = _coerce_int(params[key], f"{prefix}.params.{key}", repairs)

    for key in ("std_dev", "multiplier"):
        if key in params:
            params[key] = _coerce_float(params[key], f"{prefix}.params.{key}", repairs)

    # Ensure field is valid
    field_val = params.get("field", "close")
    if field_val not in ("open", "high", "low", "close", "volume"):
        params["field"] = "close"
        repairs.append(Repair(f"{prefix}.params.field", field_val, "close",
                              "default_fill", f"Invalid field '{field_val}', set to 'close'"))


def _canonicalize_risk(risk: dict, repairs: list[Repair], errors: list[str]) -> None:
    """Canonicalize risk parameters."""
    # stop_loss — most critical
    if "stop_loss" not in risk:
        risk["stop_loss"] = -0.03
        repairs.append(Repair("strategy.risk.stop_loss", None, -0.03,
                              "default_fill", "Missing stop_loss, set to -0.03"))
    else:
        raw = risk["stop_loss"]
        if isinstance(raw, str):
            # Try to parse as number
            try:
                raw_num = float(raw)
                risk["stop_loss"] = _fix_stop_loss(raw_num, repairs)
            except ValueError:
                errors.append(f"strategy.risk.stop_loss: cannot parse '{raw}' as number — expression-based stop_loss not supported")
        elif isinstance(raw, (int, float)):
            risk["stop_loss"] = _fix_stop_loss(float(raw), repairs)
        else:
            errors.append(f"strategy.risk.stop_loss: type {type(raw).__name__} not supported")

    # max_open_trades
    if "max_open_trades" not in risk:
        risk["max_open_trades"] = 3
        repairs.append(Repair("strategy.risk.max_open_trades", None, 3,
                              "default_fill", "Missing, set to 3"))
    else:
        risk["max_open_trades"] = _coerce_int(risk["max_open_trades"],
                                               "strategy.risk.max_open_trades", repairs)
        if risk["max_open_trades"] < 1:
            risk["max_open_trades"] = 1
            repairs.append(Repair("strategy.risk.max_open_trades", risk["max_open_trades"], 1,
                                  "range_fix", "Was <1, set to 1"))

    # stake_amount
    if "stake_amount" not in risk:
        risk["stake_amount"] = 0.1
        repairs.append(Repair("strategy.risk.stake_amount", None, 0.1,
                              "default_fill", "Missing, set to 0.1"))
    else:
        raw = risk["stake_amount"]
        if isinstance(raw, str) and raw != "unlimited":
            try:
                risk["stake_amount"] = float(raw)
                repairs.append(Repair("strategy.risk.stake_amount", raw, risk["stake_amount"],
                                      "type_coerce", f"String '{raw}' → float"))
            except ValueError:
                risk["stake_amount"] = 0.1
                repairs.append(Repair("strategy.risk.stake_amount", raw, 0.1,
                                      "default_fill", f"Could not parse '{raw}', set to 0.1"))

    # Strip unknown risk fields (schema uses additionalProperties: false)
    _ALLOWED_RISK = {'stop_loss', 'take_profit', 'trailing_stop', 'trailing_stop_positive',
                     'trailing_stop_positive_offset', 'max_open_trades', 'stake_amount', 'time_in_trade'}
    for k in list(risk.keys()):
        if k not in _ALLOWED_RISK:
            repairs.append(Repair(f'strategy.risk.{k}', risk[k], None,
                                'strip_unknown', f'Removed unknown risk field: {k}'))
            del risk[k]

    # take_profit (optional)
    if "take_profit" in risk:
        risk["take_profit"] = _coerce_float(risk["take_profit"],
                                             "strategy.risk.take_profit", repairs)

    # trailing_stop (optional)
    if "trailing_stop" in risk and isinstance(risk["trailing_stop"], str):
        val = risk["trailing_stop"].lower().strip()
        risk["trailing_stop"] = val in ("true", "yes", "1")
        repairs.append(Repair("strategy.risk.trailing_stop", raw, risk["trailing_stop"],
                              "type_coerce", f"String '{raw}' → bool"))

    if "trailing_stop_positive" in risk:
        risk["trailing_stop_positive"] = _coerce_float(risk["trailing_stop_positive"],
                                                        "strategy.risk.trailing_stop_positive", repairs)


def _fix_stop_loss(value: float, repairs: list[Repair]) -> float:
    """Fix stop_loss value to be a negative decimal ratio.

    Interpretation rules:
    - Already negative and > -1: keep as-is (e.g. -0.03 = 3% loss)
    - Positive and > 1: interpret as percentage → convert (e.g. 3.0 → -0.03)
    - Positive and 0 < x < 1: interpret as ratio → negate (e.g. 0.03 → -0.03)
    - Already negative and <= -1: interpret as percentage → convert (e.g. -3.0 → -0.03)
    """
    if value > 1:
        # Percentage: 3.0 means 3% loss → -0.03
        fixed = -value / 100.0
        repairs.append(Repair("strategy.risk.stop_loss", value, fixed,
                              "positive_percent_to_negative_decimal",
                              f"Value {value} interpreted as {value}% loss → -{value/100:.4f}"))
        return round(fixed, 4)
    elif value > 0:
        # Ratio: 0.03 means 3% loss but positive → negate
        fixed = -value
        repairs.append(Repair("strategy.risk.stop_loss", value, fixed,
                              "positive_to_negative",
                              f"Positive ratio {value} → negated to {fixed}"))
        return round(fixed, 4)
    elif value <= -1:
        # Negative percentage: -3.0 means 3% loss → -0.03
        fixed = value / 100.0
        repairs.append(Repair("strategy.risk.stop_loss", value, fixed,
                              "negative_percent_to_decimal",
                              f"Value {value} interpreted as {abs(value)}% loss → {fixed}"))
        return round(fixed, 4)
    else:
        # Already correct: -0.03
        return round(value, 4)


def _canonicalize_entry_exit(section: dict, name: str, repairs: list[Repair], errors: list[str]) -> None:
    """Canonicalize entry/exit section.

    Strips illegal fields (schema only allows 'long' and 'short').
    LLMs sometimes output 'buy', 'sell', 'enter', etc.
    """
    prefix = f"strategy.{name}"

    # Strip illegal keys — only 'long' and 'short' are valid
    allowed = {"long", "short"}
    illegal_keys = set(section.keys()) - allowed
    for key in illegal_keys:
        repairs.append(Repair(f"{prefix}.{key}", section[key], None,
                              "strip_illegal",
                              f"Removed illegal field '{key}' from {name} (only 'long'/'short' allowed)"))
        del section[key]

    for direction in ("long", "short"):
        if direction not in section:
            section[direction] = None
            repairs.append(Repair(f"{prefix}.{direction}", None, None,
                                  "default_fill", f"Missing {direction}, set to null"))
        elif isinstance(section[direction], str):
            # Keep string expressions as-is (they'll be validated by expr_parser)
            pass
        elif section[direction] is not None and not isinstance(section[direction], str):
            errors.append(f"{prefix}.{direction}: expected string or null, got {type(section[direction]).__name__}")


def _coerce_int(value: Any, field_path: str, repairs: list[Repair]) -> int:
    """Coerce a value to int, logging the repair."""
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        repairs.append(Repair(field_path, value, int(value),
                              "type_coerce", f"Float {value} → int {int(value)}"))
        return int(value)
    if isinstance(value, str):
        try:
            parsed = int(value)
            repairs.append(Repair(field_path, value, parsed,
                                  "type_coerce", f"String '{value}' → int {parsed}"))
            return parsed
        except ValueError:
            try:
                parsed = int(float(value))
                repairs.append(Repair(field_path, value, parsed,
                                      "type_coerce", f"String '{value}' → float → int {parsed}"))
                return parsed
            except ValueError:
                repairs.append(Repair(field_path, value, 14,
                                      "default_fill", f"Could not parse '{value}' as int, set to 14"))
                return 14
    repairs.append(Repair(field_path, value, 14,
                          "default_fill", f"Unknown type {type(value).__name__}, set to 14"))
    return 14


def _coerce_float(value: Any, field_path: str, repairs: list[Repair]) -> float:
    """Coerce a value to float, logging the repair."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            parsed = float(value)
            repairs.append(Repair(field_path, value, parsed,
                                  "type_coerce", f"String '{value}' → float {parsed}"))
            return parsed
        except ValueError:
            repairs.append(Repair(field_path, value, 2.0,
                                  "default_fill", f"Could not parse '{value}' as float, set to 2.0"))
            return 2.0
    repairs.append(Repair(field_path, value, 2.0,
                          "default_fill", f"Unknown type {type(value).__name__}, set to 2.0"))
    return 2.0
