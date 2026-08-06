"""Multi-agent observation features for multi-robot — pure numpy, CPU-testable.

The single-agent hierarchical policy uses a 19-dim observation that contains
only *ball + self*. For multi-robot it must also see teammates and opponents. This
module computes the extra per-player features as a pure function so they can be
unit-tested without Genesis, then concatenated onto the 19-dim base.

Extra features (5 dims), all in the robot body frame:

    nearest_teammate_rel(2)   — xy of the closest teammate relative to self
    nearest_opponent_rel(2)   — xy of the closest opponent relative to self
    possession_flag(1)        — +1 if my team possesses, -1 if opponents, 0 loose

Total observation becomes 19 + 5 = 24 dims. These are appended *after* the base
19 so a policy trained without them is untouched (feature flag off), and a new
policy can be trained with them on (feature flag on).
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from .scene import Team, PlayerState, BallState
from .strategy import world_to_body, Possession

N_EXTRA = 5  # teammate_rel(2) + opponent_rel(2) + possession_flag(1)


def compute_multiagent_features(
    player: PlayerState,
    players: list[PlayerState],
    possession: Possession,
) -> np.ndarray:
    """Return the 5-dim multi-agent feature vector for ``player``.

    Parameters
    ----------
    player : PlayerState
        The robot these features describe.
    players : list[PlayerState]
        All players on the field (both teams), including ``player``.
    possession : Possession
        Current possession estimate (from ``PossessionTracker``).

    Returns
    -------
    np.ndarray, shape (5,), dtype float32
        [tm_fwd, tm_left, opp_fwd, opp_left, possession_flag].
        Missing teammate/opponent yields a large sentinel distance (30 m) so the
        policy sees "nobody there" rather than a zero that looks like "on top of me".
    """
    yaw = player.yaw
    teammates = [p for p in players if p.team == player.team and p.robot_idx != player.robot_idx]
    opponents = [p for p in players if p.team != player.team]

    def nearest_rel(candidates) -> np.ndarray:
        if not candidates:
            return np.array([30.0, 0.0])  # sentinel: nobody in range
        closest = min(candidates, key=lambda p: float(np.linalg.norm(p.pos[:2] - player.pos[:2])))
        return world_to_body(closest.pos[:2] - player.pos[:2], yaw)

    tm_rel = nearest_rel(teammates)
    opp_rel = nearest_rel(opponents)

    if possession.team is None:
        flag = 0.0
    elif possession.team == player.team:
        flag = 1.0
    else:
        flag = -1.0

    feats = np.concatenate([tm_rel, opp_rel, [flag]]).astype(np.float32)
    assert feats.shape == (N_EXTRA,), f"multi-agent feats must be {N_EXTRA}-dim, got {feats.shape}"
    return feats


def build_full_observation(
    base_obs_19: np.ndarray,
    player: PlayerState,
    players: list[PlayerState],
    possession: Possession,
) -> np.ndarray:
    """Concatenate the base 19-dim observation with the 5-dim multi-agent features.

    Returns a 24-dim float32 vector. Validates input shape to catch wiring bugs.
    """
    base = np.asarray(base_obs_19, dtype=np.float32).reshape(-1)
    assert base.shape == (19,), f"base obs must be 19-dim, got {base.shape}"
    extra = compute_multiagent_features(player, players, possession)
    full = np.concatenate([base, extra]).astype(np.float32)
    assert full.shape == (24,), f"full obs must be 24-dim, got {full.shape}"
    return full
