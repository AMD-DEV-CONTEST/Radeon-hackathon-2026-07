"""Retired legacy pipeline CLI.

The implementation modules remain importable only for proof readers, migration
adapters, and atomic capability compatibility.  Workflow execution is owned by
Creative Hub after the cutover.
"""

from __future__ import annotations

import sys


RETIRED_EXIT_CODE = 78


def main(argv: list[str] | None = None) -> int:
    del argv
    print(
        "drama-run 已硬退役；请通过 Creative Hub 统一工作流创建运行。",
        file=sys.stderr,
    )
    return RETIRED_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
