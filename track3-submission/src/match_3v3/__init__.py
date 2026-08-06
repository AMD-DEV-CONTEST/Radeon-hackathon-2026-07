"""multi-robot soccer match environment — scene, roles, policies, and evaluation.

This package defines the code skeleton for 6-robot (multi-robot) soccer matches.
It does NOT require Genesis or GPU for import or unit-level testing.

Modules:
    scene   — Scene3v3: builds 6 T1 entities + ball + goals, holds entity handles.
    roles   — RoleAssigner: attacker/defender/goalkeeper assignment via fixed rules.
    policy  — RulePolicy and SharedRLPolicy with a unified action interface.
"""
from __future__ import annotations

from .roles import Role, Team, RoleAssignment, RoleAssigner
from .policy import PolicyAction, RulePolicy, SharedRLPolicy
from .scene import Scene3v3, SceneConfig, FieldConstants, DEFAULT_FIELD, PlayerState, BallState
from .result import MatchResult, MatchSummary, ScoreBoard
from .strategy import (
    Possession, PossessionTracker, SmartRoleAssigner, FormationTargets,
    PassDecision, PassPlanner, TeamBrain, PlayerCommand,
    build_hl_observation, world_to_body, normalize_angle,
)
from .multiagent_obs import compute_multiagent_features, build_full_observation, N_EXTRA

__all__ = [
    "Role", "Team", "RoleAssignment", "RoleAssigner",
    "PolicyAction", "RulePolicy", "SharedRLPolicy",
    "Scene3v3", "SceneConfig", "FieldConstants", "DEFAULT_FIELD", "PlayerState", "BallState",
    "MatchResult", "MatchSummary", "ScoreBoard",
    # strategy brain
    "Possession", "PossessionTracker", "SmartRoleAssigner", "FormationTargets",
    "PassDecision", "PassPlanner", "TeamBrain", "PlayerCommand",
    "build_hl_observation", "world_to_body", "normalize_angle",
    # multi-agent observation
    "compute_multiagent_features", "build_full_observation", "N_EXTRA",
]
