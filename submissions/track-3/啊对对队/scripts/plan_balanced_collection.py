from __future__ import annotations

import argparse
import json
from pathlib import Path

from parcel_sorter.collection_plan import build_balanced_collection_plan
from parcel_sorter.config import load_config


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan a new, balanced RGB-D expert-data collection from audit evidence"
    )
    parser.add_argument("--config", default="configs/catalog_v2.toml")
    parser.add_argument(
        "--audit-manifest",
        required=True,
        help="path to expert/audit_dataset/episodes.jsonl from a completed collection",
    )
    parser.add_argument("--output", required=True, help="path for the generated plan JSON")
    parser.add_argument("--target-successes-per-profile", type=int, default=30)
    parser.add_argument("--planning-rate-floor", type=float, default=0.10)
    parser.add_argument("--oversampling-factor", type=float, default=1.25)
    parser.add_argument("--readiness-success-rate-lower-bound", type=float, default=0.35)
    parser.add_argument("--start-episode", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    output = Path(args.output)
    if output.exists() and not args.overwrite:
        parser.error(f"output already exists: {output}; pass --overwrite to replace it")
    try:
        config = load_config(args.config)
        plan = build_balanced_collection_plan(
            profiles=config.parcel_profiles,
            audit_manifest=args.audit_manifest,
            config_path=args.config,
            target_successes_per_profile=args.target_successes_per_profile,
            planning_rate_floor=args.planning_rate_floor,
            oversampling_factor=args.oversampling_factor,
            readiness_success_rate_lower_bound=args.readiness_success_rate_lower_bound,
            start_episode=args.start_episode,
        )
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = plan["summary"]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["ready_for_full_collection"]:
        print("Plan is ready for bulk collection.")
    else:
        print("Plan records unresolved profiles; run diagnostics before bulk collection.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
