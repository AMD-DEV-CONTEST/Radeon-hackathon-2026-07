#!/usr/bin/env python3
"""Audit a frozen PI0.5 held-out observation collection without probing a model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parcel_sorter.mobile_pi05_heldout_capture import (
    validate_pi05_heldout_collection,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--workspace-block", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    panel = json.loads(args.panel.read_text(encoding="utf-8"))
    block = json.loads(args.workspace_block.read_text(encoding="utf-8"))
    result = validate_pi05_heldout_collection(args.collection, panel, block)
    payload = json.dumps(result, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
