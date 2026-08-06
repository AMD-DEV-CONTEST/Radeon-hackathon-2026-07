"""Verify (and if needed populate) local assets for the manipulation scene.

Assets live as real copied files under ``assets/`` (YCB meshes + the Franka model),
so the scene is self-contained and needs no symlinks. This script is idempotent:

* If an asset is already present (real files), it is left untouched.
* If an asset is missing, it is copied from the source datasets as a fallback
  (originals in ``mani_skill_dataset``; scaled fruit copies baked by ``scale_ycb.py``
  in ``mani_skill_dataset_scaled``; the Franka model from the genesis assets).
* If something is missing and no source exists to populate it, a clear error is raised.
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent  # franka_fruit_pick/ package dir
REPO_ROOT = ROOT.parent  # repository root -- bundled assets live here
ASSETS = REPO_ROOT / "assets"
# Fallback sources, used only in-place during development to populate assets/ (they are
# NOT shipped): the original YCB dataset, the scaled fruit copies baked by scale_ycb.py,
# and the Franka model. When assets/ is already bundled, these are never touched.
_DEV_SOURCE_ROOT = REPO_ROOT.parent
YCB_SOURCE = _DEV_SOURCE_ROOT / "mani_skill_dataset"
YCB_SCALED_SOURCE = _DEV_SOURCE_ROOT / "mani_skill_dataset_scaled"
FRANKA_SOURCE = _DEV_SOURCE_ROOT / "genesis" / "assets" / "xml" / "franka_emika_panda"

YCB_OBJECTS = (
    # "003_cracker_box",
    # "006_mustard_bottle",
    "011_banana",
    "013_apple",
    "014_lemon",
    "016_pear",
    "017_orange",
    "018_plum",
    "024_bowl",
    "025_mug",
)

# Objects whose fallback source is the scaled dataset instead of the original YCB dataset.
YCB_SCALED_OBJECTS = frozenset({"013_apple", "017_orange"})

# Files each YCB object directory must contain for the scene to load it.
REQUIRED_OBJECT_FILES = ("textured.obj", "collision.ply")
# File whose presence indicates the Franka model is populated.
ROBOT_REQUIRED_FILE = "panda.xml"


def _have_object(dst: Path) -> bool:
    return dst.is_dir() and all((dst / f).exists() for f in REQUIRED_OBJECT_FILES)


def _copy_tree(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def setup_assets() -> Path:
    ycb_dir = ASSETS / "ycb"
    robot_dir = ASSETS / "robots" / "franka"
    missing: list[str] = []

    for name in YCB_OBJECTS:
        dst = ycb_dir / name
        if _have_object(dst):
            continue  # real files already in place -- leave them untouched
        source_root = YCB_SCALED_SOURCE if name in YCB_SCALED_OBJECTS else YCB_SOURCE
        src = source_root / name
        if src.is_dir():
            _copy_tree(src, dst)
        else:
            missing.append(f"ycb/{name} (no source at {src})")

    if not (robot_dir / ROBOT_REQUIRED_FILE).exists():
        if FRANKA_SOURCE.is_dir():
            _copy_tree(FRANKA_SOURCE, robot_dir)
        else:
            missing.append(f"robots/franka (no source at {FRANKA_SOURCE})")

    if missing:
        raise FileNotFoundError("Missing assets and no source to populate them:\n  " + "\n  ".join(missing))
    return ASSETS


def main() -> None:
    assets_dir = setup_assets()
    print(f"Assets ready at: {assets_dir}")


if __name__ == "__main__":
    main()
