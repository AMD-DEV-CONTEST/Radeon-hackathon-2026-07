#!/usr/bin/env python3
"""Build and audit a non-overwriting public submission candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mantis_rocm_bridge.publication import (
    PublicationGateError,
    build_publication_candidate,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=("candidate", "release"),
        default="candidate",
        help=(
            "candidate succeeds when the content gate passes; release additionally "
            "requires every promotion gate"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        audit = build_publication_candidate(
            args.repository_root,
            args.config,
            args.output,
        )
    except PublicationGateError as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, sort_keys=True))
        return 2

    print(json.dumps(audit, indent=2, sort_keys=True))
    if args.mode == "release":
        return 0 if audit["promotion_gate_pass"] else 2
    return 0 if audit["content_gate_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

