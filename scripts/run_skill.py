#!/usr/bin/env python3
"""Run a selectable development skill and write a real project to disk."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_settings
from src.skills import SkillRegistry


def main() -> None:
    parser = argparse.ArgumentParser(description="PrivateLocalAgent skill runner")
    parser.add_argument("--list", action="store_true", help="list skills")
    parser.add_argument("--skill", type=str, default="", help="skill id or title")
    parser.add_argument("--name", type=str, default="", help="output project name")
    args = parser.parse_args()

    settings = load_settings()
    out = settings.resolve(settings.paths.generated_projects)
    reg = SkillRegistry(out)

    if args.list or not args.skill:
        print(reg.describe())
        if not args.skill:
            print("\nExample:\n  python scripts/run_skill.py --skill scaffold_private_agent_mini --name demo_agent")
            return

    result = reg.run_by_title(args.skill, {"name": args.name} if args.name else {})
    print(result.as_text())
    # prove files exist
    missing = [p for p in result.files_written if not Path(p).exists()]
    if missing:
        print("ERROR missing files:", missing)
        sys.exit(1)
    print("[ok] files exist on disk")


if __name__ == "__main__":
    main()
