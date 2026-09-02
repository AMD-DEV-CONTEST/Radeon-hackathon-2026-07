"""Command-line dry run for RadeonHome planning and Policy decisions."""

from __future__ import annotations

import argparse
import json

from .language import DEFAULT_INSTRUCTION, parse_instruction
from .models import FailureType
from .policy import HeuristicGraspPolicy, generate_candidates
from .recovery import decide_recovery


def main() -> None:
    parser = argparse.ArgumentParser(description="Dry-run the RadeonHome planner")
    parser.add_argument("instruction", nargs="?", default=DEFAULT_INSTRUCTION)
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()

    plan = parse_instruction(args.instruction)
    print("TASK PLAN")
    print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))

    policy = HeuristicGraspPolicy()
    ranked = policy.rank(generate_candidates(obstacle_clearance_m=0.14))
    print("\nTOP GRASP CANDIDATES")
    for index, item in enumerate(ranked[: args.top_k], start=1):
        print(
            f"{index}. score={item.score:.3f} "
            f"offset=({item.candidate.offset_x_m:+.3f}, "
            f"{item.candidate.offset_y_m:+.3f}) "
            f"yaw={item.candidate.yaw_deg:+.0f}°"
        )

    print("\nRECOVERY EXAMPLES")
    for failure in FailureType:
        decision = decide_recovery(failure, attempt=1)
        print(f"- {failure.value}: {decision.action}")


if __name__ == "__main__":
    main()

