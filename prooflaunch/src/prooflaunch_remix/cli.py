from __future__ import annotations

import argparse
import json
from pathlib import Path

from .audience_pulse import LexicalAudiencePulse
from .contracts import CampaignRequest
from .runtime import build_supervisor


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the offline ProofLaunch Track 1 reference pipeline."
    )
    parser.add_argument("--product-image", required=True)
    parser.add_argument("--product-name", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--market", default="Global")
    parser.add_argument("--platform", default="TikTok")
    parser.add_argument("--goal", default="launch")
    parser.add_argument("--emotion", default="joy")
    parser.add_argument("--output", default="./prooflaunch-output")
    parser.add_argument("--seed", type=int, default=202607)
    args = parser.parse_args()
    request = CampaignRequest(
        product_name=args.product_name,
        product_image=str(Path(args.product_image).resolve()),
        specification_text=args.spec,
        market=args.market,
        platform=args.platform,
        goal=args.goal,
        target_emotion=args.emotion,
    )
    supervisor = build_supervisor(
        audience=LexicalAudiencePulse(),
        seed=args.seed,
    )
    state = supervisor.run(request, args.output)
    print(json.dumps(state.serializable(), ensure_ascii=False, indent=2))
    raise SystemExit(0 if state.stage.value == "deliver" else 2)


if __name__ == "__main__":
    main()
