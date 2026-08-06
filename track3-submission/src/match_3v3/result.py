"""Match result and scoreboard for multi-robot soccer matches.

Defines the JSON schema for match outputs and provides aggregation utilities.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict, field
from typing import Optional


@dataclass
class ScoreBoard:
    """Live score tracking during a match."""
    left_score: int = 0
    right_score: int = 0
    step: int = 0
    match_over: bool = False

    # Per-match stats
    left_falls: int = 0
    right_falls: int = 0
    left_recoveries: int = 0
    right_recoveries: int = 0
    left_shots: int = 0
    right_shots: int = 0
    left_shots_on_target: int = 0
    right_shots_on_target: int = 0
    ball_out_of_bounds: int = 0

    def record_goal(self, team: str):
        """Record a goal. team is 'left' or 'right'."""
        if team == "left":
            self.left_score += 1
        else:
            self.right_score += 1

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MatchResult:
    """Single match result — the JSON schema for match output.

    Fields are designed to be directly serializable to JSON and CSV.
    Left team perspective: goals_for = left_score, goals_against = right_score.
    """
    match_id: int
    method: str = "rule_vs_rule"
    left_score: int = 0
    right_score: int = 0
    left_falls: int = 0
    right_falls: int = 0
    left_recoveries: int = 0
    right_recoveries: int = 0
    left_shots: int = 0
    right_shots: int = 0
    left_shots_on_target: int = 0
    right_shots_on_target: int = 0
    ball_out_count: int = 0
    total_steps: int = 0
    match_duration_s: float = 0.0
    winner: str = "draw"        # "left", "right", "draw"
    seed: int = 0

    # --- Derived properties (left team perspective) ---

    @property
    def goals_for(self) -> int:
        return self.left_score

    @property
    def goals_against(self) -> int:
        return self.right_score

    @property
    def goal_diff(self) -> int:
        return self.left_score - self.right_score

    @property
    def fallen_count(self) -> int:
        return self.left_falls + self.right_falls

    @property
    def recovery_count(self) -> int:
        return self.left_recoveries + self.right_recoveries

    # --- Serialization ---

    def to_dict(self) -> dict:
        """Full dict including derived fields."""
        d = asdict(self)
        d["goals_for"] = self.goals_for
        d["goals_against"] = self.goals_against
        d["goal_diff"] = self.goal_diff
        d["fallen_count"] = self.fallen_count
        d["recovery_count"] = self.recovery_count
        return d

    def to_csv_row(self) -> str:
        d = self.to_dict()
        return ",".join(str(v) for v in d.values())

    @staticmethod
    def csv_header() -> str:
        fields = [
            "match_id", "method", "left_score", "right_score",
            "left_falls", "right_falls", "left_recoveries", "right_recoveries",
            "left_shots", "right_shots", "left_shots_on_target", "right_shots_on_target",
            "ball_out_count", "total_steps", "match_duration_s",
            "winner", "seed",
            "goals_for", "goals_against", "goal_diff",
            "fallen_count", "recovery_count",
        ]
        return ",".join(fields)

    @staticmethod
    def expected_json_keys() -> set:
        """Return the set of all keys in the match result JSON schema.

        Used by tests to validate schema completeness.
        """
        return {
            "match_id", "method", "left_score", "right_score",
            "left_falls", "right_falls", "left_recoveries", "right_recoveries",
            "left_shots", "right_shots", "left_shots_on_target", "right_shots_on_target",
            "ball_out_count", "total_steps", "match_duration_s",
            "winner", "seed",
            "goals_for", "goals_against", "goal_diff",
            "fallen_count", "recovery_count",
        }


@dataclass
class MatchSummary:
    """Aggregate statistics across multiple matches."""
    n_matches: int = 0
    method: str = "rule_vs_rule"
    left_wins: int = 0
    right_wins: int = 0
    draws: int = 0
    avg_goals_for: float = 0.0
    avg_goals_against: float = 0.0
    avg_goal_diff: float = 0.0
    avg_fallen_count: float = 0.0
    avg_recovery_count: float = 0.0
    avg_match_duration: float = 0.0
    left_win_rate: float = 0.0
    right_win_rate: float = 0.0
    draw_rate: float = 0.0
    recovery_rate: float = 0.0

    @staticmethod
    def from_results(results: list[MatchResult]) -> "MatchSummary":
        n = len(results)
        if n == 0:
            return MatchSummary()

        left_wins = sum(1 for r in results if r.winner == "left")
        right_wins = sum(1 for r in results if r.winner == "right")
        draws = sum(1 for r in results if r.winner == "draw")
        total_falls = sum(r.fallen_count for r in results)
        total_recoveries = sum(r.recovery_count for r in results)

        return MatchSummary(
            n_matches=n,
            method=results[0].method,
            left_wins=left_wins,
            right_wins=right_wins,
            draws=draws,
            avg_goals_for=sum(r.goals_for for r in results) / n,
            avg_goals_against=sum(r.goals_against for r in results) / n,
            avg_goal_diff=sum(r.goal_diff for r in results) / n,
            avg_fallen_count=sum(r.fallen_count for r in results) / n,
            avg_recovery_count=sum(r.recovery_count for r in results) / n,
            avg_match_duration=sum(r.match_duration_s for r in results) / n,
            left_win_rate=left_wins / n,
            right_win_rate=right_wins / n,
            draw_rate=draws / n,
            recovery_rate=total_recoveries / max(total_falls, 1),
        )

    def to_dict(self) -> dict:
        return asdict(self)
