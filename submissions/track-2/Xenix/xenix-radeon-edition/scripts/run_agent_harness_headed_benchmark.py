"""Visible desktop entry point for explicit real-provider Agent benchmarks."""

from __future__ import annotations

import sys

from run_agent_harness_benchmark import main as run_benchmark


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    return run_benchmark(["--headed", *arguments])


if __name__ == "__main__":
    raise SystemExit(main())
