from __future__ import annotations

import shutil
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    dist_dir = project_root / "dist" / "xenix"
    zip_path = project_root / "dist" / "xenix"

    if not dist_dir.is_dir():
        raise FileNotFoundError(
            f"Packaged directory not found: {dist_dir}\n"
            "Run 'pdm run package' first to create the bundle."
        )

    shutil.rmtree(str(zip_path) + ".zip", ignore_errors=True)
    shutil.make_archive(str(zip_path), "zip", dist_dir.parent, dist_dir.name)

    final_zip = project_root / "dist" / "xenix.zip"
    print(f"✓ Distribution zip created: {final_zip}")
    print(f"  Size: {final_zip.stat().st_size / (1024 * 1024):.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
