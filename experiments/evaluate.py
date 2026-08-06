"""Evaluate IK and learned-policy variants by task success rate."""

from __future__ import annotations

from typing import Any, Callable


def evaluate_success_rate(env: Any, action_fn: Callable[[dict], Any], episodes: int = 100) -> dict[str, float]:
    successes = 0
    for _ in range(episodes):
        observation, _ = env.reset()
        done = False
        info: dict[str, Any] = {}
        while not done:
            observation, _, terminated, truncated, info = env.step(action_fn(observation))
            done = terminated or truncated
        successes += bool(info.get("is_success", False))
    return {"success_rate": successes / episodes}


def compare_policies(env_factory: Callable[[], Any], policies: dict[str, Callable[[dict], Any]], episodes: int = 100) -> dict[str, dict[str, float]]:
    """Experiment 1/2: evaluate IK and each residual-policy ablation."""
    return {name: evaluate_success_rate(env_factory(), policy, episodes) for name, policy in policies.items()}
