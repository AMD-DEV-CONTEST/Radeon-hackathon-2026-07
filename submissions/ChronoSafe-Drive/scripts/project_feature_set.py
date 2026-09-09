"""Project a generated ChronoSafe dataset onto a named feature subset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from chronosafe.features import FEATURE_NAMES


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("basic",), default="basic")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = np.load(args.input)
    if "features" not in payload or "feature_names" not in payload:
        raise ValueError("Input dataset does not contain features and feature_names")
    names = [str(value) for value in payload["feature_names"]]
    indices = [names.index(name) for name in FEATURE_NAMES]
    arrays = {key: payload[key] for key in payload.files}
    arrays["features"] = payload["features"][:, indices].astype(np.float32)
    arrays["feature_names"] = np.asarray(FEATURE_NAMES)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.output, **arrays)
    metadata = {
        "source": str(args.input),
        "output": str(args.output),
        "mode": args.mode,
        "samples": int(len(arrays["features"])),
        "feature_count": int(arrays["features"].shape[1]),
        "features": list(FEATURE_NAMES),
        "preserved_arrays": sorted(arrays),
    }
    args.output.with_suffix(".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2))
    print("ChronoSafe feature projection: PASS")


if __name__ == "__main__":
    main()
