#!/usr/bin/env python3
"""Emit a bounded ROCm runtime receipt without dumping environment variables."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mantis_rocm_bridge.rocm import collect_rocm_receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-rocm", action="store_true")
    args = parser.parse_args()
    receipt = collect_rocm_receipt()
    rendered = json.dumps(receipt, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 2 if args.require_rocm and not receipt["strict_rocm_pass"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

