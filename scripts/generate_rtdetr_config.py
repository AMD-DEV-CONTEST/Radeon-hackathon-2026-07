"""Generate a local RT-DETRv2 training data configuration."""

import argparse
import json
from pathlib import Path

from buildguard.vision.ppe_dataset import CANONICAL_CLASSES


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.dataset_dir.resolve()
    payload = {
        "dataset_root": str(root),
        "train_annotations": str(root / "annotations" / "train.json"),
        "val_annotations": str(root / "annotations" / "val.json"),
        "test_annotations": str(root / "annotations" / "test.json"),
        "classes": list(CANONICAL_CLASSES),
        "num_classes": len(CANONICAL_CLASSES),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
