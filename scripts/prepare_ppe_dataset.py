"""Prepare licensed PPE COCO sources without downloading any data."""

import argparse
import json
from pathlib import Path

from buildguard.vision.ppe_dataset import prepare_dataset


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = prepare_dataset(args.source_manifest, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
