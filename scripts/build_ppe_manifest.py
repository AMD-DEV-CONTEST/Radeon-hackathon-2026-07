"""Rebuild the prepared PPE image hash manifest."""

import argparse
import json
from pathlib import Path

from buildguard.vision.ppe_dataset import sha256_file


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.dataset_dir.resolve()
    records = [
        {
            "path": str(path.relative_to(root)).replace("\\", "/"),
            "sha256": sha256_file(path),
        }
        for path in sorted((root / "images").rglob("*"))
        if path.is_file()
    ]
    target = args.output or root / "image_hash_manifest.json"
    target.write_text(
        json.dumps({"images": records}, indent=2) + "\n", encoding="utf-8"
    )
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
