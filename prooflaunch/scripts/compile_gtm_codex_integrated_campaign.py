#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.gtm_codex_integrated_campaign import (  # noqa: E402
    compile_codex_integrated_campaign_portfolio,
)
from prooflaunch_remix.v10_submission_production_api import (  # noqa: E402
    load_verified_platform_capability_showcase,
)


DEFAULT_BLUEPRINTS = ROOT / "config/codex-integrated-campaign-blueprints-v1.json"
DEFAULT_OUTPUT = ROOT / "evidence/v10/gtm-codex-integrated-campaign-portfolio-v1.json"


def _inside_project(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as error:
        raise argparse.ArgumentTypeError("path must remain inside the project root") from error
    return path


def compile_from_files(
    *,
    blueprint_path: Path = DEFAULT_BLUEPRINTS,
) -> dict[str, object]:
    showcase = load_verified_platform_capability_showcase(ROOT)
    blueprints = json.loads(blueprint_path.read_text(encoding="utf-8"))
    return compile_codex_integrated_campaign_portfolio(
        showcase=showcase,
        blueprints=blueprints,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile Codex B2B/B2C platform references into integrated zero-budget campaign systems."
    )
    parser.add_argument("--blueprints", type=_inside_project, default=DEFAULT_BLUEPRINTS)
    parser.add_argument("--output", type=_inside_project, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    portfolio = compile_from_files(blueprint_path=args.blueprints)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        args.output,
        json.dumps(portfolio, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(
        json.dumps(
            {
                "output": str(args.output.relative_to(ROOT)),
                "content_sha256": portfolio["content_sha256"],
                "pack_count": portfolio["pack_count"],
                "platform_candidate_count": portfolio["platform_candidate_count"],
                "email_count": portfolio["email_count"],
                "production_direction_count": portfolio["production_direction_count"],
                "search_geo_node_count": portfolio["search_geo_node_count"],
                "seven_day_flight_slot_count": portfolio["seven_day_flight_slot_count"],
                "experiment_count": portfolio["experiment_count"],
                "release_eligible_count": portfolio["release_eligible_count"],
                "human_review_completed_count": portfolio["human_review_completed_count"],
                "production_effect_observed": portfolio["production_effect_observed"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
