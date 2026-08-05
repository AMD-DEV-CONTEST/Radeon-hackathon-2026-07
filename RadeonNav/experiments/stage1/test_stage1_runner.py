from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_runner():
    path = Path(__file__).with_name("stage1_runner.py")
    spec = importlib.util.spec_from_file_location("stage1_runner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_stage1_contract_and_selection(tmp_path: Path) -> None:
    runner = _load_runner()
    assert runner._sha256(runner.GOLDEN_FIXTURE) == runner.EXPECTED_GOLDEN_SHA256
    assert runner._sha256(runner.PLANNER_FIXTURE) == runner.EXPECTED_PLANNER_SHA256
    payload = {
        "results": [
            {
                "actor_observation_dim": 45,
                "plot_data": {"throughput_env_steps_per_s": 123.0},
            }
        ]
    }
    record = runner._find_record(payload, "actor_observation_dim")
    assert record is not None
    assert record["plot_data"]["throughput_env_steps_per_s"] == 123.0
    assert not runner._rocm_ready(
        {
            "hip": None,
            "cuda_api_available": False,
            "device_count": 0,
            "device_names": [],
        }
    )
    results = [
        {
            "run_id": "S1-R006",
            "status": "PASSED",
            "num_envs": 512,
            "steps_per_sec": 100.0,
            "telemetry": {"vram_percent_peak": 50.0},
        },
        {
            "run_id": "S1-R007",
            "status": "PASSED",
            "num_envs": 1024,
            "steps_per_sec": 104.0,
            "telemetry": {"vram_percent_peak": 60.0},
        },
        {
            "run_id": "S1-R008",
            "status": "PASSED",
            "num_envs": 2048,
            "steps_per_sec": 200.0,
            "telemetry": {"vram_percent_peak": 95.0},
        },
    ]
    assert runner._select_throughput_result(results)["run_id"] == "S1-R006"

    log = tmp_path / "run.log"
    log.write_text(
        "Steps per second: 10\nSteps per second: 20\nSteps per second: 30\n",
        encoding="utf-8",
    )
    assert runner._training_fps(log, 1)["measured_mean"] == 25.0

    metrics = tmp_path / "gpu_metrics.jsonl"
    metrics.write_text(
        json.dumps(
            {
                "parsed": None,
                "stdout": (
                    "GFX_ACTIVITY: 75 %\n"
                    "CURRENT_SOCKET_POWER: 180 W\n"
                    "TOTAL_VISIBLE_VRAM: 24560 MB\n"
                    "USED_VISIBLE_VRAM: 12280 MB\n"
                ),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    telemetry = runner._telemetry_summary(metrics)
    assert telemetry["gpu_utilization_mean"] == 75.0
    assert telemetry["vram_percent_peak"] == 50.0
    assert telemetry["power_w_mean"] == 180.0

    assert not runner._check_checkpoint_sequence(
        "S1-R009", [0, 1, 2], {"completed_iterations": 2}, None
    )
