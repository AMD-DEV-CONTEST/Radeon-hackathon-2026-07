from __future__ import annotations

import argparse
from dataclasses import asdict
import json

from .config import load_config
from .contracts import Observation
from .metrics import EpisodeResult, MetricsAccumulator
from .randomization import DomainRandomizer
from .state_machine import ClosedLoopSupervisor


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the CPU closed-loop dry run")
    parser.add_argument("--config", default="configs/baseline.toml")
    args = parser.parse_args()

    config = load_config(args.config)
    supervisor = ClosedLoopSupervisor(config.task.max_grasp_retries)
    observations = [
        Observation(),
        Observation(parcel_visible=True),
        Observation(at_pregrasp=True),
        Observation(),
        Observation(),
        Observation(parcel_visible=True),
        Observation(at_pregrasp=True),
        Observation(),
        Observation(grasp_contact=True),
        Observation(parcel_lifted=True),
        Observation(at_drop_pose=True),
        Observation(at_drop_pose=True, parcel_released=True),
    ]

    trace = [asdict(supervisor.step(observation)) for observation in observations]

    randomizer = DomainRandomizer(config.randomization, config.seed, config.parcel_profiles)
    samples = [randomizer.sample(index).to_dict() for index in range(3)]
    metrics = MetricsAccumulator()
    metrics.add(
        EpisodeResult(
            success=True,
            retries=1,
            duration_seconds=4.2,
            inference_latency_ms=(8.1, 8.5, 9.0),
            max_contact_force_n=21.4,
        )
    )
    metrics.add(
        EpisodeResult(
            success=True,
            retries=0,
            duration_seconds=3.8,
            inference_latency_ms=(7.9, 8.2, 8.4),
            max_contact_force_n=18.7,
        )
    )
    print(
        json.dumps(
            {
                "project": config.name,
                "trace": trace,
                "randomized_parcels": samples,
                "example_metrics": metrics.summary(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
