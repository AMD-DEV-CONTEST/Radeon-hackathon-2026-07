#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.gtm_platform_native_challenger import (  # noqa: E402
    build_platform_native_challenger_plan,
)


def _inside_project(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as error:
        raise argparse.ArgumentTypeError("path must remain inside the project root") from error
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile frozen B2B and B2C thirteen-surface local challenger plans."
    )
    parser.add_argument(
        "--briefs",
        type=_inside_project,
        default=ROOT / "config/platform-native-challenger-briefs-v1.json",
    )
    parser.add_argument(
        "--output-dir",
        type=_inside_project,
        default=ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v1",
    )
    args = parser.parse_args()
    source = json.loads(args.briefs.read_text(encoding="utf-8"))
    briefs = source.get("briefs")
    if not isinstance(briefs, list) or len(briefs) != 2:
        raise SystemExit("brief set must contain exactly one B2B and one B2C brief")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, str] = {}
    for brief in briefs:
        business_model = str(brief.get("business_model", ""))
        plan = build_platform_native_challenger_plan(
            brief, business_model=business_model
        )
        output = args.output_dir / f"{business_model}-plan.json"
        atomic_write_text(
            output,
            json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        outputs[str(output.relative_to(ROOT))] = plan["content_sha256"]
    print(json.dumps({"outputs": outputs}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
