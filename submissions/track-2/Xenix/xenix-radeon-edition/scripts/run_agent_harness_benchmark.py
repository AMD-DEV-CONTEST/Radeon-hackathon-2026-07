"""Thin pytest entry point for explicit real-provider Agent Harness benchmarks."""

from __future__ import annotations

import sys

from run_pytest import main as run_pytest


_PYTEST_PLUGIN = "benchmarks.agent_harness._infra.pytest_plugin"
_BENCHMARK_ROOT = "benchmarks/agent_harness"


def main(argv: list[str] | None = None) -> int:
    """Delegate all collection, selection, and lifecycle control to pytest."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    return run_pytest(
        [
            "--direct",
            "-p",
            _PYTEST_PLUGIN,
            _BENCHMARK_ROOT,
            "--run-agent-harness",
            *arguments,
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
