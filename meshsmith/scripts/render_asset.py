"""Offscreen beauty/turntable renders of a generated asset (no GPU viewer needed).

    python scripts/render_asset.py outputs/<run>/<slug>.glb --out shot.png
    python scripts/render_asset.py outputs/<run>/<slug>.glb --turntable 24 --out frames/
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import trimesh
from PIL import Image


def look_at_pose(eye, center):
    fwd = center - eye
    fwd = fwd / np.linalg.norm(fwd)
    right = np.cross(fwd, [0, 1, 0])
    right = right / np.linalg.norm(right)
    up = np.cross(right, fwd)
    pose = np.eye(4)
    pose[:3, 0], pose[:3, 1], pose[:3, 2], pose[:3, 3] = right, up, -fwd, eye
    return pose


def render(mesh: trimesh.Trimesh, azimuth_deg: float, size: int = 900) -> Image.Image:
    import pyrender

    scene = pyrender.Scene(bg_color=[248, 248, 250, 255], ambient_light=[0.35, 0.35, 0.38])
    scene.add(pyrender.Mesh.from_trimesh(mesh, smooth=len(mesh.faces) < 200_000))
    bounds = mesh.bounds
    center = bounds.mean(axis=0)
    radius = float(np.linalg.norm(bounds[1] - bounds[0]))
    az = np.radians(azimuth_deg)
    eye = center + radius * np.array([1.15 * np.sin(az), 0.45, 1.15 * np.cos(az)])
    pose = look_at_pose(eye, center)
    scene.add(pyrender.PerspectiveCamera(yfov=np.pi / 5), pose=pose)
    scene.add(pyrender.DirectionalLight(intensity=3.2), pose=pose)
    r = pyrender.OffscreenRenderer(size, size)
    color, _ = r.render(scene)
    r.delete()
    return Image.fromarray(color)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mesh")
    parser.add_argument("--out", default="render.png")
    parser.add_argument("--turntable", type=int, default=0, help="N frames instead of one shot")
    parser.add_argument("--size", type=int, default=900)
    args = parser.parse_args()

    mesh = trimesh.load(args.mesh, force="mesh")
    if args.turntable:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        for i in range(args.turntable):
            frame = render(mesh, 360.0 * i / args.turntable, args.size)
            frame.save(out_dir / f"frame_{i:03d}.png")
            print(f"frame {i + 1}/{args.turntable}")
        print(f"frames in {out_dir} — make an mp4 with:\n"
              f"  ffmpeg -framerate 12 -i {out_dir}/frame_%03d.png -pix_fmt yuv420p turntable.mp4")
    else:
        render(mesh, 35.0, args.size).save(args.out)
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
