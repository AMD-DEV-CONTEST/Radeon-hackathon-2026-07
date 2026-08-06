"""CLI entrypoint for the private AI Photographer Agent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.agent.orchestrator import PhotographerAgent
from src.tools.image_orientation import normalize_image_orientation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Local reference image path")
    parser.add_argument(
        "--request",
        default="Create an executable photography plan for this reference image.",
        help="User's shooting goal",
    )
    parser.add_argument("--output", help="Optional JSON output path")
    parser.add_argument(
        "--card-output",
        "--overlay-output",
        dest="card_output",
        default="demo/ai_photography_execution_card.png",
        help="Deterministic AI photography execution-card PNG output.",
    )
    return parser


def run(
    image: str,
    request: str,
    *,
    overlay_path: str | Path = "demo/coaching_overlay.png",
) -> dict:
    orientation = normalize_image_orientation(image)
    return PhotographerAgent().run(
        image,
        request,
        generate_overlay=True,
        overlay_path=overlay_path,
        local_person_geometry=orientation.get("person_geometry"),
    )


def main() -> None:
    args = build_parser().parse_args()
    result = run(
        args.image,
        args.request,
        overlay_path=args.card_output,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
