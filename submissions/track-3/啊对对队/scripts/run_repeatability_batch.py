from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from parcel_sorter.config import ExperimentConfig, load_config
from parcel_sorter.genesis_env import GenesisParcelEnv
from parcel_sorter.metrics import MetricsAccumulator
from parcel_sorter.provenance import runtime_report
from parcel_sorter.randomization import DomainRandomizer
from parcel_sorter.runner import run_expert_episode


BASELINE = "collision-checked-reset"
CANDIDATE = "reset-risk-gated-planner"


def _condition_config(base: ExperimentConfig, condition: str) -> ExperimentConfig:
    config = replace(
        base,
        control=replace(base.control, collision_checked_reset_enabled=True),
    )
    if condition == CANDIDATE:
        config = replace(
            config,
            task=replace(
                config.task,
                geometry_aware_grasp_planning_enabled=True,
                grasp_planning_reset_fallback_gate_enabled=True,
            ),
        )
    elif condition != BASELINE:
        raise ValueError(f"unknown repeatability condition: {condition}")
    config.validate()
    return config


def _write_single_episode_summary(
    output: Path,
    config: ExperimentConfig,
    profile_id: str,
    report: dict,
) -> None:
    metrics = MetricsAccumulator()
    from parcel_sorter.metrics import EpisodeResult

    result = report["result"]
    metrics.add(
        EpisodeResult(
            success=bool(result["success"]),
            retries=int(result["retries"]),
            duration_seconds=float(result["duration_seconds"]),
            inference_latency_ms=tuple(result["inference_latency_ms"]),
            dropped=bool(result["dropped"]),
            max_contact_force_n=float(result["max_contact_force_n"]),
        )
    )
    payload = {
        "runtime": runtime_report(),
        "evaluation_range": {
            "start_episode": int(report["episode_index"]),
            "end_episode": int(report["episode_index"]),
            "num_episodes": 1,
            "profile_filter": [profile_id],
            "episodes_per_profile": 1,
            "collection_plan": None,
            "profile_episode_counts": {profile_id: 1},
        },
        "config": asdict(config),
        "summary": metrics.summary(),
        "profile_summaries": {profile_id: metrics.summary()},
        "episodes": [report],
    }
    output.mkdir(parents=True, exist_ok=False)
    (output / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a frozen nested-repeat schedule in one Genesis process"
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--event-log", type=Path, required=True)
    parser.add_argument("--backend", choices=("rocm", "cuda", "cpu"), default="rocm")
    args = parser.parse_args()
    schedule = json.loads(args.schedule.read_text(encoding="utf-8"))
    if tuple(schedule.get("conditions", ())) != (BASELINE, CANDIDATE):
        parser.error("repeatability schedule has unexpected conditions")
    if args.event_log.exists() or any(args.runs_root.iterdir()):
        parser.error("repeatability output must be empty")

    base = load_config(args.config)
    configs = {
        condition: _condition_config(base, condition)
        for condition in schedule["conditions"]
    }
    randomizer = DomainRandomizer(base.randomization, base.seed, base.parcel_profiles)
    args.event_log.parent.mkdir(parents=True, exist_ok=True)
    with args.event_log.open("x", encoding="utf-8") as event_log:
        for block in schedule["blocks"]:
            run_index = int(block["run_index"])
            episode_id = int(block["episode_id"])
            profile_id = str(block["profile_id"])
            for position, condition in enumerate(block["condition_order"], 1):
                output = args.runs_root / f"{run_index:02d}" / condition / "expert"
                sample = randomizer.sample_profile(profile_id, episode_id)
                started = time.perf_counter()
                with GenesisParcelEnv(
                    configs[condition],
                    sample,
                    backend=args.backend,
                    show_viewer=False,
                    video_path=None,
                    capture_sensors=False,
                ) as env:
                    report = run_expert_episode(
                        env,
                        configs[condition],
                        sample,
                        episode_id,
                    ).to_dict()
                _write_single_episode_summary(
                    output,
                    configs[condition],
                    profile_id,
                    report,
                )
                event = {
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "run_index": run_index,
                    "repeat_index": int(block["repeat_index"]),
                    "episode_id": episode_id,
                    "profile_id": profile_id,
                    "condition": condition,
                    "condition_position": position,
                    "wall_seconds": time.perf_counter() - started,
                    "success": bool(report["result"]["success"]),
                    "terminal_stage": report["terminal_stage"],
                    "max_contact_force_n": float(
                        report["result"]["max_contact_force_n"]
                    ),
                    "planner_active": bool(
                        report.get("safety_summary", {}).get(
                            "geometry_aware_grasp_planning_active", False
                        )
                    ),
                }
                event_log.write(json.dumps(event, ensure_ascii=False) + "\n")
                event_log.flush()
                print(json.dumps(event, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
