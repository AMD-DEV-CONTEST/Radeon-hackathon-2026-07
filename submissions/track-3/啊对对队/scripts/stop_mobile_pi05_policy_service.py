#!/usr/bin/env python3
"""Stop a local persistent PI0.5 policy service cleanly."""

from __future__ import annotations

import argparse
from pathlib import Path

from parcel_sorter.mobile_vla_service import shutdown_mobile_vla_service


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ready", type=Path, required=True)
    args = parser.parse_args()
    shutdown_mobile_vla_service(args.ready)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
