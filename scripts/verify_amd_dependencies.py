"""Verify portable runtime, training, and evaluation Python dependencies."""

from __future__ import annotations

import argparse
import importlib
import json
from importlib import metadata
from typing import Final

MODULES: Final[dict[str, tuple[tuple[str, str], ...]]] = {
    "runtime": (
        ("torch", "torch"),
        ("transformers", "transformers"),
        ("numpy", "numpy"),
        ("opencv-python-headless", "cv2"),
        ("pillow", "PIL"),
    ),
    "training": (("scipy", "scipy"),),
    "evaluation": (("pycocotools", "pycocotools"),),
}


def required_modules(profile: str) -> tuple[tuple[str, str], ...]:
    selected = list(MODULES["runtime"])
    if profile in {"training", "evaluation"}:
        selected.extend(MODULES["training"])
    if profile == "evaluation":
        selected.extend(MODULES["evaluation"])
    return tuple(selected)


def verify(profile: str) -> tuple[int, dict[str, object]]:
    versions: dict[str, str] = {}
    missing: list[str] = []
    for distribution, module in required_modules(profile):
        try:
            importlib.import_module(module)
            versions[distribution] = metadata.version(distribution)
        except (ImportError, metadata.PackageNotFoundError) as exc:
            missing.append(f"{distribution}: {exc}")
    result: dict[str, object] = {
        "status": "PASS" if not missing else "FAIL",
        "profile": profile,
        "versions": versions,
        "missing": missing,
    }
    return (0 if not missing else 2), result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        choices=tuple(MODULES),
        default="runtime",
    )
    args = parser.parse_args()
    code, result = verify(args.profile)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
