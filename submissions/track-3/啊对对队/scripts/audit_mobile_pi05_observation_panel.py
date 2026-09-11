#!/usr/bin/env python3
"""Audit a frozen PI0.5 observation panel against training physical contexts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parcel_sorter.mobile_pi05_contract import decode_pi05_context
from parcel_sorter.mobile_pi05_observation_panel import (
    load_catalog_profiles,
    physical_context_signature,
    validate_pi05_observation_panel,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--training-dataset", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=Path("configs/catalog_v2.toml"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    import pyarrow.parquet as pq

    panel = json.loads(args.panel.read_text(encoding="utf-8"))
    signatures = set()
    for path in sorted(args.training_dataset.glob("data/**/*.parquet")):
        for row in pq.read_table(path, columns=["observation.state"]).to_pylist():
            context = decode_pi05_context(row["observation.state"])
            signatures.add(
                physical_context_signature(
                    {
                        "shape": context.parcel_shape,
                        "orientation_mode": (
                            "upright"
                            if context.parcel_shape == "cylinder"
                            and context.parcel_size_m[2] > context.parcel_size_m[0]
                            else (
                                "horizontal"
                                if context.parcel_shape == "cylinder"
                                else "yaw"
                            )
                        ),
                        "size_m": context.parcel_size_m,
                        "mass_kg": context.parcel_mass_kg,
                    }
                )
            )
    if not signatures:
        parser.error("training dataset contains no physical contexts")
    result = validate_pi05_observation_panel(
        panel,
        load_catalog_profiles(args.catalog),
        signatures,
    )
    result["training_unique_physical_contexts"] = len(signatures)
    result["panel"] = str(args.panel.resolve())
    result["training_dataset"] = str(args.training_dataset.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
