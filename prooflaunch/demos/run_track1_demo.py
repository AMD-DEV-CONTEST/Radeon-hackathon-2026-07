#!/usr/bin/env python3
"""One-command, truth-bounded Track 1 evaluator demo.

This replays the governed ProofLaunch workflow against already sealed local
assets. It does not make a new model call and does not claim Radeon execution.
The separate live-Radeon capture gate is documented in
submission/track1-prooflaunch/RADEON_FINAL_CAPTURE.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scripts.run_run_bound_multimodal_demo import run_demo  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay the governed Track 1 GTM-to-multimodal workflow."
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "artifacts/judge-track1-replay-v1"),
    )
    args = parser.parse_args()
    output = Path(args.output).expanduser().resolve()
    try:
        output.relative_to(ROOT)
    except ValueError as error:
        raise SystemExit("--output must remain inside the project root") from error

    receipt = run_demo(output)
    summary = {
        "status": "local_governed_replay_passed",
        "run_id": receipt["run_id"],
        "registered_deliverables": receipt[
            "registered_run_bound_deliverable_count"
        ],
        "receipt": str((output / "demo-receipt.json").relative_to(ROOT)),
        "receipt_content_sha256": receipt["content_sha256"],
        "radeon_execution_observed": receipt["source_execution"][
            "radeon_execution_observed"
        ],
        "named_human_quality_count": receipt["named_human_quality_count"],
        "production_effect_attributed_count": receipt[
            "production_effect_attributed_count"
        ],
        "next_gate": "run_and_record_the_live_radeon_capture_card",
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
