"""Central path configuration.

Everything is resolved from environment variables so the project is not tied to
one machine's layout. Defaults assume the repo layout described in the README.

    V2M_WORKDIR    where generated artifacts go (motions, checkpoints, videos)
    V2M_GVHMR      GVHMR checkout
    V2M_GMR        GMR checkout
    V2M_PY_MJX     python of the `mjx` venv
    V2M_PY_GVHMR   python of the `gvhmr` venv
    V2M_PY_GMR     python of the `gmr` venv

Check your setup with:

    python -m config
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _p(env: str, default: str | Path) -> Path:
    return Path(os.environ.get(env, str(default))).expanduser()


# ---- where generated artifacts live -----------------------------------------
WORKDIR = _p("V2M_WORKDIR", REPO / "workdir")

MOTIONS_RAW = WORKDIR / "motions"        # GMR .pkl
MOTIONS_MJX = WORKDIR / "motions_mjx"    # converted .npz
MOTIONS_BM = WORKDIR / "motions_bm"      # + body poses and velocities
TRAIN_OUT = WORKDIR / "train"            # checkpoints
RENDER_OUT = WORKDIR / "render"          # videos
DEPLOY_OUT = WORKDIR / "deploy"          # exported NumPy weights
DOWNLOADS = WORKDIR / "downloads"        # zips served by the web UI
UPLOADS = WORKDIR / "uploads"            # staged input videos

# ---- third-party checkouts ---------------------------------------------------
GVHMR = _p("V2M_GVHMR", Path.home() / "GVHMR")
GMR = _p("V2M_GMR", Path.home() / "GMR")
UNITREE_MUJOCO = _p("V2M_UNITREE_MUJOCO", Path.home() / "unitree_mujoco")

# ---- interpreters ------------------------------------------------------------
# The three environments cannot coexist (numpy 2.x vs 1.26, jax vs torch), so
# each stage runs as a subprocess against its own interpreter.
PY_MJX = str(_p("V2M_PY_MJX", Path.home() / "venvs/mjx/bin/python"))
PY_GVHMR = str(_p("V2M_PY_GVHMR", Path.home() / "venvs/gvhmr/bin/python"))
PY_GMR = str(_p("V2M_PY_GMR", Path.home() / "venvs/gmr/bin/python"))

SRC = REPO / "src"


def scene_xml() -> str:
    """Playground's flat-terrain G1 scene, located inside the installed package.

    Only usable via from_xml_string() paired with get_assets(): its mesh paths
    are resolved by Playground's own asset loader, not relative to the file.
    Anything calling from_xml_path() wants scene_xml_standalone() instead.
    """
    from mujoco_playground._src.locomotion.g1 import g1_constants as c
    return c.FEET_ONLY_FLAT_TERRAIN_XML.as_posix()


def scene_xml_standalone() -> str:
    """Menagerie's G1 scene, for plain mujoco.MjModel.from_xml_path().

    from_xml_path() resolves meshes relative to the XML, so it needs the scene
    that actually sits next to its assets/ directory. Handing it scene_xml()
    fails on the first mesh with a path under site-packages/mujoco_menagerie,
    which is not where Playground installs menagerie.
    """
    from mujoco_playground._src import mjx_env
    return (mjx_env.MENAGERIE_PATH / "unitree_g1" / "scene_mjx.xml").as_posix()


def ensure_dirs() -> None:
    for d in (WORKDIR, MOTIONS_RAW, MOTIONS_MJX, MOTIONS_BM,
              TRAIN_OUT, RENDER_OUT, DEPLOY_OUT, DOWNLOADS, UPLOADS):
        d.mkdir(parents=True, exist_ok=True)


def doctor() -> int:
    """Print what is configured and whether it exists. Returns 0 if usable."""
    bad = 0
    print("repo      ", REPO)
    print("workdir   ", WORKDIR)
    print()
    # unitree_mujoco only exists after setup.sh --with-dds, so its absence is
    # normal and should not read as a broken install.
    for label, path, need, opt in (
            ("GVHMR", GVHMR, False, ""),
            ("GMR", GMR, False, ""),
            ("unitree_mujoco", UNITREE_MUJOCO, False, "  (optional: --with-dds)"),
            ("python (mjx)", Path(PY_MJX), True, ""),
            ("python (gvhmr)", Path(PY_GVHMR), False, ""),
            ("python (gmr)", Path(PY_GMR), False, "")):
        ok = path.exists()
        if need and not ok:
            bad += 1
        mark = "OK " if ok else ("--     " if opt else "MISSING")
        print(f"  {mark}  {label:<16} {path}{'' if ok else opt}")

    print()
    try:
        import jax
        backend = jax.default_backend()
        print(f"  {'OK ' if backend == 'gpu' else 'WARN'}  jax backend      "
              f"{backend}  {jax.devices()}")
        if backend != "gpu":
            print("        JAX is not using the GPU — training will be unusably slow.")
            bad += 1
    except Exception as e:                                   # noqa: BLE001
        print(f"  MISSING  jax              {e}")
        bad += 1

    try:
        print(f"  OK       scene xml        {scene_xml()}")
    except Exception as e:                                   # noqa: BLE001
        print(f"  MISSING  mujoco_playground {e}")
        bad += 1

    print()
    print("usable" if bad == 0 else f"{bad} problem(s) — see README §5")
    return bad


if __name__ == "__main__":
    ensure_dirs()
    sys.exit(1 if doctor() else 0)
