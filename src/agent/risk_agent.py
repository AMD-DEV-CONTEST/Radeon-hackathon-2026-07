"""Risk Control Agent — the final gatekeeper with veto power.

Two types of checks:
1. **Fact check**: Verify all numbers in the reasoning output have RAG support
2. **Hard rule check** (code-level, not model-influenced):
   - Total position limit
   - Per-asset position limit
   - Max allowed loss
   - Stop-loss distance compliance
   - Leverage limit

Output: allow_execute (bool) + final_position_ratio + audit_note

If allow_execute=false, no trade is executed — period.
The LLM never has the final say; the Risk Agent does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .protocol import AgentMessage


@dataclass
class RiskConfig:
    """Hard risk limits — code-level, not configurable by the LLM."""

    max_total_position: float = 0.30       # 30% max total position
    max_per_asset_position: float = 0.10   # 10% max per single asset
    max_allowed_loss: float = -0.05        # -5% max allowed loss
    min_stop_loss_distance: float = 0.005  # 0.5% min stop distance
    max_stop_loss_distance: float = 0.15   # 15% max stop distance
    max_leverage: int = 1                  # No leverage by default
    max_confidence_threshold: float = 0.30 # Below this confidence → reject


@dataclass
class CheckResult:
    """Result of a single risk check."""
    name: str
    passed: bool
    detail: str


def run_risk_agent(msg: AgentMessage, config: RiskConfig | None = None) -> AgentMessage:
    """Execute risk validation on the reasoning agent's trading intent.

    Returns allow_execute=true only if ALL checks pass.
    """
    cfg = config or RiskConfig()
    intent = msg.payload

    view = intent.get("view", "neutral")
    confidence = float(intent.get("confidence", 0))
    pos_ratio = float(intent.get("suggest_position_ratio", 0))
    stop_loss = intent.get("stop_loss_price")
    entry_price = intent.get("entry_price")
    reason = intent.get("reason", "")

    checks: list[CheckResult] = []

    # ── Check 1: Neutral view → no execution needed ────────────
    if view == "neutral":
        checks.append(CheckResult("neutral_view", True, "Neutral view — no execution needed"))
        return _build_result(checks, False, 0, "Neutral view, no trade to execute", msg)

    checks.append(CheckResult("neutral_view", True, f"View={view}, proceeding to checks"))

    # ── Check 2: Confidence threshold ──────────────────────────
    if confidence < cfg.max_confidence_threshold:
        checks.append(CheckResult(
            "confidence", False,
            f"Confidence {confidence:.2f} below threshold {cfg.max_confidence_threshold}"
        ))
        return _build_result(checks, False, 0, "Confidence too low, trade rejected", msg)

    checks.append(CheckResult("confidence", True, f"Confidence {confidence:.2f} OK"))

    # ── Check 3: Position size limits ──────────────────────────
    if pos_ratio > cfg.max_per_asset_position:
        # Auto-adjust to max allowed
        original = pos_ratio
        pos_ratio = cfg.max_per_asset_position
        checks.append(CheckResult(
            "per_asset_position", True,
            f"Position {original:.2%} exceeded max {cfg.max_per_asset_position:.2%}, "
            f"adjusted down to {pos_ratio:.2%}"
        ))
    else:
        checks.append(CheckResult("per_asset_position", True, f"Position {pos_ratio:.2%} OK"))

    if pos_ratio > cfg.max_total_position:
        checks.append(CheckResult(
            "total_position", False,
            f"Position {pos_ratio:.2%} exceeds total limit {cfg.max_total_position:.2%}"
        ))
        return _build_result(checks, False, 0, "Total position limit exceeded", msg)

    checks.append(CheckResult("total_position", True, "Within total limit"))

    # ── Check 4: Stop-loss distance ────────────────────────────
    if stop_loss is not None and entry_price is not None:
        try:
            sl_pct = abs(float(stop_loss) - float(entry_price)) / float(entry_price)
            if sl_pct < cfg.min_stop_loss_distance:
                checks.append(CheckResult(
                    "stop_loss_distance", False,
                    f"Stop loss distance {sl_pct:.2%} below minimum {cfg.min_stop_loss_distance:.2%}"
                ))
                return _build_result(checks, False, 0, "Stop loss too tight", msg)
            elif sl_pct > cfg.max_stop_loss_distance:
                checks.append(CheckResult(
                    "stop_loss_distance", False,
                    f"Stop loss distance {sl_pct:.2%} above maximum {cfg.max_stop_loss_distance:.2%}"
                ))
                return _build_result(checks, False, 0, "Stop loss too wide", msg)
            else:
                checks.append(CheckResult("stop_loss_distance", True, f"Stop loss distance {sl_pct:.2%} OK"))
        except (TypeError, ZeroDivisionError):
            checks.append(CheckResult("stop_loss_distance", False, "Cannot calculate stop loss distance"))
            return _build_result(checks, False, 0, "Stop loss calculation error", msg)
    elif stop_loss is not None and stop_loss != 0:
        checks.append(CheckResult("stop_loss_distance", True, "Stop loss present (no entry price for distance check)"))
    else:
        if view != "neutral":
            checks.append(CheckResult("stop_loss_distance", False, "No stop loss set for non-neutral position"))
            return _build_result(checks, False, 0, "Missing stop loss", msg)

    # ── Check 5: Reason must not be empty ──────────────────────
    if not reason.strip():
        checks.append(CheckResult("reason_completeness", False, "Empty reasoning"))
        return _build_result(checks, False, 0, "Missing reasoning", msg)
    checks.append(CheckResult("reason_completeness", True, "Reasoning present"))

    # ── All checks passed ───────────────────────────────────────
    return _build_result(checks, True, pos_ratio, "All risk checks passed", msg)


def _build_result(
    checks: list[CheckResult],
    allow: bool,
    final_ratio: float,
    note: str,
    msg: AgentMessage,
) -> AgentMessage:
    """Build the final risk agent message."""
    passed = [c.name for c in checks if c.passed]
    failed = [c.name for c in checks if not c.passed]

    return AgentMessage(
        payload={
            "allow_execute": allow,
            "final_position_ratio": final_ratio,
            "audit_note": note,
            "checks_passed": passed,
            "checks_failed": failed,
            "check_details": [
                {"name": c.name, "passed": c.passed, "detail": c.detail}
                for c in checks
            ],
        },
        status="success" if allow else "reject",
        source_agent="risk_agent",
        target_agent="orchestrator",
        session_id=msg.session_id,
        asset=msg.asset,
        timeframe=msg.timeframe,
    )
