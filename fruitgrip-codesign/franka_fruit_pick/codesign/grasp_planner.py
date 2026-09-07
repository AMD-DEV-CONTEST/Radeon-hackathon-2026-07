"""Antipodal grasp planner: replaces the fixed per-object-category height/yaw
heuristic (`controller_adapt._OBJECT_GRASP_META`, `sim_episode._grasp_hand_z`'s
single global `GRASP_CENTER_DROP_FRAC`) with a geometry-driven choice, derived
directly from each object's own mesh and the ACTIVE gripper design's aperture.

Scope, stated plainly up front: the existing pick pipeline (`sim_episode.run_pick_place`)
is a constrained top-down descent -- the hand always closes by moving straight down
onto the object's already-known (x, y) centroid, then closing its fingers in the
horizontal plane at whatever height it stopped at. The only real degrees of freedom
that heuristic ever had were (a) that height and (b) a yaw rotation about world z. This
planner chooses both from real geometry instead of a hardcoded per-object-name table --
it does NOT add free 6-DOF grasp poses, an out-of-plane approach direction, or an (x, y)
offset from the object's centroid; extending to those would need changes to the descent
routine itself, not just what feeds it, and is explicitly out of scope here.

Method (the training-free antipodal/force-closure family -- the mature, pre-learned
ancestor of Contact-GraspNet/GPD/AnyGrasp): slice the object's own collision mesh at a
range of heights, and at each height look for the pair (2-finger) or ring (N-finger) of
boundary points whose outward surface normals most directly oppose the direction they'd
be squeezed from, subject to fitting within the gripper's real aperture. Because every
object here is placed at a fixed (roll=pitch=0) resting orientation and only yaw is
randomized at runtime (see `franka_fruit_pick/randomize.py`'s pure-yaw jitter), the
static mesh's own local frame IS the object's world resting frame up to that yaw -- so
analysis done once, offline, on the asset file transfers directly to the live scene.

Reuses the exact asset directory `franka_fruit_pick/scene_config.py` already uses for
the 36-object generalization pool (`assets/ycb/<name>/`, preferring `textured.obj` --
see `_asset_mesh_path` for why -- falling back to `collision.ply`) and the already-a-
dependency `trimesh` for mesh loading/slicing -- no new dependency. Boundary-normal
computation is done with plain numpy 2D polygon geometry (not `mesh.vertex_normals`),
because for this top-down-only system the only normal component that matters is the
in-plane one at the cut, which the mesh's cross-section boundary gives exactly and
more simply than back-mapping to 3D face normals.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh

_ROOT = Path(__file__).resolve().parent
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

from gripper_gen import FINGER_RADIUS, GripperParams  # noqa: E402

ASSETS = _ROOT.parent.parent / "assets"

# Two capsule fingers approaching from opposite sides physically collide with each
# other once their surfaces meet -- below this separation there is no daylight left
# for an object to be gripped between them (this is a hard mechanical floor, not a
# tuned preference).
MIN_GRASP_WIDTH = 2.0 * FINGER_RADIUS

# A design's `aperture` field is its max fingertip-to-fingertip opening (frozen_designs.py
# docstring); leave a small margin so a candidate isn't scored feasible at literal full
# extension, which leaves no closing travel left to actually squeeze.
APERTURE_SAFETY_FRAC = 0.95

MIN_HEIGHT_SLICES = 12
MAX_HEIGHT_SLICES = 60
TARGET_SLICE_THICKNESS = 0.0015  # m; adaptive slice count aims for roughly this spacing

N_YAW_SAMPLES_2FINGER = 24  # every 180/24 = 7.5 deg (pinch is symmetric under 180 deg flip)
N_YAW_SAMPLES_NFINGER = 24  # every 360/24 = 15 deg


def _asset_mesh_path(object_name: str) -> Path:
    # Prefer the VISUAL mesh (textured.obj), not the physics collision mesh
    # (collision.ply), despite collision.ply being what actually gets simulated: YCB's
    # collision meshes here are convex DECOMPOSITIONS (multiple overlapping convex
    # pieces, confirmed via mesh.body_count -- e.g. plum decomposes into 3 pieces),
    # which corrupts a horizontal slice into up to a dozen overlapping/fragmentary
    # boundary loops per height. textured.obj is a single coherent watertight-enough
    # surface and gives one clean loop per slice almost everywhere -- both meshes
    # describe essentially the same physical shape, so analyzing the clean one and
    # applying the result to the (geometrically equivalent) collision shape is valid.
    textured = ASSETS / "ycb" / object_name / "textured.obj"
    if textured.exists():
        return textured
    collision = ASSETS / "ycb" / object_name / "collision.ply"
    if collision.exists():
        return collision
    raise FileNotFoundError(f"No mesh found for {object_name!r} under {ASSETS / 'ycb' / object_name}")


def _load_mesh(object_name: str) -> trimesh.Trimesh:
    return trimesh.load(_asset_mesh_path(object_name), force="mesh")


def _largest_loop(loops: list[np.ndarray]) -> np.ndarray | None:
    """Cross-sections of a convex-decomposed collision mesh can return several loops
    (one per convex piece the slice happens to touch) -- take the dominant one by
    enclosed area, which is the object's actual outer boundary at that height."""
    if not loops:
        return None
    areas = [abs(_shoelace_area(loop[:, :2])) for loop in loops]
    return loops[int(np.argmax(areas))]


def _shoelace_area(pts_xy: np.ndarray) -> float:
    x, y = pts_xy[:, 0], pts_xy[:, 1]
    x2, y2 = np.roll(x, -1), np.roll(y, -1)
    return 0.5 * float(np.sum(x * y2 - x2 * y))


def _polygon_centroid(pts_xy: np.ndarray) -> np.ndarray:
    x, y = pts_xy[:, 0], pts_xy[:, 1]
    x2, y2 = np.roll(x, -1), np.roll(y, -1)
    cross = x * y2 - x2 * y
    a = 0.5 * np.sum(cross)
    if abs(a) < 1e-12:
        return pts_xy.mean(axis=0)
    cx = np.sum((x + x2) * cross) / (6 * a)
    cy = np.sum((y + y2) * cross) / (6 * a)
    return np.array([cx, cy])


def _ray_boundary_hit(pts_xy: np.ndarray, origin: np.ndarray, direction: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """Cast a ray from an interior `origin` in `direction` (unit 2D vector); return the
    first (point, outward_unit_normal) where it crosses the closed polyline `pts_xy`, or
    None if no crossing was found (degenerate/very concave cross-section)."""
    best_t = None
    best_point = None
    best_edge = None
    n = len(pts_xy)
    for i in range(n):
        p1, p2 = pts_xy[i], pts_xy[(i + 1) % n]
        edge = p2 - p1
        denom = direction[0] * edge[1] - direction[1] * edge[0]
        if abs(denom) < 1e-12:
            continue
        diff = p1 - origin
        t = (diff[0] * edge[1] - diff[1] * edge[0]) / denom
        u = (diff[0] * direction[1] - diff[1] * direction[0]) / denom
        if t > 1e-9 and -1e-9 <= u <= 1 + 1e-9:
            if best_t is None or t < best_t:
                best_t = t
                best_point = origin + t * direction
                best_edge = edge
    if best_point is None:
        return None
    edge_len = np.linalg.norm(best_edge)
    if edge_len < 1e-12:
        return None
    tangent = best_edge / edge_len
    normal = np.array([tangent[1], -tangent[0]])  # one of the two perpendiculars
    # Orient outward: away from the polygon's own centroid-ward direction at this point.
    if np.dot(normal, best_point - origin) < 0:
        normal = -normal
    return best_point, normal


@dataclass
class PlannedGrasp:
    object_name: str
    n_fingers: int
    feasible: bool
    center_align: bool
    center_drop_frac: float  # see sim_episode._grasp_hand_z; 0=vertical center, 1=bottom, -1=top
    yaw_offset_deg: float
    antipodal_score: float  # 0..1, 1 = perfect opposition/radial alignment
    grasp_width: float  # m, the chosen candidate's point-pair separation (2-finger) or 2*max_radius (N-finger)
    n_slices_evaluated: int
    notes: str = ""


def _score_2finger(loop: np.ndarray, centroid: np.ndarray, yaw_deg: float) -> dict | None:
    direction = np.array([np.cos(np.radians(yaw_deg)), np.sin(np.radians(yaw_deg))])
    hit_a = _ray_boundary_hit(loop, centroid, direction)
    hit_b = _ray_boundary_hit(loop, centroid, -direction)
    if hit_a is None or hit_b is None:
        return None
    pa, na = hit_a
    pb, nb = hit_b
    width = float(np.linalg.norm(pa - pb))
    antipodal = (1.0 - float(np.dot(na, nb))) / 2.0  # dot=-1 (opposing) -> 1.0; dot=+1 -> 0.0
    return {"width": width, "score": antipodal, "points": [pa, pb], "normals": [na, nb]}


def _score_nfinger(loop: np.ndarray, centroid: np.ndarray, yaw_deg: float, n_fingers: int) -> dict | None:
    radii = []
    radial_scores = []
    points, normals = [], []
    for k in range(n_fingers):
        ang = yaw_deg + k * 360.0 / n_fingers
        direction = np.array([np.cos(np.radians(ang)), np.sin(np.radians(ang))])
        hit = _ray_boundary_hit(loop, centroid, direction)
        if hit is None:
            return None
        p, nrm = hit
        r = p - centroid
        rad = float(np.linalg.norm(r))
        if rad < 1e-9:
            return None
        radii.append(rad)
        points.append(p)
        normals.append(nrm)
        # Radial score: for a stable squeeze, the OUTWARD surface normal at the contact
        # should point straight back along the same line the finger presses in on --
        # i.e. directly away from the centroid (dot with the outward radial unit vector
        # close to +1). A perfect sphere/cylinder cross-section scores 1.0 here (every
        # point's normal is exactly radial); a corner or flat face at an angle scores
        # lower (normal not aligned with any finger's actual approach line).
        radial_scores.append(float(np.dot(nrm, r / rad)))
    width = 2.0 * max(radii)  # conservative: every finger must clear the widest one
    score = float(np.mean(radial_scores))
    score = (score + 1.0) / 2.0  # rescale -1..1 -> 0..1 to match the 2-finger scale
    return {"width": width, "score": score, "points": points, "normals": normals}


def _search(object_name: str, gripper: GripperParams) -> dict:
    """Shared search core for `plan_grasp` (summary-only, used by the real pipeline) and
    `plan_grasp_with_geometry` (keeps the winning candidate's boundary/points/normals too,
    for visualization) -- one algorithm, two views of its result."""
    mesh = _load_mesh(object_name)
    z_min, z_max = float(mesh.bounds[0][2]), float(mesh.bounds[1][2])
    z_extent = z_max - z_min
    out = {"object_name": object_name, "n_fingers": gripper.n_fingers, "z_min": z_min, "z_max": z_max,
           "z_extent": z_extent, "n_evaluated": 0, "chosen": None, "feasible": False,
           "notes": "", "max_width": APERTURE_SAFETY_FRAC * gripper.aperture}
    if z_extent < 1e-6:
        out["notes"] = "degenerate mesh (near-zero height)"
        return out

    # Adaptive slice count: aim for ~TARGET_SLICE_THICKNESS resolution, but keep it
    # bounded so a large object (e.g. a 30cm cracker box) doesn't blow up runtime and a
    # tiny one (e.g. a marker) still gets enough slices to find its narrow waist.
    n_slices = int(np.clip(round(z_extent / TARGET_SLICE_THICKNESS), MIN_HEIGHT_SLICES, MAX_HEIGHT_SLICES))
    # Stay a bit inside the true top/bottom -- a slice exactly at the apex/base of a
    # rounded object returns a degenerate near-zero-area loop, not a useful cross-section.
    margin = 0.04 * z_extent
    candidate_zs = np.linspace(z_min + margin, z_max - margin, n_slices)

    max_width = out["max_width"]
    yaw_samples = np.linspace(0.0, 180.0, N_YAW_SAMPLES_2FINGER, endpoint=False) if gripper.n_fingers == 2 else \
        np.linspace(0.0, 360.0 / gripper.n_fingers, N_YAW_SAMPLES_NFINGER, endpoint=False)

    best_feasible = None
    best_any = None
    n_evaluated = 0

    for z in candidate_zs:
        section = mesh.section(plane_origin=[0, 0, float(z)], plane_normal=[0, 0, 1])
        if section is None:
            continue
        loops = [loop for loop in section.discrete if len(loop) >= 3]
        loop = _largest_loop(loops)
        if loop is None:
            continue
        loop_xy = loop[:, :2]
        centroid = _polygon_centroid(loop_xy)

        for yaw in yaw_samples:
            result = _score_2finger(loop_xy, centroid, float(yaw)) if gripper.n_fingers == 2 \
                else _score_nfinger(loop_xy, centroid, float(yaw), gripper.n_fingers)
            if result is None:
                continue
            width, antipodal_score = result["width"], result["score"]
            n_evaluated += 1
            feasible = MIN_GRASP_WIDTH <= width <= max_width
            # A perfectly round object scores antipodal_score=1.0 at EVERY height, including
            # right near a pole where the cross-section is a tiny, near-zero-width circle --
            # geometrically "perfect" but a thin, unstable pinch far from the object's actual
            # bulk. Confirmed as a real bug via simulation, not just theory: an earlier version
            # of this function (ranking by raw antipodal_score alone) picked a 28.5mm near-pole
            # slice over 018_plum's ~55-60mm equatorial band and dropped the winner design's
            # success rate on that object from 5/5 to 0/5 in a real n=5 trial batch. Weighting
            # alignment quality by how much of the design's available aperture the grasp
            # actually uses breaks ties toward wider, more equatorial, more stable candidates.
            combined = antipodal_score * min(width / max_width, 1.0)
            candidate = {
                "combined": combined, "score": antipodal_score, "z": float(z), "yaw": float(yaw),
                "width": width, "loop_xy": loop_xy, "centroid": centroid,
                "points": result["points"], "normals": result["normals"],
            }
            if best_any is None or combined > best_any["combined"]:
                best_any = candidate
            if feasible and (best_feasible is None or combined > best_feasible["combined"]):
                best_feasible = candidate

    out["n_evaluated"] = n_evaluated
    chosen = best_feasible if best_feasible is not None else best_any
    out["chosen"] = chosen
    out["feasible"] = best_feasible is not None
    if chosen is None:
        out["notes"] = "no valid cross-section found at any sampled height/yaw"
    elif not out["feasible"]:
        out["notes"] = (
            f"best candidate at width={chosen['width'] * 1000:.1f}mm is outside this design's feasible "
            f"range [{MIN_GRASP_WIDTH * 1000:.1f}, {max_width * 1000:.1f}]mm at every sampled "
            f"height/yaw -- geometrically too large (or, rarely, too thin) for this gripper, "
            f"not a targeting problem"
        )
    return out


def _drop_frac(result: dict) -> float:
    z_min, z_max, chosen = result["z_min"], result["z_max"], result["chosen"]
    if chosen is None:
        return 0.0
    center_z = 0.5 * (z_min + z_max)
    half_height = 0.5 * result["z_extent"]
    return float((center_z - chosen["z"]) / half_height) if half_height > 1e-9 else 0.0


def plan_grasp(object_name: str, gripper: GripperParams) -> PlannedGrasp:
    result = _search(object_name, gripper)
    chosen = result["chosen"]
    if chosen is None:
        return PlannedGrasp(object_name, gripper.n_fingers, False, False, 0.0, 0.0, 0.0, result["z_extent"],
                             result["n_evaluated"], notes=result["notes"])
    return PlannedGrasp(
        object_name=object_name,
        n_fingers=gripper.n_fingers,
        feasible=result["feasible"],
        center_align=result["feasible"],  # only claim the AABB-center-based height formula if we found a real candidate there
        center_drop_frac=_drop_frac(result),
        yaw_offset_deg=chosen["yaw"],
        antipodal_score=chosen["score"],
        grasp_width=chosen["width"],
        n_slices_evaluated=result["n_evaluated"],
        notes=result["notes"],
    )


def plan_grasp_with_geometry(object_name: str, gripper: GripperParams) -> dict:
    """Same search as `plan_grasp`, but keeps the winning candidate's cross-section
    boundary, contact points, and normals -- for visualization, not for the sim pipeline
    (which only ever needs `plan_grasp`'s scalar summary)."""
    result = _search(object_name, gripper)
    chosen = result["chosen"]
    out = {
        "object_name": object_name, "n_fingers": gripper.n_fingers,
        "feasible": result["feasible"], "notes": result["notes"],
        "z_min": result["z_min"], "z_max": result["z_max"], "max_width": result["max_width"],
    }
    if chosen is None:
        return out
    out.update({
        "center_drop_frac": _drop_frac(result),
        "yaw_offset_deg": chosen["yaw"],
        "antipodal_score": chosen["score"],
        "grasp_width": chosen["width"],
        "grasp_z": chosen["z"],
        "loop_xy": chosen["loop_xy"].tolist(),
        "centroid_xy": chosen["centroid"].tolist(),
        "contact_points_xy": [p.tolist() for p in chosen["points"]],
        "contact_normals_xy": [n.tolist() for n in chosen["normals"]],
    })
    return out
