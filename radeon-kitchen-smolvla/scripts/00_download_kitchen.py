"""
Download free Rustic Kitchen assets from World Labs Marble.

Downloads all exportable assets for the Rustic Kitchen scene:
  - HQ mesh GLB   (~600k triangles, textures) -> Genesis visual layer
  - Collider GLB   (~100-200k triangles)       -> Genesis collision layer
  - Gaussian Splat PLY (2M splats)             -> for future GS rendering
  - 360 Panorama PNG  (2560x1280)             -> reference / skybox

Genesis currently only renders meshes (GLB); the Gaussian Splat PLY is
downloaded for future use when Genesis adds native GS rendering support,
or for standalone viewers like Spark (https://sparkjs.dev/).

Reference: https://docs.worldlabs.ai/marble/export/specs#example-files

Usage:
    python 00_download_kitchen.py                  # download all assets
    python 00_download_kitchen.py --force          # re-download even if files exist
    python 00_download_kitchen.py --mesh-only      # skip large PLY splat file
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

CDN_BASE = (
    "https://wlt-ai-cdn.art/example_exports/rustic_kitchen_with_natural_light"
)

MESH_ASSETS = {
    "rustic_kitchen_hq.glb": f"{CDN_BASE}/rustic_kitchen_with_natural_light_hq.glb",
    "rustic_kitchen_collider.glb": f"{CDN_BASE}/rustic_kitchen_with_natural_light_collider.glb",
}

SPLAT_ASSETS = {
    "rustic_kitchen_2m.ply": f"{CDN_BASE}/rustic_kitchen_with_natural_light_2m.ply",
    "rustic_kitchen_pano.png": f"{CDN_BASE}/rustic_kitchen_with_natural_light_pano.png",
}


def download_file(url: str, dest: Path, *, force: bool = False) -> None:
    if dest.exists() and not force:
        size_mb = dest.stat().st_size / (1024 * 1024)
        print(f"  [skip] {dest.name} already exists ({size_mb:.1f} MB)")
        return

    print(f"  [download] {dest.name} <- {url}")
    try:
        urllib.request.urlretrieve(url, str(dest))
    except Exception as exc:
        print(f"  [error] failed to download {dest.name}: {exc}", file=sys.stderr)
        if dest.exists():
            dest.unlink()
        raise

    size_mb = dest.stat().st_size / (1024 * 1024)
    print(f"  [ok] {dest.name} ({size_mb:.1f} MB)")


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    default_asset_dir = script_dir.parent / "assets" / "rustic_kitchen"

    ap = argparse.ArgumentParser(
        description="Download Rustic Kitchen assets (mesh + Gaussian Splats)"
    )
    ap.add_argument(
        "--asset-dir",
        type=Path,
        default=default_asset_dir,
        help=f"Directory to save assets (default: {default_asset_dir})",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if files already exist",
    )
    ap.add_argument(
        "--mesh-only",
        action="store_true",
        help="Download only mesh GLB files, skip large Gaussian Splat PLY (~250 MB)",
    )
    args = ap.parse_args()

    args.asset_dir.mkdir(parents=True, exist_ok=True)
    print(f"Asset directory: {args.asset_dir}")

    print("\n--- Mesh assets (for Genesis simulation) ---")
    for filename, url in MESH_ASSETS.items():
        dest = args.asset_dir / filename
        download_file(url, dest, force=args.force)

    if not args.mesh_only:
        print("\n--- Gaussian Splat + Panorama (for future GS rendering / offline viz) ---")
        for filename, url in SPLAT_ASSETS.items():
            dest = args.asset_dir / filename
            download_file(url, dest, force=args.force)
    else:
        print("\n[skip] --mesh-only: skipping Gaussian Splat PLY and panorama")

    print("\nDone. Files ready for 01_inspect_scene.py / 03_pick_cube.py")
    print("  Mesh GLB -> Genesis (visual + collision)")
    print("  Splat PLY -> future Genesis GS rendering or Spark viewer")


if __name__ == "__main__":
    main()
