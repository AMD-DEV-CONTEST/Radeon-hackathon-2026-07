"""Standalone local LLM benchmark entry point."""

from pathlib import Path

from rich.console import Console

from buildguard.benchmark import run_benchmark
from buildguard.config import load_settings


def main() -> None:
    result = run_benchmark(load_settings(Path("configs/app.yaml")))
    Console().print_json(result.model_dump_json())


if __name__ == "__main__":
    main()
