#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

from prooflaunch_remix.benchmark_runner import (
    BenchmarkRunnerError,
    CompetitionMatrixRunner,
    merge_sharded_results,
)
from prooflaunch_remix.radeon_preflight import (
    DEFAULT_MINIMUM_FREE_DISK_GB,
    DEFAULT_MINIMUM_VRAM_GB,
    run_radeon_preflight,
    write_preflight_report,
)


def _load_adapter(specification: str):
    module_name, separator, factory_name = specification.partition(":")
    if not separator or not module_name or not factory_name:
        raise BenchmarkRunnerError(
            "--adapter must use the form importable.module:factory"
        )
    try:
        module = importlib.import_module(module_name)
        factory = getattr(module, factory_name)
        adapter = factory()
    except (ImportError, AttributeError, TypeError) as error:
        raise BenchmarkRunnerError(
            f"cannot construct adapter {specification}: {error}"
        ) from error
    return adapter


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run or merge the durable competition-2X Radeon matrix"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument(
        "--settings",
        required=True,
        type=Path,
    )
    preflight_parser.add_argument("--manifest", type=Path)
    preflight_parser.add_argument("--strict-cache", action="store_true")
    preflight_parser.add_argument(
        "--minimum-vram-gb",
        type=float,
        default=DEFAULT_MINIMUM_VRAM_GB,
    )
    preflight_parser.add_argument(
        "--minimum-free-disk-gb",
        type=float,
        default=DEFAULT_MINIMUM_FREE_DISK_GB,
    )
    preflight_parser.add_argument("--output", type=Path)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--manifest", required=True, type=Path)
    run_parser.add_argument("--run-dir", required=True, type=Path)
    run_parser.add_argument("--adapter", required=True)
    run_parser.add_argument("--resume", action="store_true")
    run_parser.add_argument("--shard-index", type=int, default=0)
    run_parser.add_argument("--shard-count", type=int, default=1)
    run_parser.add_argument("--max-retries", type=int, default=2)

    merge_parser = subparsers.add_parser("merge")
    merge_parser.add_argument("--manifest", required=True, type=Path)
    merge_parser.add_argument("--run-dir", required=True, type=Path)
    merge_parser.add_argument("--shard-count", required=True, type=int)
    merge_parser.add_argument("--output", type=Path)

    arguments = parser.parse_args()
    if arguments.command == "preflight":
        summary = run_radeon_preflight(
            settings_path=arguments.settings,
            manifest_path=arguments.manifest,
            strict_cache=arguments.strict_cache,
            minimum_vram_gb=arguments.minimum_vram_gb,
            minimum_free_disk_gb=arguments.minimum_free_disk_gb,
        )
        if arguments.output is not None:
            write_preflight_report(summary, arguments.output)
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if summary["passed"] else 1
    if arguments.command == "merge":
        summary = merge_sharded_results(
            manifest_path=arguments.manifest,
            run_dir=arguments.run_dir,
            shard_count=arguments.shard_count,
            output_path=arguments.output,
        )
    else:
        adapter = _load_adapter(arguments.adapter)
        summary = CompetitionMatrixRunner(
            manifest_path=arguments.manifest,
            run_dir=arguments.run_dir,
            adapter=adapter,
            resume=arguments.resume,
            shard_index=arguments.shard_index,
            shard_count=arguments.shard_count,
            max_retries=arguments.max_retries,
        ).run()
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
