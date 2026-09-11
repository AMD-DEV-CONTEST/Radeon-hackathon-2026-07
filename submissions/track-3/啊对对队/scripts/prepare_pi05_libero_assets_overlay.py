#!/usr/bin/env python3
"""Validate official LIBERO assets and expose them to the isolated package."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


EXPECTED_ASSET_FILES = 586
EXPECTED_ASSET_BYTES = 422_320_936
REQUIRED_SCENE = Path("scenes/libero_tabletop_base_style.xml")


def directory_stats(root: Path) -> tuple[int, int]:
    files = [path for path in root.rglob("*") if path.is_file()]
    return len(files), sum(path.stat().st_size for path in files)


def prepare_assets_link(
    assets_root: Path,
    package_root: Path,
    *,
    expected_files: int = EXPECTED_ASSET_FILES,
    expected_bytes: int = EXPECTED_ASSET_BYTES,
) -> dict[str, object]:
    assets_root = assets_root.resolve(strict=True)
    package_root = package_root.resolve(strict=True)
    files, bytes_total = directory_stats(assets_root)
    if (files, bytes_total) != (expected_files, expected_bytes):
        raise RuntimeError(
            "LIBERO asset mismatch: "
            f"got files={files}, bytes={bytes_total}; "
            f"expected files={expected_files}, bytes={expected_bytes}"
        )
    if not (assets_root / REQUIRED_SCENE).is_file():
        raise FileNotFoundError(assets_root / REQUIRED_SCENE)

    assets_link = package_root / "assets"
    created = False
    if os.path.lexists(assets_link):
        if not assets_link.is_symlink():
            raise RuntimeError(f"refusing to replace non-symlink asset path: {assets_link}")
        linked_root = assets_link.resolve(strict=True)
        if linked_root != assets_root:
            raise RuntimeError(
                f"asset link points to {linked_root}, expected {assets_root}"
            )
    else:
        assets_link.symlink_to(assets_root, target_is_directory=True)
        created = True

    return {
        "schema_version": 1,
        "protocol": "pi05-libero-assets-overlay-v1",
        "status": "pass",
        "created": created,
        "assets_root": str(assets_root),
        "package_assets_link": str(assets_link),
        "resolved_link_target": str(assets_link.resolve(strict=True)),
        "files": files,
        "bytes": bytes_total,
        "required_scene": str(REQUIRED_SCENE),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets-root", type=Path, default=Path("/workspace/libero-assets"))
    parser.add_argument(
        "--package-root",
        type=Path,
        default=Path("/workspace/libero-overlay/libero/libero"),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = prepare_assets_link(args.assets_root, args.package_root)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
