#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.competition_benchmark import (
    DEFAULT_SEEDS,
    DeclaredBaseline,
    build_frozen_manifest,
    load_products_csv,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze the ProofLaunch 30-product × 3-ratio × 5-seed matrix"
    )
    parser.add_argument("products_csv", type=Path)
    parser.add_argument("--benchmark-id", required=True)
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--prooflaunch-build-sha256", required=True)
    parser.add_argument("--baseline-name", required=True)
    parser.add_argument("--baseline-version", required=True)
    parser.add_argument("--baseline-settings-sha256", required=True)
    parser.add_argument("--baseline-source-locator", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--seeds",
        default=",".join(str(seed) for seed in DEFAULT_SEEDS),
        help="exactly five comma-separated non-negative integers",
    )
    arguments = parser.parse_args()
    try:
        seeds = tuple(int(value.strip()) for value in arguments.seeds.split(","))
    except ValueError as error:
        raise SystemExit("--seeds must contain integers") from error
    manifest = build_frozen_manifest(
        benchmark_id=arguments.benchmark_id,
        protocol_sha256=arguments.protocol_sha256,
        prooflaunch_build_sha256=arguments.prooflaunch_build_sha256,
        baseline=DeclaredBaseline(
            name=arguments.baseline_name,
            version=arguments.baseline_version,
            settings_sha256=arguments.baseline_settings_sha256,
            source_locator=arguments.baseline_source_locator,
        ),
        products=load_products_csv(arguments.products_csv),
        seeds=seeds,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(
            manifest.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "schema": manifest.schema,
                "manifest_hash": manifest.manifest_hash,
                "products": len(manifest.products),
                "ratios": len(manifest.aspect_ratios),
                "seeds": len(manifest.seeds),
                "cases": len(manifest.cases),
                "video_cases": sum(case.video_required for case in manifest.cases),
                "output": str(arguments.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
