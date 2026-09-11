#!/usr/bin/env python3
"""Freeze the 60-context PI0.5 validation and 120-rollout long-run designs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parcel_sorter.mobile_pi05_validation import build_pi05_validation_design


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("configs/catalog_v2.toml"))
    parser.add_argument(
        "--validation-output",
        type=Path,
        default=Path("configs/mobile_pi05_frozen_validation_60_v1.json"),
    )
    parser.add_argument(
        "--development-output",
        type=Path,
        default=Path("configs/mobile_pi05_development_validation_30_v1.json"),
    )
    parser.add_argument(
        "--long-run-output",
        type=Path,
        default=Path("configs/mobile_pi05_frozen_long_run_120_v1.json"),
    )
    parser.add_argument("--seed", type=int, default=20260728)
    args = parser.parse_args()
    validation, long_run = build_pi05_validation_design(args.catalog, seed=args.seed)
    development, _ = build_pi05_validation_design(
        args.catalog,
        seed=20260711,
        blocks=10,
        context_prefix="pd30",
        validation_collection_id="mobile-pi05-development-validation-30-v1",
        long_run_collection_id="mobile-pi05-unused-development-repeat-v1",
        validation_split="development_validation_do_not_train",
    )
    development["protocol"] = "pi05-pure-vla-development-complete-block-screen-v1"
    development["claim_boundary"] = (
        "Development-only model and runtime selection. These 30 contexts are excluded "
        "from the frozen 60-context score and cannot support a final performance claim."
    )
    _write(args.validation_output, validation)
    _write(args.long_run_output, long_run)
    _write(args.development_output, development)
    print(
        json.dumps(
            {
                "validation_contexts": len(validation["episodes"]),
                "development_contexts": len(development["episodes"]),
                "long_run_rollouts": len(long_run["episodes"]),
                "independent_contexts": long_run["independent_physical_contexts"],
                "design_fingerprint_sha256": validation["design_fingerprint_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
