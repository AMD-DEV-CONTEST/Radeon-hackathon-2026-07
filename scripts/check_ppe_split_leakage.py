"""Fail when a group or identical image crosses PPE dataset splits."""

import argparse
import json
from pathlib import Path

from buildguard.vision.ppe_dataset import leakage_issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    issues = leakage_issues(args.manifest)
    print(json.dumps({"valid": not issues, "issues": issues}, ensure_ascii=False))
    return 2 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
