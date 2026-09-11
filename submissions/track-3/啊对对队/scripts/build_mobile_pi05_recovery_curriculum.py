#!/usr/bin/env python3
"""Build a deterministic PI0.5 contact-recovery development curriculum."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
from typing import Any


RECOVERY_OFFSETS_M = (
    (0.004, 0.000),
    (-0.004, 0.000),
    (0.000, 0.004),
    (0.000, -0.004),
    (0.003, 0.003),
    (-0.003, 0.003),
    (0.003, -0.003),
    (-0.003, -0.003),
    (0.006, 0.000),
    (-0.006, 0.000),
    (0.000, 0.006),
    (0.000, -0.006),
)
PENETRATION_DELTAS_M = (0.0, 0.0005, -0.0005)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variants-per-episode", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260727)
    parser.add_argument(
        "--vertical-speed-scale",
        type=float,
        default=0.6,
        help="fixed safety-layer scale shared by all recovery demonstrations",
    )
    parser.add_argument(
        "--profile",
        action="append",
        help="retain only this profile; repeat to select multiple profiles",
    )
    args = parser.parse_args()
    if args.variants_per_episode < 1:
        parser.error("variants-per-episode must be positive")
    if not 0.6 <= args.vertical_speed_scale <= 1.0:
        parser.error("vertical-speed-scale must be in [0.6, 1.0]")
    if args.output.exists():
        parser.error("output must not already exist")

    source = json.loads(args.source.read_text(encoding="utf-8"))
    source_episodes = source.get("episodes")
    if not isinstance(source_episodes, list) or not source_episodes:
        parser.error("source must contain a non-empty episodes list")
    selected_profiles = set(args.profile or ())
    selected = [
        item
        for item in source_episodes
        if not selected_profiles or str(item.get("profile")) in selected_profiles
    ]
    if not selected:
        parser.error("profile selection produced no episodes")

    rng = random.Random(args.seed)
    offsets = list(RECOVERY_OFFSETS_M)
    rng.shuffle(offsets)
    episodes: list[dict[str, Any]] = []
    for source_index, item in enumerate(selected):
        for variant_index in range(args.variants_per_episode):
            offset = offsets[(source_index * args.variants_per_episode + variant_index) % len(offsets)]
            penetration = PENETRATION_DELTAS_M[
                (source_index + variant_index) % len(PENETRATION_DELTAS_M)
            ]
            episode = dict(item)
            source_episode_id = str(item["episode_id"])
            vertical_speed_scale = (
                1.0 if bool(item.get("cooperative_cradle")) else args.vertical_speed_scale
            )
            episode.update(
                {
                    "episode_id": f"{source_episode_id}-pi05r{variant_index + 1:02d}",
                    "source_episode_id": source_episode_id,
                    "split": "development_recovery",
                    "recovery_contact_offset_m": list(offset),
                    "recovery_contact_penetration_delta_m": penetration,
                    "recovery_vertical_speed_scale": vertical_speed_scale,
                    "retry_index": 1 + variant_index % 2,
                    "task_text": (
                        f"Recover contact and transport the {item['profile']} parcel to the "
                        "marked destination using the selected grasp mode."
                    ),
                }
            )
            episodes.append(episode)

    payload = {
        "schema_version": 1,
        "collection_id": f"pi05-contact-recovery-seed-{args.seed}",
        "protocol": "pi05-verified-contact-recovery-curriculum-v1",
        "seed": args.seed,
        "source_config": str(args.source.resolve()),
        "source_config_sha256": _sha256(args.source),
        "source_episode_count": len(selected),
        "variants_per_episode": args.variants_per_episode,
        "safety_vertical_speed_scale_by_mode": {
            "top_suction": args.vertical_speed_scale,
            "side_suction": args.vertical_speed_scale,
            "cooperative_cradle": 1.0,
        },
        "requested_episodes": len(episodes),
        "profiles": sorted({str(item["profile"]) for item in episodes}),
        "episodes": episodes,
        "split_policy": (
            "development recovery only; episode ids and source ids must be disjoint from "
            "the frozen evaluation campaign"
        ),
        "admission_policy": (
            "the collector may save training data only after full physical task success; "
            "failed attempts remain failure-replay records"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in payload.items() if key != "episodes"}, indent=2))
    return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
