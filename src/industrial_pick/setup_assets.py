"""Verify local assets for the industrial manipulation scene.

Assets live as real files under ``assets/`` (industrial STL parts + the YCB bowl +
the Franka model), so the scene is self-contained. Unlike the fruit reference pipeline's version
this is verify-only: every asset is bundled with the repo, so anything missing is a
packaging error, not something to auto-populate.

Checks:
* ``assets/industrial/{gear,nut,bolt}.stl``      -- the three pick objects
* ``assets/ycb/024_bowl/{textured.obj,collision.ply}`` -- the place container
* ``assets/robots/franka/panda.xml``             -- the robot model
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent  # industrial_pick/ package dir
REPO_ROOT = ROOT.parent  # repository root -- bundled assets live here
ASSETS = REPO_ROOT / "assets"

INDUSTRIAL_OBJECTS = ("gear", "nut", "bolt")
REQUIRED_BOWL_FILES = ("textured.obj", "collision.ply")
ROBOT_REQUIRED_FILE = "panda.xml"


def setup_assets() -> Path:
    missing: list[str] = []

    for name in INDUSTRIAL_OBJECTS:
        if not (ASSETS / "industrial" / f"{name}.stl").is_file():
            missing.append(f"industrial/{name}.stl")

    bowl_dir = ASSETS / "ycb" / "024_bowl"
    if not bowl_dir.is_dir() or not all((bowl_dir / f).exists() for f in REQUIRED_BOWL_FILES):
        missing.append("ycb/024_bowl (textured.obj + collision.ply)")

    if not (ASSETS / "robots" / "franka" / ROBOT_REQUIRED_FILE).exists():
        missing.append("robots/franka (panda.xml)")

    if missing:
        raise FileNotFoundError(
            "Missing bundled assets under " + str(ASSETS) + ":\n  " + "\n  ".join(missing)
        )
    return ASSETS


def main() -> None:
    assets_dir = setup_assets()
    print(f"Assets ready at: {assets_dir}")


if __name__ == "__main__":
    main()
