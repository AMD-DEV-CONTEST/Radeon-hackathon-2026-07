"""RL feedback loop — connects reward computation to agent behavior.

Three feedback layers:
  L1 (Immediate): After backtest, compute reward and inject into the
     current session's prompt so the LLM can adapt its next action.
  L2 (Experience): Extract positive/negative patterns from high/low
     reward strategies, write to SemanticMemory as experience rules.
  L3 (DPO Data): Record (chosen, rejected) strategy pairs based on
     reward ranking for later DPO fine-tuning.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from .reward import compute_reward, RewardBreakdown, RewardConfig, compare_strategies


@dataclass
class StrategyRecord:
    """A complete strategy record with reward for RL feedback."""
    dsl: dict
    metrics: dict
    reward: RewardBreakdown
    user_request: str = ""
    timestamp: float = field(default_factory=time.time)


class RLFeedbackLoop:
    """Manages RL feedback across the three layers.

    Usage in the agent loop:
        rl = RLFeedbackLoop()
        # After backtest:
        record = rl.record_strategy(dsl, metrics, user_request)
        # Inject into prompt:
        prompt_context = rl.format_feedback_for_prompt()
        # At session end, extract experience:
        rl.consolidate_to_memory(semantic_memory)
    """

    def __init__(self, config: RewardConfig | None = None):
        self.config = config or RewardConfig()
        self.records: list[StrategyRecord] = []
        self._best: StrategyRecord | None = None
        self._worst: StrategyRecord | None = None
        self._dpo_pairs: list[dict] = []  # For DPO training data

    # ── L1: Immediate feedback ─────────────────────────────────

    def record_strategy(
        self,
        dsl: dict,
        metrics: dict,
        user_request: str = "",
        walkforward: dict | None = None,
    ) -> StrategyRecord:
        """Record a strategy + its backtest metrics + computed reward.

        Called after each backtest in the agent loop.
        """
        reward = compute_reward(metrics, walkforward, self.config)
        record = StrategyRecord(
            dsl=dsl,
            metrics=metrics,
            reward=reward,
            user_request=user_request,
        )
        self.records.append(record)

        # Track best and worst
        if self._best is None or reward.total > self._best.reward.total:
            self._best = record
        if self._worst is None or reward.total < self._worst.reward.total:
            self._worst = record

        # L3: Generate DPO pairs (best vs worst)
        if self._best and self._worst and self._best != self._worst:
            self._dpo_pairs.append({
                "prompt": user_request or "Generate a trading strategy",
                "chosen": json.dumps(self._best.dsl, ensure_ascii=False),
                "rejected": json.dumps(self._worst.dsl, ensure_ascii=False),
                "chosen_reward": self._best.reward.total,
                "rejected_reward": self._worst.reward.total,
                "preference_strength": abs(self._best.reward.total - self._worst.reward.total),
            })

        return record

    def format_feedback_for_prompt(self) -> str:
        """Format RL feedback for injection into the agent's system prompt.

        This is L1 (immediate) feedback — shows the LLM how previous
        strategies performed and what to improve.
        """
        if not self.records:
            return "No prior strategies evaluated yet."

        parts: list[str] = ["## RL Reward Feedback"]

        # Show last strategy's reward
        latest = self.records[-1]
        parts.append(f"### Last Strategy: {latest.dsl.get('strategy', {}).get('name', '?')}")
        parts.append(f"- Reward: {latest.reward.total:+.2f} (Grade: {latest.reward.grade})")
        parts.append(f"- Feedback: {latest.reward.feedback}")

        # Component breakdown
        if latest.reward.components:
            comp_str = ", ".join(
                f"{k}={v:+.3f}" for k, v in latest.reward.components.items()
            )
            parts.append(f"- Components: {comp_str}")

        # Show best/worst if available
        if self._best and len(self.records) > 1:
            parts.append(f"\n### Best Strategy: {self._best.dsl.get('strategy', {}).get('name', '?')}")
            parts.append(f"- Reward: {self._best.reward.total:+.2f}")
            parts.append(f"- Return: {self._best.metrics.get('total_return', 0):.2%}")
            parts.append(f"- Sharpe: {self._best.metrics.get('sharpe_ratio', 0):.2f}")

        if self._worst and len(self.records) > 1:
            parts.append(f"\n### Worst Strategy: {self._worst.dsl.get('strategy', {}).get('name', '?')}")
            parts.append(f"- Reward: {self._worst.reward.total:+.2f}")
            parts.append(f"- Return: {self._worst.metrics.get('total_return', 0):.2%}")

        # Actionable guidance
        if latest.reward.total < 0:
            parts.append("\n⚠️ 上次策略reward为负，建议调整：")
            if latest.reward.components.get("drawdown", 0) < 0:
                parts.append("- 收紧止损距离，降低最大回撤")
            if latest.reward.components.get("sharpe", 0) < 0:
                parts.append("- 增加过滤条件，提高风险调整收益")
            if latest.reward.components.get("alpha", 0) < 0:
                parts.append("- 策略未跑赢基准，考虑更换指标组合")
        elif latest.reward.total > 0.3:
            parts.append("\n✅ 上次策略表现良好，可参考类似参数继续优化")

        return "\n".join(parts)

    # ── L2: Experience extraction ──────────────────────────────

    def extract_experience_rules(self) -> list[str]:
        """Extract positive/negative experience rules from reward history.

        Called at session end to update SemanticMemory.
        """
        rules: list[str] = []

        if not self.records:
            return rules

        # Positive patterns from high-reward strategies
        good_records = [r for r in self.records if r.reward.total > 0.3]
        for r in good_records[:3]:
            name = r.dsl.get("strategy", {}).get("name", "?")
            timeframe = r.dsl.get("strategy", {}).get("market", {}).get("timeframe", "?")
            indicators = [i.get("type", "?") for i in r.dsl.get("strategy", {}).get("indicators", [])]
            rules.append(
                f"[REWARD={r.reward.total:+.2f}] {name} ({timeframe}, indicators={indicators}) "
                f"return={r.metrics.get('total_return', 0):.2%} "
                f"sharpe={r.metrics.get('sharpe_ratio', 0):.2f} — 此模式表现良好"
            )

        # Negative patterns from low-reward strategies
        bad_records = [r for r in self.records if r.reward.total < -0.2]
        for r in bad_records[:2]:
            name = r.dsl.get("strategy", {}).get("name", "?")
            indicators = [i.get("type", "?") for i in r.dsl.get("strategy", {}).get("indicators", [])]
            rules.append(
                f"[REWARD={r.reward.total:+.2f}] {name} (indicators={indicators}) "
                f"return={r.metrics.get('total_return', 0):.2%} "
                f"max_dd={r.metrics.get('max_drawdown', 0):.2%} — 此模式表现较差，避免类似参数"
            )

        return rules

    # ── L3: DPO training data ──────────────────────────────────

    def get_dpo_pairs(self) -> list[dict]:
        """Return reward-ranked strategy pairs for DPO training.

        Each pair has: prompt, chosen (high reward), rejected (low reward).
        """
        return [p for p in self._dpo_pairs if p["preference_strength"] > 0.05]

    def export_dpo_dataset(self, file_path: str) -> int:
        """Export DPO training pairs to a JSONL file.

        Returns number of pairs written.
        """
        pairs = self.get_dpo_pairs()
        import os
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        with open(file_path, "w") as f:
            for pair in pairs:
                f.write(json.dumps(pair, ensure_ascii=False) + "\n")
        return len(pairs)

    # ── Consolidation ───────────────────────────────────────────

    def consolidate_to_memory(self, semantic_memory: Any) -> None:
        """Extract insights and write to SemanticMemory.

        Called at session end via memory.consolidate().
        """
        # Add reward-weighted experience rules
        rules = self.extract_experience_rules()
        for rule in rules:
            if rule not in semantic_memory.experience_rules:
                semantic_memory.experience_rules.append(rule)

        # Add reward to strategy_stats
        for record in self.records:
            name = record.dsl.get("strategy", {}).get("name", "Unknown")
            semantic_memory.strategy_stats.append({
                "strategy_name": name,
                "pair": record.dsl.get("strategy", {}).get("market", {}).get("pair", ""),
                "total_return": record.metrics.get("total_return", 0),
                "sharpe": record.metrics.get("sharpe_ratio", 0),
                "max_drawdown": record.metrics.get("max_drawdown", 0),
                "win_rate": record.metrics.get("win_rate", 0),
                "reward": record.reward.total,
                "reward_grade": record.reward.grade,
                "ts": record.timestamp,
            })

        semantic_memory._persist()

    # ── Summary ─────────────────────────────────────────────────

    def get_summary(self) -> dict:
        """Return a summary of all strategies evaluated."""
        if not self.records:
            return {"total_strategies": 0, "avg_reward": 0.0, "best_reward": 0.0, "worst_reward": 0.0}

        rewards = [r.reward.total for r in self.records]
        return {
            "total_strategies": len(self.records),
            "avg_reward": round(sum(rewards) / len(rewards), 4),
            "best_reward": round(max(rewards), 4),
            "worst_reward": round(min(rewards), 4),
            "dpo_pairs": len(self.get_dpo_pairs()),
            "grades": {r.reward.grade: 1 for r in self.records if r.reward.grade},
        }
