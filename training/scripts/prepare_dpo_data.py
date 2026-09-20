"""Generate DPO (Direct Preference Optimization) training data from backtest rewards.

Reads the semantic memory's strategy_stats (which includes reward scores) and
constructs preference pairs: (prompt, chosen=high-reward DSL, rejected=low-reward DSL).

Output: training/data/processed/dpo_train.jsonl
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_FILE = PROJECT_ROOT / "training" / "data" / "processed" / "dpo_train.jsonl"


def generate_dpo_from_reward_pairs(pairs: list[dict]) -> int:
    """Write DPO pairs to JSONL file.

    Each pair has:
        prompt: user request
        chosen: high-reward strategy DSL
        rejected: low-reward strategy DSL
    """
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with open(OUTPUT_FILE, "w") as f:
        for pair in pairs:
            if pair.get("preference_strength", 0) < 0.05:
                continue
            entry = {
                "prompt": pair["prompt"],
                "chosen": pair["chosen"],
                "rejected": pair["rejected"],
                "chosen_reward": pair.get("chosen_reward", 0),
                "rejected_reward": pair.get("rejected_reward", 0),
                "preference_strength": pair.get("preference_strength", 0),
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            count += 1

    return count


def generate_dpo_from_memory(memory_dir: str = "~/.agent_memory") -> int:
    """Read semantic memory and generate DPO pairs from strategy stats.

    This reads the persisted semantic_memory.json and constructs preference
    pairs by comparing high-reward vs low-reward strategies.
    """
    memory_path = os.path.expanduser(os.path.join(memory_dir, "semantic_memory.json"))

    if not os.path.exists(memory_path):
        print(f"No semantic memory found at {memory_path}")
        print("Run the agent first to accumulate strategy stats with rewards.")
        return 0

    with open(memory_path) as f:
        data = json.load(f)

    stats = data.get("strategy_stats", [])
    if len(stats) < 2:
        print(f"Not enough strategy stats ({len(stats)} found, need ≥2)")
        return 0

    # Sort by reward
    stats_with_reward = [s for s in stats if "reward" in s]
    stats_with_reward.sort(key=lambda s: s.get("reward", 0), reverse=True)

    # Generate pairs: top vs bottom, adjacent pairs
    pairs = []
    n = len(stats_with_reward)

    # Top vs bottom pairs
    for i in range(min(n // 2, 10)):
        good = stats_with_reward[i]
        bad = stats_with_reward[n - 1 - i]
        if good.get("reward", 0) - bad.get("reward", 0) > 0.05:
            pairs.append({
                "prompt": f"Generate a trading strategy with good risk-adjusted return",
                "chosen": good.get("dsl", json.dumps({"strategy": {"name": good.get("strategy_name", "")}})),
                "rejected": bad.get("dsl", json.dumps({"strategy": {"name": bad.get("strategy_name", "")}})),
                "chosen_reward": good.get("reward", 0),
                "rejected_reward": bad.get("reward", 0),
                "preference_strength": abs(good.get("reward", 0) - bad.get("reward", 0)),
            })

    return generate_dpo_from_reward_pairs(pairs)


if __name__ == "__main__":
    count = generate_dpo_from_memory()
    if count > 0:
        print(f"✅ Generated {count} DPO pairs → {OUTPUT_FILE}")
    else:
        print("No DPO pairs generated. Run the agent with RL feedback first.")
