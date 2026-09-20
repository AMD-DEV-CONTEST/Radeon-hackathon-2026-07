"""Tests for the RL reward system and feedback loop.

Covers:
- Reward computation: all components, edge cases, clamping
- RewardBreakdown: grades, feedback text
- compare_strategies: preference direction
- RLFeedbackLoop: recording, prompt formatting, experience extraction, DPO pairs
- Memory integration: consolidation to semantic memory
"""

from __future__ import annotations

import json

import pytest

from src.agent.reward import (
    compute_reward,
    RewardConfig,
    RewardBreakdown,
    compare_strategies,
)
from src.agent.rl_feedback import RLFeedbackLoop, StrategyRecord


# ── Reward computation tests ───────────────────────────────────────


class TestComputeReward:
    def test_excellent_strategy(self):
        """High return, high Sharpe, low drawdown → high reward."""
        metrics = {
            "total_return": 0.25,
            "sharpe_ratio": 2.5,
            "sortino_ratio": 3.0,
            "calmar_ratio": 2.0,
            "max_drawdown": -0.05,
            "max_consecutive_losses": 2,
            "alpha": 0.08,
        }
        reward = compute_reward(metrics)
        assert reward.total > 0.5
        assert reward.grade in ("A", "A+")
        assert "良好" in reward.feedback or "优秀" in reward.feedback

    def test_terrible_strategy(self):
        """Large loss, negative Sharpe, high drawdown → negative reward."""
        metrics = {
            "total_return": -0.30,
            "sharpe_ratio": -1.0,
            "sortino_ratio": -1.5,
            "calmar_ratio": -0.5,
            "max_drawdown": -0.45,
            "max_consecutive_losses": 8,
            "alpha": -0.15,
        }
        reward = compute_reward(metrics)
        assert reward.total < -0.3
        assert reward.grade in ("D", "F")
        assert "差" in reward.feedback or "不足" in reward.feedback

    def test_neutral_strategy(self):
        """Break-even → near-zero reward."""
        metrics = {
            "total_return": 0.01,
            "sharpe_ratio": 0.1,
            "sortino_ratio": 0.15,
            "calmar_ratio": 0.1,
            "max_drawdown": -0.05,
            "max_consecutive_losses": 3,
            "alpha": 0.0,
        }
        reward = compute_reward(metrics)
        assert -0.2 < reward.total < 0.2
        assert reward.grade in ("B", "C")

    def test_reward_is_clamped(self):
        """Reward should always be in [-1, 1]."""
        extreme_metrics = {
            "total_return": 10.0,  # 1000%
            "sharpe_ratio": 100.0,
            "sortino_ratio": 100.0,
            "calmar_ratio": 100.0,
            "max_drawdown": 0.0,
            "max_consecutive_losses": 0,
            "alpha": 10.0,
        }
        reward = compute_reward(extreme_metrics)
        assert reward.total <= 1.0

    def test_reward_components_sum(self):
        """Component values should roughly sum to total."""
        metrics = {
            "total_return": 0.15,
            "sharpe_ratio": 1.5,
            "sortino_ratio": 2.0,
            "calmar_ratio": 1.0,
            "max_drawdown": -0.10,
            "max_consecutive_losses": 3,
            "alpha": 0.05,
        }
        reward = compute_reward(metrics)
        component_sum = sum(reward.components.values())
        assert abs(component_sum - reward.total) < 0.01

    def test_walkforward_robust(self):
        """Walk-forward robust strategy gets bonus."""
        metrics = {
            "total_return": 0.10,
            "sharpe_ratio": 1.0,
            "sortino_ratio": 1.5,
            "calmar_ratio": 0.8,
            "max_drawdown": -0.08,
            "max_consecutive_losses": 3,
            "alpha": 0.02,
        }
        wf_robust = {"is_robust": True, "overfitting_score": 0.02}
        wf_overfit = {"is_robust": False, "overfitting_score": 0.15}

        r_robust = compute_reward(metrics, walkforward=wf_robust)
        r_overfit = compute_reward(metrics, walkforward=wf_overfit)

        assert r_robust.total > r_overfit.total

    def test_high_drawdown_penalized(self):
        """High drawdown should reduce reward."""
        base = {
            "total_return": 0.10,
            "sharpe_ratio": 1.0,
            "sortino_ratio": 1.5,
            "calmar_ratio": 0.8,
            "max_consecutive_losses": 3,
            "alpha": 0.02,
        }
        low_dd = {**base, "max_drawdown": -0.05}
        high_dd = {**base, "max_drawdown": -0.40}

        r_low = compute_reward(low_dd)
        r_high = compute_reward(high_dd)

        assert r_low.total > r_high.total
        assert r_high.components["drawdown"] < r_low.components["drawdown"]

    def test_custom_config(self):
        """Custom config changes weights."""
        cfg = RewardConfig(w_return=0.5, w_alpha=0.5, w_sharpe=0, w_sortino=0,
                           w_calmar=0, w_drawdown=0, w_consecutive=0, w_walkforward=0)
        metrics = {"total_return": 0.20, "alpha": 0.05, "sharpe_ratio": 100.0,
                   "max_drawdown": -0.50, "max_consecutive_losses": 20}
        reward = compute_reward(metrics, config=cfg)
        # Only return and alpha matter
        assert "return" in reward.components
        assert "alpha" in reward.components
        # Sharpe/drawdown should contribute 0
        assert abs(reward.components.get("sharpe", 0)) < 0.001


class TestRewardBreakdown:
    def test_grade_assignment(self):
        assert compute_reward({"total_return": 0.30, "sharpe_ratio": 3.0, "alpha": 0.10,
                              "sortino_ratio": 3.5, "calmar_ratio": 2.5,
                              "max_drawdown": -0.03, "max_consecutive_losses": 1}).grade == "A+"
        assert compute_reward({"total_return": -0.40, "sharpe_ratio": -2.0, "alpha": -0.20,
                              "sortino_ratio": -2.5, "calmar_ratio": -1.0,
                              "max_drawdown": -0.50, "max_consecutive_losses": 10}).grade == "F"

    def test_feedback_contains_metrics(self):
        metrics = {"total_return": 0.20, "sharpe_ratio": 2.0, "alpha": 0.10,
                   "sortino_ratio": 2.5, "calmar_ratio": 1.5,
                   "max_drawdown": -0.05, "max_consecutive_losses": 2}
        reward = compute_reward(metrics)
        assert "20.00%" in reward.feedback or "20.0%" in reward.feedback
        assert "2.00" in reward.feedback

    def test_float_conversion(self):
        """RewardBreakdown should be usable as float."""
        reward = compute_reward({"total_return": 0.1, "sharpe_ratio": 1.0,
                                  "alpha": 0.02, "sortino_ratio": 1.5,
                                  "calmar_ratio": 0.8, "max_drawdown": -0.08,
                                  "max_consecutive_losses": 3})
        assert isinstance(float(reward), float)


# ── compare_strategies tests ───────────────────────────────────────


class TestCompareStrategies:
    def test_better_strategy_wins(self):
        good = {"total_return": 0.20, "sharpe_ratio": 2.0, "alpha": 0.10,
                "sortino_ratio": 2.5, "calmar_ratio": 1.5,
                "max_drawdown": -0.05, "max_consecutive_losses": 2}
        bad = {"total_return": -0.10, "sharpe_ratio": -0.5, "alpha": -0.08,
               "sortino_ratio": -0.7, "calmar_ratio": -0.3,
               "max_drawdown": -0.25, "max_consecutive_losses": 6}
        ra, rb, pref = compare_strategies(good, bad)
        assert pref == 1  # A is better
        assert ra.total > rb.total

    def test_similar_strategies_tie(self):
        a = {"total_return": 0.10, "sharpe_ratio": 1.0, "alpha": 0.02,
             "sortino_ratio": 1.5, "calmar_ratio": 0.8,
             "max_drawdown": -0.08, "max_consecutive_losses": 3}
        # Near-identical — difference within margin (0.02)
        b = {"total_return": 0.10, "sharpe_ratio": 1.0, "alpha": 0.02,
             "sortino_ratio": 1.5, "calmar_ratio": 0.8,
             "max_drawdown": -0.08, "max_consecutive_losses": 3}
        _, _, pref = compare_strategies(a, b)
        assert pref == 0  # Tie — identical strategies


# ── RLFeedbackLoop tests ───────────────────────────────────────────


class TestRLFeedbackLoop:
    def test_record_strategy(self):
        rl = RLFeedbackLoop()
        dsl = {"strategy": {"name": "TestEMA", "market": {"pair": "BTC/USDT", "timeframe": "1h"}}}
        metrics = {"total_return": 0.15, "sharpe_ratio": 1.5, "alpha": 0.05,
                   "sortino_ratio": 2.0, "calmar_ratio": 1.0,
                   "max_drawdown": -0.08, "max_consecutive_losses": 3}
        record = rl.record_strategy(dsl, metrics, "Create EMA strategy")
        assert record.reward.total > 0
        assert len(rl.records) == 1

    def test_best_worst_tracking(self):
        rl = RLFeedbackLoop()
        good_dsl = {"strategy": {"name": "Good"}}
        bad_dsl = {"strategy": {"name": "Bad"}}
        good_metrics = {"total_return": 0.20, "sharpe_ratio": 2.0, "alpha": 0.10,
                        "sortino_ratio": 2.5, "calmar_ratio": 1.5,
                        "max_drawdown": -0.05, "max_consecutive_losses": 2}
        bad_metrics = {"total_return": -0.15, "sharpe_ratio": -0.8, "alpha": -0.10,
                       "sortino_ratio": -1.0, "calmar_ratio": -0.5,
                       "max_drawdown": -0.30, "max_consecutive_losses": 7}

        rl.record_strategy(good_dsl, good_metrics)
        rl.record_strategy(bad_dsl, bad_metrics)

        assert rl._best.dsl["strategy"]["name"] == "Good"
        assert rl._worst.dsl["strategy"]["name"] == "Bad"

    def test_format_feedback_empty(self):
        rl = RLFeedbackLoop()
        result = rl.format_feedback_for_prompt()
        assert "No prior" in result

    def test_format_feedback_with_data(self):
        rl = RLFeedbackLoop()
        dsl = {"strategy": {"name": "TestStrategy", "market": {"pair": "BTC/USDT"}}}
        metrics = {"total_return": 0.15, "sharpe_ratio": 1.5, "alpha": 0.05,
                   "sortino_ratio": 2.0, "calmar_ratio": 1.0,
                   "max_drawdown": -0.08, "max_consecutive_losses": 3}
        rl.record_strategy(dsl, metrics, "Test request")

        feedback = rl.format_feedback_for_prompt()
        assert "TestStrategy" in feedback
        assert "Reward" in feedback
        assert "Grade" in feedback

    def test_format_feedback_negative_reward(self):
        rl = RLFeedbackLoop()
        dsl = {"strategy": {"name": "BadStrategy"}}
        metrics = {"total_return": -0.15, "sharpe_ratio": -0.5, "alpha": -0.08,
                   "sortino_ratio": -0.7, "calmar_ratio": -0.3,
                   "max_drawdown": -0.25, "max_consecutive_losses": 6}
        rl.record_strategy(dsl, metrics, "Test")

        feedback = rl.format_feedback_for_prompt()
        assert "建议调整" in feedback or "⚠️" in feedback

    def test_dpo_pairs_generation(self):
        rl = RLFeedbackLoop()
        good_dsl = {"strategy": {"name": "Good", "indicators": [{"type": "EMA"}]}}
        bad_dsl = {"strategy": {"name": "Bad", "indicators": [{"type": "RSI"}]}}
        good_metrics = {"total_return": 0.20, "sharpe_ratio": 2.0, "alpha": 0.10,
                        "sortino_ratio": 2.5, "calmar_ratio": 1.5,
                        "max_drawdown": -0.05, "max_consecutive_losses": 2}
        bad_metrics = {"total_return": -0.15, "sharpe_ratio": -0.8, "alpha": -0.10,
                       "sortino_ratio": -1.0, "calmar_ratio": -0.5,
                       "max_drawdown": -0.30, "max_consecutive_losses": 7}

        rl.record_strategy(good_dsl, good_metrics, "Create strategy")
        rl.record_strategy(bad_dsl, bad_metrics, "Create strategy")

        pairs = rl.get_dpo_pairs()
        assert len(pairs) > 0
        assert pairs[0]["chosen_reward"] > pairs[0]["rejected_reward"]

    def test_extract_experience_rules(self):
        rl = RLFeedbackLoop()
        good_dsl = {"strategy": {"name": "GoodEMA", "market": {"timeframe": "1h"},
                                 "indicators": [{"type": "EMA"}, {"type": "RSI"}]}}
        bad_dsl = {"strategy": {"name": "BadMACD", "market": {"timeframe": "4h"},
                                "indicators": [{"type": "MACD"}]}}
        good_metrics = {"total_return": 0.20, "sharpe_ratio": 2.0, "alpha": 0.10,
                        "sortino_ratio": 2.5, "calmar_ratio": 1.5,
                        "max_drawdown": -0.05, "max_consecutive_losses": 2}
        bad_metrics = {"total_return": -0.15, "sharpe_ratio": -0.8, "alpha": -0.10,
                       "sortino_ratio": -1.0, "calmar_ratio": -0.5,
                       "max_drawdown": -0.30, "max_consecutive_losses": 7}

        rl.record_strategy(good_dsl, good_metrics)
        rl.record_strategy(bad_dsl, bad_metrics)

        rules = rl.extract_experience_rules()
        assert len(rules) > 0
        assert any("GoodEMA" in r and "良好" in r for r in rules)
        assert any("BadMACD" in r and "较差" in r for r in rules)

    def test_get_summary(self):
        rl = RLFeedbackLoop()
        for ret in [0.1, -0.05, 0.15]:
            rl.record_strategy(
                {"strategy": {"name": f"S{ret}"}},
                {"total_return": ret, "sharpe_ratio": 1.0, "alpha": 0.02,
                 "sortino_ratio": 1.5, "calmar_ratio": 0.8,
                 "max_drawdown": -0.08, "max_consecutive_losses": 3}
            )
        summary = rl.get_summary()
        assert summary["total_strategies"] == 3
        assert summary["best_reward"] > summary["worst_reward"]

    def test_export_dpo_dataset(self, tmp_path):
        rl = RLFeedbackLoop()
        good_dsl = {"strategy": {"name": "Good"}}
        bad_dsl = {"strategy": {"name": "Bad"}}
        good_metrics = {"total_return": 0.20, "sharpe_ratio": 2.0, "alpha": 0.10,
                        "sortino_ratio": 2.5, "calmar_ratio": 1.5,
                        "max_drawdown": -0.05, "max_consecutive_losses": 2}
        bad_metrics = {"total_return": -0.15, "sharpe_ratio": -0.8, "alpha": -0.10,
                       "sortino_ratio": -1.0, "calmar_ratio": -0.5,
                       "max_drawdown": -0.30, "max_consecutive_losses": 7}

        rl.record_strategy(good_dsl, good_metrics, "Test prompt")
        rl.record_strategy(bad_dsl, bad_metrics, "Test prompt")

        f = str(tmp_path / "dpo.jsonl")
        count = rl.export_dpo_dataset(f)
        assert count > 0

        import os
        assert os.path.exists(f)
        with open(f) as fp:
            lines = fp.readlines()
        assert len(lines) == count
        data = json.loads(lines[0])
        assert "prompt" in data
        assert "chosen" in data
        assert "rejected" in data

    def test_consolidate_to_memory(self):
        """RL feedback should write reward-weighted stats to semantic memory."""
        from src.agent.memory import SemanticMemory

        rl = RLFeedbackLoop()
        sm = SemanticMemory()

        dsl = {"strategy": {"name": "TestRL", "market": {"pair": "BTC/USDT"}}}
        metrics = {"total_return": 0.15, "sharpe_ratio": 1.5, "alpha": 0.05,
                   "sortino_ratio": 2.0, "calmar_ratio": 1.0,
                   "max_drawdown": -0.08, "max_consecutive_losses": 3}
        rl.record_strategy(dsl, metrics, "Test")
        rl.consolidate_to_memory(sm)

        assert len(sm.strategy_stats) > 0
        assert sm.strategy_stats[-1].get("reward") is not None
        assert sm.strategy_stats[-1].get("reward_grade") is not None
        assert any("TestRL" in r or "REWARD" in r for r in sm.experience_rules)


class TestAgentStateWithRL:
    def test_state_has_rl_feedback(self):
        from src.agent.core import AgentState
        rl = RLFeedbackLoop()
        state = AgentState(user_goal="test", rl_feedback=rl)
        assert state.rl_feedback is rl
        assert state.rl_feedback.records == []
