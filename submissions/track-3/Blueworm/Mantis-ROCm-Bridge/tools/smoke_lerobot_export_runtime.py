#!/usr/bin/env python3
"""Write one synthetic, explicitly non-trainable LeRobot schema smoke dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mantis_rocm_bridge.contracts import ContractError, load_json
from mantis_rocm_bridge.episode_export import create_lerobot_dataset_sink


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_root", type=Path)
    parser.add_argument(
        "--interface",
        type=Path,
        default=ROOT / "configs/mantis-lerobot-interface-v1.json",
    )
    args = parser.parse_args()
    try:
        import numpy as np
    except ImportError as exc:
        raise ContractError("LeRobot schema smoke requires NumPy") from exc

    output = args.output_root.resolve()
    if output.exists():
        parser.error(f"refusing to overwrite output root: {output}")
    interface = load_json(args.interface)
    sink = create_lerobot_dataset_sink(
        repo_id="local/mantis_schema_smoke_nontrainable",
        root=output,
        interface=interface,
        use_videos=False,
    )
    frame = {
        "task": "SYNTHETIC SCHEMA SMOKE ONLY - NOT TRAINING DATA",
        "observation.state": np.zeros(len(interface["state_names"]), dtype=np.float32),
        "action": np.zeros(len(interface["action_names"]), dtype=np.float32),
    }
    for camera_key, shape in interface["camera_features"].items():
        frame[camera_key] = np.zeros(shape, dtype=np.uint8)
    sink.add_frame(frame)
    sink.save_episode()
    sink.finalize()

    parquet_files = sorted((output / "data").rglob("*.parquet"))
    checks = {
        "info_json": (output / "meta/info.json").is_file(),
        "stats_json": (output / "meta/stats.json").is_file(),
        "episode_metadata": any((output / "meta").rglob("*.parquet")),
        "frame_parquet": len(parquet_files) == 1,
    }
    receipt = {
        "schema_version": 1,
        "smoke_id": "mantis_lerobot_schema_smoke_v1",
        "runtime_smoke_pass": all(checks.values()),
        "checks": checks,
        "parquet_files": [str(path.relative_to(output)) for path in parquet_files],
        "frames": 1,
        "episodes": 1,
        "training_eligible": False,
        "expected_data_gate_result": "reject_zero_variance_and_episode_too_short",
        "claim_boundary": (
            "Synthetic writer/schema smoke only; no demonstration, task-success, "
            "training, inference, GPU, or ROCm claim."
        ),
    }
    receipt_path = output / "runtime-smoke-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["runtime_smoke_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
