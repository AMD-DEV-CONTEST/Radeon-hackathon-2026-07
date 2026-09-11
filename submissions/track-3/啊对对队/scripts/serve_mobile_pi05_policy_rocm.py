#!/usr/bin/env python3
"""Serve one PI0.5 checkpoint persistently across sequential ROCm episodes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parcel_sorter.mobile_vla_service import serve_mobile_vla


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--ready", type=Path, required=True)
    parser.add_argument(
        "--chunk-execution-protocol",
        choices=(
            "first-action-hold-v1",
            "pi05-window-aggregate-v1",
            "pi05-open-loop-queue-v1",
        ),
        default="first-action-hold-v1",
    )
    parser.add_argument("--chunk-execution-steps", type=int, default=1)
    parser.add_argument("--stage-chunk-execution-steps", type=json.loads)
    args = parser.parse_args()
    if not (args.checkpoint / "config.json").is_file():
        parser.error("checkpoint config is missing")
    serve_mobile_vla(
        args.checkpoint,
        args.socket,
        args.ready,
        chunk_execution_protocol=args.chunk_execution_protocol,
        chunk_execution_steps=args.chunk_execution_steps,
        stage_chunk_execution_steps=args.stage_chunk_execution_steps,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
