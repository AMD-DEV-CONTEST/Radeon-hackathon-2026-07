"""Reward function for RL-based strategy optimization.

Computes a scalar reward from backtest metrics, combining:
- Profitability (total_return, alpha vs benchmark)
- Risk-adjusted return (Sharpe, Sortino, Calmar)
- Risk control (max drawdown, consecutive losses)
- Robustness (walk-forward consistency)

The reward is normalized to [-1.0, 1.0]:
  +1.0 = excellent (high return, high Sharpe, low drawdown, positive alpha)
   0.0 = neutral (break-even or mixed signals)
  -1.0 = terrible (large loss, high drawdown, negative alpha)

This reward signal feeds into:
  L1: Immediate prompt injection (current session)
  L2: Experience rule extraction (semantic memory)
  L3: DPO training data generation (LoRA weight update)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RewardConfig:
    """Weights for reward components — sum should be 1.0."""

    # Profitability (35%)
    w_return: float = 0.20       # total_return contribution
    w_alpha: float = 0.15        # alpha vs buy-and-hold

    # Risk-adjusted (30%)
    w_sharpe: float = 0.15       # Sharpe ratio
    w_sortino: float = 0.10      # Sortino ratio (downside risk)
    w_calmar: float = 0.05       # Calmar ratio (return/drawdown)

    # Risk control (20%)
    w_drawdown: float = 0.12     # max drawdown penalty
    w_consecutive: float = 0.08  # max consecutive losses penalty

    # Robustness (15%)
    w_walkforward: float = 0.15  # walk-forward consistency

    # Thresholds
    sharpe_good: float = 2.0     # Sharpe at which reward is maxed
    sharpe_bad: float = -0.5    # Sharpe at which penalty is maxed
    dd_threshold: float = 0.20   # Drawdown beyond which penalty kicks in
    dd_max: float = 0.50         # Drawdown at which penalty is maxed


@dataclass
class RewardBreakdown:
    """Detailed reward breakdown for transparency and debugging."""
    total: float = 0.0
    components: dict[str, float] = field(default_factory=dict)
    grade: str = ""              # A+ / A / B / C / D / F
    feedback: str = ""           # Natural language feedback for prompt

    def __float__(self) -> float:
        return self.total


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    if x != x:  # NaN check
        return 0.0
    return max(lo, min(hi, x))


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert to float, returning default for NaN/None/inf."""
    try:
        f = float(value)
        if f != f or f in (float('inf'), float('-inf')):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _sigmoid_normalize(value: float, center: float = 0.0, scale: float = 1.0) -> float:
    """Normalize a value to [0, 1] using sigmoid, then map to [-1, 1]."""
    if value != value:  # NaN
        return 0.0
    return 2.0 / (1.0 + math.exp(-(value - center) / scale)) - 1.0


def compute_reward(
    metrics: dict[str, Any],
    walkforward: dict[str, Any] | None = None,
    config: RewardConfig | None = None,
) -> RewardBreakdown:
    """Compute a normalized reward from backtest metrics.

    Args:
        metrics: BacktestResult metrics dict (total_return, sharpe_ratio, etc.)
        walkforward: Optional walk-forward analysis result (is_robust, overfitting_score)
        config: Reward weight configuration

    Returns:
        RewardBreakdown with total score [-1, 1], component breakdown, grade, and feedback.
    """
    cfg = config or RewardConfig()
    components: dict[str, float] = {}

    # ── 1. Total return (profitability) ────────────────────────
    total_return = _safe_float(metrics.get("total_return"))
    # Map [-50%, +50%] → [-1, +1] with diminishing returns at extremes
    ret_score = _clamp(total_return / 0.50)
    components["return"] = ret_score * cfg.w_return

    # ── 2. Alpha (vs buy-and-hold) ─────────────────────────────
    alpha = _safe_float(metrics.get("alpha"))
    # Alpha > 10% is excellent, < -10% is terrible
    alpha_score = _clamp(alpha / 0.10)
    components["alpha"] = alpha_score * cfg.w_alpha

    # ── 3. Sharpe ratio ────────────────────────────────────────
    sharpe = _safe_float(metrics.get("sharpe_ratio"))
    # Map to [-1, 1]: sharpe_bad → -1, 0 → ~0, sharpe_good → +1
    if sharpe <= cfg.sharpe_bad:
        sharpe_score = -1.0
    elif sharpe >= cfg.sharpe_good:
        sharpe_score = 1.0
    else:
        sharpe_score = (sharpe - cfg.sharpe_bad) / (cfg.sharpe_good - cfg.sharpe_bad) * 2 - 1
    components["sharpe"] = sharpe_score * cfg.w_sharpe

    # ── 4. Sortino ratio ───────────────────────────────────────
    sortino = _safe_float(metrics.get("sortino_ratio"))
    sortino_score = _clamp(sortino / 2.0)
    components["sortino"] = sortino_score * cfg.w_sortino

    # ── 5. Calmar ratio ────────────────────────────────────────
    calmar = _safe_float(metrics.get("calmar_ratio"))
    calmar_score = _clamp(calmar / 3.0)
    components["calmar"] = calmar_score * cfg.w_calmar

    # ── 6. Max drawdown (penalty) ──────────────────────────────
    max_dd = abs(_safe_float(metrics.get("max_drawdown")))
    if max_dd <= cfg.dd_threshold:
        dd_score = 1.0  # No penalty
    elif max_dd >= cfg.dd_max:
        dd_score = -1.0
    else:
        # Linear interpolation between threshold and max
        dd_score = 1.0 - 2.0 * (max_dd - cfg.dd_threshold) / (cfg.dd_max - cfg.dd_threshold)
    components["drawdown"] = dd_score * cfg.w_drawdown

    # ── 7. Max consecutive losses (penalty) ────────────────────
    max_cl = int(metrics.get("max_consecutive_losses", 0))
    # 0-2 losses = no penalty, 10+ = max penalty
    cl_score = _clamp(1.0 - max_cl / 5.0)
    components["consecutive_losses"] = cl_score * cfg.w_consecutive

    # ── 8. Walk-forward robustness ────────────────────────────
    if walkforward:
        is_robust = walkforward.get("is_robust", False)
        overfit = float(walkforward.get("overfitting_score", 0))
        wf_score = (1.0 if is_robust else 0.0) - _clamp(overfit / 0.20)
    else:
        wf_score = 0.0  # Neutral if no walk-forward data
    components["walkforward"] = wf_score * cfg.w_walkforward

    # ── Total reward ───────────────────────────────────────────
    total = sum(components.values())
    total = _clamp(total)

    # ── Grade ──────────────────────────────────────────────────
    if total >= 0.6:
        grade = "A+"
    elif total >= 0.4:
        grade = "A"
    elif total >= 0.2:
        grade = "B"
    elif total >= 0.0:
        grade = "C"
    elif total >= -0.2:
        grade = "D"
    else:
        grade = "F"

    # ── Feedback text ──────────────────────────────────────────
    feedback_parts: list[str] = []
    if ret_score > 0.3:
        feedback_parts.append(f"收益率{total_return:.2%}表现良好")
    elif ret_score < -0.3:
        feedback_parts.append(f"收益率{total_return:.2%}较差")

    if alpha_score > 0.2:
        feedback_parts.append(f"Alpha{alpha:+.2%}跑赢基准")
    elif alpha_score < -0.2:
        feedback_parts.append(f"Alpha{alpha:+.2%}跑输基准")

    if sharpe_score > 0.3:
        feedback_parts.append(f"Sharpe {sharpe:.2f}风险调整收益优秀")
    elif sharpe_score < -0.3:
        feedback_parts.append(f"Sharpe {sharpe:.2f}风险调整收益不足")

    if dd_score < 0:
        feedback_parts.append(f"最大回撤{max_dd:.2%}偏高，需加强风控")

    if walkforward:
        if not is_robust:
            feedback_parts.append("Walk-Forward检测到过拟合风险")
        elif overfit < 0.05:
            feedback_parts.append("策略稳健性良好")

    feedback = "；".join(feedback_parts) if feedback_parts else "策略表现中等，无明显优势或劣势"

    return RewardBreakdown(
        total=round(total, 4),
        components={k: round(v, 4) for k, v in components.items()},
        grade=grade,
        feedback=feedback,
    )


def compare_strategies(
    metrics_a: dict,
    metrics_b: dict,
    config: RewardConfig | None = None,
) -> tuple[RewardBreakdown, RewardBreakdown, int]:
    """Compare two strategies and return which is better.

    Returns:
        (reward_a, reward_b, preference) where preference is:
          1 if A is better, -1 if B is better, 0 if tie
    """
    ra = compute_reward(metrics_a, config=config)
    rb = compute_reward(metrics_b, config=config)

    # Use a small margin to avoid ties
    margin = 0.02
    if ra.total > rb.total + margin:
        pref = 1
    elif rb.total > ra.total + margin:
        pref = -1
    else:
        pref = 0

    return ra, rb, pref
