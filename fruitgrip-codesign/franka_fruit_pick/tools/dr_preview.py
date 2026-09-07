"""M4 domain randomization -- Layer-A visual preview / comparison tool.

Renders the scene under several Layer-A appearance domains (a baseline with DR off plus
one tile per seed) and stitches a labeled montage, so you can eyeball what the
``SceneDomainRandomizationConfig`` knobs actually do -- reproducibly, into
``eval_results/dr_preview/`` instead of dumping PNGs into the repo root.

Each domain is rendered in its own subprocess (a fresh ``gs.init`` + ``scene.build``),
because Genesis is happiest with a single built scene per process. Given the same
``--seeds`` and knob values, the montage is fully reproducible.

Usage:
    # 4 seeds + baseline, recolor objects, jitter table + FOV
    uv run python franka_fruit_pick/tools/dr_preview.py \
        --seeds 0 1 2 3 --object-color --table-jitter 0.15 --fov-jitter 2.0

    # nuisance-only (keep original object textures), also montage the wrist cam
    uv run python franka_fruit_pick/tools/dr_preview.py --seeds 0 1 2 --table-jitter 0.2 --wrist

Outputs (under eval_results/dr_preview/ by default):
    frames/world_baseline.png, frames/world_seed{K}.png, ...   (per-domain renders)
    world_montage.png            (+ wrist_montage.png when --wrist)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import cv2
import imageio.v2 as imageio
import numpy as np

# This tool lives in tools/; put the package dir (its parent) on sys.path so the flat
# sibling imports (inside the worker/orchestrator functions below) resolve.
_PKG = Path(__file__).resolve().parent.parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from paths import EVAL_RESULTS_DIR

DEFAULT_OUT = EVAL_RESULTS_DIR / "dr_preview"


# ---------------------------------------------------------------------------
# Worker: render a single domain in an isolated process.
# ---------------------------------------------------------------------------


def _run_worker(args: argparse.Namespace) -> None:
    """Build one scene under the requested Layer-A config and save camera frame(s)."""
    import genesis as gs

    from build_scene import SceneDomainRandomizationConfig, build_scene
    from scene_config import FRANKA_QPOS

    scene_dr = SceneDomainRandomizationConfig(
        enabled=args.dr_enabled,
        table_color_jitter=args.table_jitter,
        randomize_object_color=args.object_color,
        fov_jitter_deg=args.fov_jitter,
        seed=args.seed,
    )

    gs.init(backend=gs.cpu if args.cpu else gs.gpu)
    bundle = build_scene(
        show_viewer=False,
        n_envs=1,
        add_world_cam=True,
        add_wrist_cam=bool(args.wrist_out),
        scene_dr=scene_dr,
    )

    hold_qpos = np.array(FRANKA_QPOS)
    for _ in range(args.steps):
        bundle.franka.control_dofs_position(hold_qpos)
        bundle.scene.step()
        bundle.update_wrist_cam()

    if args.world_out and bundle.world_cam is not None:
        Path(args.world_out).parent.mkdir(parents=True, exist_ok=True)
        imageio.imwrite(args.world_out, bundle.world_cam.render(rgb=True)[0])
    if args.wrist_out and bundle.wrist_cam is not None:
        Path(args.wrist_out).parent.mkdir(parents=True, exist_ok=True)
        imageio.imwrite(args.wrist_out, bundle.wrist_cam.render(rgb=True)[0])


# ---------------------------------------------------------------------------
# Orchestrator: spawn one worker per domain, then stitch a labeled montage.
# ---------------------------------------------------------------------------


def _spawn_worker(*, label_flags: list[str], world_out: Path, wrist_out: Path | None) -> None:
    cmd = [sys.executable, str(Path(__file__).resolve()), "--worker", "--world-out", str(world_out)]
    if wrist_out is not None:
        cmd += ["--wrist-out", str(wrist_out)]
    cmd += label_flags
    subprocess.run(cmd, check=True)


def _label_tile(img: np.ndarray, text: str, tile_w: int) -> np.ndarray:
    """Resize an RGB frame to width ``tile_w`` and draw a caption bar on top."""
    h, w = img.shape[:2]
    tile_h = int(round(h * tile_w / w))
    tile = cv2.resize(img, (tile_w, tile_h), interpolation=cv2.INTER_AREA)
    bar_h = max(24, tile_w // 20)
    bar = np.full((bar_h, tile_w, 3), 30, dtype=np.uint8)
    cv2.putText(bar, text, (8, int(bar_h * 0.72)), cv2.FONT_HERSHEY_SIMPLEX,
                bar_h / 40.0, (240, 240, 240), 1, cv2.LINE_AA)
    return np.vstack([bar, tile])


def _montage(tiles: list[np.ndarray], cols: int) -> np.ndarray:
    """Arrange equal-sized tiles into a grid, padding the final row."""
    rows = (len(tiles) + cols - 1) // cols
    th, tw = tiles[0].shape[:2]
    canvas = np.full((rows * th, cols * tw, 3), 30, dtype=np.uint8)
    for i, tile in enumerate(tiles):
        r, c = divmod(i, cols)
        canvas[r * th:(r + 1) * th, c * tw:(c + 1) * tw] = tile
    return canvas


def _build_montage(
    frames_dir: Path, names: list[str], labels: list[str], out_path: Path, tile_w: int, cols: int
) -> None:
    tiles = []
    for name, label in zip(names, labels):
        path = frames_dir / name
        if not path.exists():
            print(f"[dr_preview] WARN missing frame {path}, skipping tile")
            continue
        tiles.append(_label_tile(imageio.imread(path), label, tile_w))
    if not tiles:
        print(f"[dr_preview] no frames to montage for {out_path.name}")
        return
    imageio.imwrite(out_path, _montage(tiles, cols))
    print(f"[dr_preview] wrote {out_path}")


def _orchestrate(args: argparse.Namespace) -> None:
    out_dir = Path(args.out)
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    # One domain per tile: an optional DR-off baseline, then one per seed.
    domains: list[tuple[str, str, bool, int | None]] = []  # (tag, label, dr_enabled, seed)
    if not args.no_baseline:
        domains.append(("baseline", "baseline (DR off)", False, None))
    for seed in args.seeds:
        domains.append((f"seed{seed}", f"seed={seed}", True, seed))

    knob_flags = [
        "--table-jitter", str(args.table_jitter),
        "--fov-jitter", str(args.fov_jitter),
        "--steps", str(args.steps),
    ]
    if args.object_color:
        knob_flags.append("--object-color")
    if args.cpu:
        knob_flags.append("--cpu")

    for tag, label, dr_enabled, seed in domains:
        world_out = frames_dir / f"world_{tag}.png"
        wrist_out = frames_dir / f"wrist_{tag}.png" if args.wrist else None
        flags = list(knob_flags)
        if dr_enabled:
            flags.append("--dr-enabled")
        flags += ["--seed", str(seed if seed is not None else 0)]
        print(f"[dr_preview] rendering {label} ...")
        _spawn_worker(label_flags=flags, world_out=world_out, wrist_out=wrist_out)

    tags = [d[0] for d in domains]
    labels = [d[1] for d in domains]
    cols = args.cols or min(len(domains), 3)
    _build_montage(frames_dir, [f"world_{t}.png" for t in tags], labels,
                   out_dir / "world_montage.png", args.tile_width, cols)
    if args.wrist:
        _build_montage(frames_dir, [f"wrist_{t}.png" for t in tags], labels,
                       out_dir / "wrist_montage.png", args.tile_width, cols)


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview M4 Layer-A domain randomization as a montage.")
    # Worker mode (internal).
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--dr-enabled", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--world-out", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--wrist-out", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--seed", type=int, default=0, help=argparse.SUPPRESS)

    # Orchestrator knobs.
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2, 3], help="Appearance-domain seeds to render.")
    parser.add_argument("--table-jitter", type=float, default=0.15, help="+/- per-RGB-channel table color jitter.")
    parser.add_argument("--object-color", action="store_true", help="Recolor objects within DR_APPEARANCE_PRIORS.")
    parser.add_argument("--fov-jitter", type=float, default=0.0, help="+/- deg jitter on both cameras' vertical FOV.")
    parser.add_argument("--no-baseline", action="store_true", help="Omit the DR-off baseline tile.")
    parser.add_argument("--wrist", action="store_true", help="Also render + montage the wrist camera.")
    parser.add_argument("--cpu", action="store_true", help="Use the CPU backend.")
    parser.add_argument("--steps", type=int, default=30, help="Settle steps before rendering.")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output directory.")
    parser.add_argument("--tile-width", type=int, default=512, help="Per-tile width in the montage (px).")
    parser.add_argument("--cols", type=int, default=None, help="Montage columns (default: min(n, 3)).")
    args = parser.parse_args()

    if args.worker:
        _run_worker(args)
    else:
        _orchestrate(args)


if __name__ == "__main__":
    main()
