"""Inspect and stage Screen-AI model artifacts.

Examples:
    python scripts/model_artifacts.py inventory
    python scripts/model_artifacts.py stage-yolo path/to/ui_detector_int8.onnx
    python scripts/model_artifacts.py stage-gguf path/to/qwen.gguf
    python scripts/model_artifacts.py list-files
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parents[1]
sys.path.insert(0, str(BACKEND))

from app.runtime.artifact_store import ArtifactStore  # noqa: E402


MODEL_DIR = ROOT / "ai_pc_operator" / "data" / "models"


def inventory(_: argparse.Namespace) -> int:
    store = ArtifactStore()
    print(json.dumps(store.inventory(), indent=2))
    return 0


def list_files(_: argparse.Namespace) -> int:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(MODEL_DIR.rglob("*")):
        if path.is_file():
            size_mb = path.stat().st_size / (1024**2)
            print(f"{size_mb:8.2f} MB  {path.relative_to(MODEL_DIR)}")
    return 0


def stage(source: Path, target_name: str) -> Path:
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(source)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    target = MODEL_DIR / target_name
    shutil.copy2(source, target)
    return target


def stage_yolo(args: argparse.Namespace) -> int:
    target = stage(args.source, "ui_detector_int8.onnx")
    print(f"staged YOLO ONNX: {target}")
    return 0


def stage_gguf(args: argparse.Namespace) -> int:
    target = stage(args.source, args.source.name)
    print(f"staged GGUF: {target}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(required=True)

    inv = sub.add_parser("inventory", help="show discovered artifacts")
    inv.set_defaults(func=inventory)

    files = sub.add_parser("list-files", help="list files saved under the model directory")
    files.set_defaults(func=list_files)

    yolo = sub.add_parser("stage-yolo", help="copy exported YOLO ONNX into backend model dir")
    yolo.add_argument("source", type=Path)
    yolo.set_defaults(func=stage_yolo)

    gguf = sub.add_parser("stage-gguf", help="copy Qwen GGUF into backend model dir")
    gguf.add_argument("source", type=Path)
    gguf.set_defaults(func=stage_gguf)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
