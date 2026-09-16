"""Rebuild canonical cards from saved cloud VLM evidence using deterministic tools."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.critic import PlanCritic
from src.agent.field_plan import build_field_plan
from src.tools.pose_card_renderer import render_pose_card
from src.vision.pose_analyzer import PoseAnalyzer


CASES = (
    "01_single_with_phone",
    "02_single_no_prop",
    "03_group_three_people",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()

    pose_analyzer = PoseAnalyzer()
    critic = PlanCritic()
    for case in CASES:
        source_json = args.results / case / "run_01.json"
        source_image = args.samples / f"{case}.jpg"
        result: dict[str, Any] = json.loads(
            source_json.read_text(encoding="utf-8")
        )
        analysis = dict(result["analysis"])
        plan = build_field_plan(
            analysis,
            str(result.get("request") or "Recreate this reference photo"),
            result.get("intent"),
        )
        review = critic.review(analysis, plan)
        if review["status"] != "pass":
            raise RuntimeError(f"{case}: final plan blocked: {review['issues']}")
        pose_json = pose_analyzer.build(analysis, plan)
        output_png = args.results / case / "final.png"
        card = render_pose_card(
            source_image,
            analysis,
            plan,
            pose_json,
            output_png,
        )
        result["shooting_plan"] = plan
        result["critic"] = review
        result["pose_json"] = pose_json
        result["pose_card"] = card
        result["release_finalization"] = {
            "source_evidence": source_json.name,
            "mode": "deterministic planner + critic + segmentation + PIL renderer",
            "vlm_rerun": False,
            "image_generation_model_used": False,
        }
        (args.results / case / "final.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "case": case,
                    "critic": review["status"],
                    "people_matched": card["person_outline"]["people_matched"],
                    "prop_usage": plan["why_this_photo_works"]["prop_usage"],
                    "hand_title": card["display_copy"]["pose"]["hand_title"],
                    "hand_action": card["display_copy"]["pose"]["hands"],
                    "output": str(output_png),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
