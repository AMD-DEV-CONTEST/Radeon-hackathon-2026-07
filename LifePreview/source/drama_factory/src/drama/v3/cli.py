"""Retired standalone Factory V3 execution CLI.

Model verification and generation now run through versioned Creative Hub
atomic capabilities and GPU workers.  Factory V3 files remain readable by the
cutover importer but are never a writable authority after activation.
"""

from __future__ import annotations

import sys


RETIRED_EXIT_CODE = 78


def main(argv: list[str] | None = None) -> int:
    del argv
    print(
        "drama-v3 已硬退役；请使用 Creative Hub 统一运行时和 GPU Worker。",
        file=sys.stderr,
    )
    return RETIRED_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
