"""
Robot workspace placement — local-frame positioning.

Design
------
Layer 1 (scene-independent): cube & cameras defined as offsets from robot base.
Layer 2 (scene-specific): robot base position, yaw, workspace surface height.

Coordinate frame: robot-local +X = forward, +Y = left, +Z = up.
XY offsets are rotated by yaw; Z offsets are relative to *surface_z*.
"""
from __future__ import annotations

import argparse
import math

# ---------------------------------------------------------------------------
# Workspace constants (tuned from 10_franka/scripts/01_franka_pick_data.py)
# ---------------------------------------------------------------------------
CUBE_RANGE_X = (0.40, 0.70)    # feasible forward reach for top-down grasp
CUBE_RANGE_Y = (-0.20, 0.20)   # feasible lateral reach
CUBE_DEFAULT_XY = (0.55, 0.0)  # center of feasible range

CAM_UP = dict(
    pos=(0.55, 0.55, 0.55),
    lookat=(0.55, 0.0, 0.10),
    fov=45, res=(640, 480),
)
CAM_SIDE = dict(
    pos=(0.55, -0.55, 0.27),
    lookat=(0.55, 0.0, 0.12),
    fov=50, res=(640, 480),
)

HAND_OFFSET = 0.115
HOVER_DZ = 0.12
LIFT_DZ = 0.15


# ---------------------------------------------------------------------------
# Coordinate transform
# ---------------------------------------------------------------------------
def to_world(base_xy, yaw_rad, surface_z, local):
    """Robot-local ``(dx, dy, dz_above_surface)`` → world ``(x, y, z)``.

    cube_dx/dy are robot-local (dx = forward, dy = left).  They are
    rotated by *yaw_rad* before adding to base_xy, so the same
    cube_dx works for any yaw — only base_x/y needs to change.

    See :func:`target_to_base` for the inverse (choose base from target).
    """
    c, s = math.cos(yaw_rad), math.sin(yaw_rad)
    dx, dy, dz = local
    return (
        base_xy[0] + dx * c - dy * s,
        base_xy[1] + dx * s + dy * c,
        surface_z + dz,
    )


def target_to_base(target_xy, yaw_deg, cube_dx=None, cube_dy=None):
    """Compute base_x/y so that the cube lands at *target_xy* in world.

    This is the inverse of :func:`to_world` for the XY plane::

        yaw=0°   → base = (target_x − dx, target_y − dy)
        yaw=180° → base = (target_x + dx, target_y + dy)
        yaw=90°  → base = (target_x + dy, target_y − dx)
    """
    dx = cube_dx if cube_dx is not None else CUBE_DEFAULT_XY[0]
    dy = cube_dy if cube_dy is not None else CUBE_DEFAULT_XY[1]
    r = math.radians(yaw_deg)
    c, s = math.cos(r), math.sin(r)
    return (
        target_xy[0] - dx * c + dy * s,
        target_xy[1] - dx * s - dy * c,
    )


def compute_workspace(base_xy, yaw_rad, surface_z, cube_half_z=0.02,
                      cube_local_xy=None):
    """Return world positions for cube and data-collection cameras.

    *cube_local_xy* overrides the cube XY offset from robot base.
    Cameras always point at workspace center regardless of cube position.
    """
    cxy = cube_local_xy if cube_local_xy is not None else CUBE_DEFAULT_XY
    cube = to_world(base_xy, yaw_rad, surface_z, (*cxy, cube_half_z))

    def _cam(spec):
        return dict(
            pos=to_world(base_xy, yaw_rad, surface_z, spec["pos"]),
            lookat=to_world(base_xy, yaw_rad, surface_z, spec["lookat"]),
            fov=spec["fov"], res=spec["res"],
        )

    return dict(cube=cube, cam_up=_cam(CAM_UP), cam_side=_cam(CAM_SIDE))


# ---------------------------------------------------------------------------
# CLI helper
# ---------------------------------------------------------------------------
def add_placement_args(ap: argparse.ArgumentParser, *, defaults=None):
    """Register robot-placement CLI args with optional per-scene defaults."""
    d = defaults or {}
    ap.add_argument("--base-x", type=float, default=d.get("base_x", 0.0))
    ap.add_argument("--base-y", type=float, default=d.get("base_y", 0.0))
    ap.add_argument("--base-lift", type=float, default=d.get("base_lift", 0.0),
                    help="Additional base Z offset above floor_z (e.g. pedestal)")
    ap.add_argument("--yaw", type=float, default=d.get("yaw", 0.0),
                    help="Robot facing direction in degrees (0 = +X)")
    ap.add_argument("--surface-z", type=float,
                    default=d.get("surface_z", 0.0),
                    help="Workspace surface Z (countertop / ground)")
    ap.add_argument("--cube-dx", type=float, default=CUBE_DEFAULT_XY[0],
                    help=f"Cube forward offset in robot-local frame "
                         f"[{CUBE_RANGE_X[0]:.2f}, {CUBE_RANGE_X[1]:.2f}]. "
                         f"Rotated by yaw → world coords. No need to change per yaw.")
    ap.add_argument("--cube-dy", type=float, default=CUBE_DEFAULT_XY[1],
                    help=f"Cube lateral offset in robot-local frame "
                         f"[{CUBE_RANGE_Y[0]:.2f}, {CUBE_RANGE_Y[1]:.2f}]. "
                         f"Rotated by yaw → world coords.")
    ap.add_argument("--res-w", type=int, default=1280)
    ap.add_argument("--res-h", type=int, default=720)
    ap.add_argument("--cpu", action="store_true")
