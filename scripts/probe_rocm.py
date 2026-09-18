"""Standalone environment probe entry point."""

from pathlib import Path

from rich.console import Console

from buildguard.config import load_settings
from buildguard.system.environment_probe import EnvironmentProbe


def main() -> None:
    report = EnvironmentProbe(load_settings(Path("configs/app.yaml"))).probe()
    Console().print_json(report.model_dump_json())


if __name__ == "__main__":
    main()
