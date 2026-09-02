#!/usr/bin/env python3
"""PolicyCut server entry point.

Usage:
    python run.py [--host 0.0.0.0] [--port 8000] [--data-dir data] [--require-rocm]

Sets environment variables consumed by policycut.config, then starts uvicorn
with the FastAPI app at policycut.api.app:app.
"""

from __future__ import annotations

import argparse
import os
import sys


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="policycut",
        description="PolicyCut — local privacy video redaction editor.",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Data directory for projects and jobs (default: ./data)",
    )
    parser.add_argument(
        "--require-rocm",
        action="store_true",
        help="Fail model stages instead of falling back to CPU when no GPU is found",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.data_dir:
        os.environ["POLICYCUT_DATA_DIR"] = args.data_dir
    if args.require_rocm:
        os.environ["POLICYCUT_REQUIRE_ROCM"] = "1"

    try:
        import uvicorn
    except ImportError:
        print(
            "uvicorn is not installed. Install dependencies first:\n"
            "  pip install -e . \n"
            "or on the ROCm machine:\n"
            "  pip install -r requirements-rocm.txt",
            file=sys.stderr,
        )
        return 1

    uvicorn.run(
        "policycut.api.app:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
