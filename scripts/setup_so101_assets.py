"""Fetch the SO-101 robot model (URDF/MJCF + meshes) into ``assets/robots/so101``.

The SO-101 simulation model is not bundled with this repo. This script pulls it
from the upstream ``TheRobotStudio/SO-ARM100`` GitHub repository, which ships both
a URDF and a MuJoCo (MJCF) description under ``Simulation/SO101/``:

    Simulation/SO101/so101_new_calib.urdf   # preferred (new calibration)
    Simulation/SO101/so101_old_calib.urdf
    Simulation/SO101/*.xml / scene.xml       # MJCF (MuJoCo) description
    Simulation/SO101/assets/*.stl            # collision/visual meshes

Genesis can load either MJCF (``gs.morphs.MJCF``) or URDF (``gs.morphs.URDF``);
this project defaults to the MJCF (see ``simulation/so101.py``). We ``git clone``
with sparse-checkout of only ``Simulation/SO101`` so we don't download the whole
(mesh-heavy) repo. ``git clone`` is used (not ``git init`` + ``pull``) so that
environment git wrappers which proxy GitHub HTTPS (e.g. via gh-proxy.org) can
intercept the fetch; if direct GitHub HTTPS fails, we retry through that proxy.

Usage:
    python scripts/setup_so101_assets.py            # fetch if missing
    python scripts/setup_so101_assets.py --force    # re-fetch even if present

If the network fetch fails, the script prints the MuJoCo Menagerie fallback
(``google-deepmind/mujoco_menagerie`` -> ``trs_so_arm100``) so you can populate
``assets/robots/so101`` manually.

NOTE: This must be run once on the Radeon (ROCm) machine with network access.
It only downloads files; it does not require a GPU.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from paths import SO101_DIR
from simulation.so101_mjcf_patch import patch_so101_grasp_geoms

# Upstream source of the SO-101 simulation model.
SOARM_REPO = os.environ.get(
    "SOARM_REPO",
    "https://github.com/TheRobotStudio/SO-ARM100.git",
)
SOARM_SUBDIR = "Simulation/SO101"
# When direct github.com HTTPS fails (broken CA / blocked), retry via this prefix.
# Set GITHUB_HTTPS_PROXY= to disable. Example: https://gh-proxy.org
_GITHUB_PROXY = os.environ.get("GITHUB_HTTPS_PROXY", "https://gh-proxy.org").rstrip("/")
# Fallback for manual population if the git fetch fails.
MENAGERIE_HINT = (
    "Fallback: clone google-deepmind/mujoco_menagerie and copy the\n"
    "  'trs_so_arm100' folder's *.xml + assets/ into:\n"
    f"  {SO101_DIR}\n"
    "  (https://github.com/google-deepmind/mujoco_menagerie/tree/main/trs_so_arm100)"
)

# Files we expect to exist after a successful fetch (at least one URDF or MJCF).
EXPECTED_URDF = "so101_new_calib.urdf"


def _have_model() -> bool:
    """True if a URDF or any MJCF (.xml) is already present under SO101_DIR."""
    if not SO101_DIR.is_dir():
        return False
    has_urdf = (SO101_DIR / EXPECTED_URDF).is_file() or any(SO101_DIR.glob("*.urdf"))
    has_mjcf = any(SO101_DIR.glob("*.xml"))
    return has_urdf or has_mjcf


def _clone_urls() -> list[str]:
    """Direct GitHub URL first, then optional HTTPS proxy rewrite."""
    urls = [SOARM_REPO]
    if _GITHUB_PROXY and "github.com" in SOARM_REPO and not SOARM_REPO.startswith(_GITHUB_PROXY):
        urls.append(f"{_GITHUB_PROXY}/{SOARM_REPO}")
    return urls


def _sparse_checkout(dest: Path) -> Path:
    """Clone SO-ARM100 via ``git clone`` and sparse-checkout ``Simulation/SO101``.

    Returns the path to the checked-out model directory.
    """
    dest.mkdir(parents=True, exist_ok=True)
    repo_dir = dest / "SO-ARM100"
    last_err: BaseException | None = None

    for url in _clone_urls():
        if repo_dir.exists():
            shutil.rmtree(repo_dir)
        print(f"[setup] git clone --depth 1 --sparse {url}")
        try:
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--filter=blob:none",
                    "--sparse",
                    url,
                    str(repo_dir),
                ],
                check=True,
            )
            subprocess.run(
                ["git", "sparse-checkout", "set", "--cone", SOARM_SUBDIR],
                cwd=repo_dir,
                check=True,
            )
            break
        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
            last_err = exc
            print(f"[setup] clone failed ({exc}); trying next URL if any ...", file=sys.stderr)
    else:
        assert last_err is not None
        raise last_err

    src = repo_dir / SOARM_SUBDIR
    if not src.is_dir():
        raise FileNotFoundError(f"Expected {src} after checkout, not found.")
    return src


def _copy_model(src: Path) -> None:
    """Copy the checked-out Simulation/SO101 tree into SO101_DIR (flattened)."""
    if not src.is_dir():
        raise FileNotFoundError(f"Expected {src} after checkout, not found.")
    if SO101_DIR.exists():
        shutil.rmtree(SO101_DIR)
    shutil.copytree(src, SO101_DIR)


def setup_assets(force: bool = False) -> Path:
    """Ensure the SO-101 model is present under SO101_DIR; fetch it if not.

    Returns the SO101_DIR path. Idempotent: a no-op when the model already exists
    (unless ``force``).
    """
    if _have_model() and not force:
        print(f"[setup] SO-101 model already present at {SO101_DIR}")
        patched = patch_so101_grasp_geoms(SO101_DIR)
        if patched:
            print(f"[setup] patched fingertip pads into: {[p.name for p in patched]}")
        return SO101_DIR

    print(f"[setup] fetching SO-101 model from {SOARM_REPO} ({SOARM_SUBDIR}) ...")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src = _sparse_checkout(Path(tmp))
            _copy_model(src)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
        print(f"[setup] ERROR: automatic fetch failed: {exc}\n", file=sys.stderr)
        print(MENAGERIE_HINT, file=sys.stderr)
        raise SystemExit(1) from exc

    if not _have_model():
        print("[setup] ERROR: fetch completed but no URDF/MJCF found.\n", file=sys.stderr)
        print(MENAGERIE_HINT, file=sys.stderr)
        raise SystemExit(1)

    patched = patch_so101_grasp_geoms(SO101_DIR)
    n_meshes = len(list(SO101_DIR.rglob("*.stl"))) + len(list(SO101_DIR.rglob("*.STL")))
    print(f"[setup] done -> {SO101_DIR} ({n_meshes} mesh files)")
    if patched:
        print(f"[setup] patched fingertip pads into: {[p.name for p in patched]}")
    return SO101_DIR


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch the SO-101 simulation model.")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if already present.")
    args = parser.parse_args()
    setup_assets(force=args.force)


if __name__ == "__main__":
    main()
