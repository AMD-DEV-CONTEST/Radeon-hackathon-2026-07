from __future__ import annotations

import argparse
import json
from pathlib import Path

from .mission import (
    DeliverableKind,
    DeliverableSpec,
    MissionError,
    MultimodalMissionPlanner,
)
from .multimodal_ingest import (
    MediaSource,
    MultimodalIngestor,
    RightsStatus,
)
from .quality_contract import QualityTier


def _media(value: str) -> MediaSource:
    try:
        role, rights, path = value.split(":", 2)
        return MediaSource(path, role, RightsStatus(rights))
    except (ValueError, KeyError) as error:
        raise argparse.ArgumentTypeError(
            "media must be ROLE:RIGHTS:PATH; RIGHTS is owned, licensed, or unknown"
        ) from error


def _deliverable(value: str) -> DeliverableSpec:
    parts = value.split(":")
    if len(parts) not in {2, 3}:
        raise argparse.ArgumentTypeError(
            "deliverable must be KIND:ASPECT[:DURATION_SECONDS]"
        )
    try:
        duration = int(parts[2]) if len(parts) == 3 else None
        return DeliverableSpec(DeliverableKind(parts[0]), parts[1], duration)
    except (ValueError, MissionError) as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build an inspectable, local-only ProofLaunch multimodal mission graph."
        )
    )
    parser.add_argument(
        "--media",
        action="append",
        type=_media,
        required=True,
        help="ROLE:RIGHTS:PATH (repeatable)",
    )
    parser.add_argument(
        "--deliverable",
        action="append",
        type=_deliverable,
        required=True,
        help="KIND:ASPECT[:DURATION_SECONDS] (repeatable)",
    )
    parser.add_argument("--mission-id", default="prooflaunch-mission")
    parser.add_argument("--available-vram-gb", type=float, default=24)
    parser.add_argument(
        "--quality-tier",
        choices=tuple(item.value for item in QualityTier),
        default=QualityTier.STANDARD.value,
    )
    parser.add_argument("--output", default="./prooflaunch-mission")
    args = parser.parse_args()

    artifacts = MultimodalIngestor().ingest(tuple(args.media))
    plan = MultimodalMissionPlanner().build(
        mission_id=args.mission_id,
        artifacts=artifacts,
        deliverables=tuple(args.deliverable),
        available_vram_gb=args.available_vram_gb,
        quality_tier=QualityTier(args.quality_tier),
    )
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "ProofLaunchMissionBundleV1",
        "artifacts": [item.serializable() for item in artifacts],
        "plan": plan.serializable(),
        "graph_hash": plan.graph_hash,
    }
    target = output / "mission-plan.json"
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"plan": str(target), "graph_hash": plan.graph_hash}, indent=2))


if __name__ == "__main__":
    main()
