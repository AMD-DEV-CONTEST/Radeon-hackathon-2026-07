#!/usr/bin/env python3
"""Build workflow / app configs from requirements, or export workflows."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Requirement → local config / export")
    parser.add_argument(
        "action",
        choices=["workflow", "productivity", "enterprise", "rag", "developer", "multi", "export"],
        help="build target or export",
    )
    parser.add_argument("text", help="requirement text, or workflow_id when action=export")
    args = parser.parse_args()

    if args.action == "export":
        from src.agent.workflow_export import export_all_formats_text

        print(export_all_formats_text(args.text))
        return

    if args.action == "workflow":
        from src.agent.workflow_builder import build_and_summarize

        print(build_and_summarize(args.text))
        return

    from src.apps.app_builder import build_for_app

    print(build_for_app(args.action, args.text).summary)


if __name__ == "__main__":
    main()
