"""Parametric MJCF generator for the Franka end-effector's finger geometry.

Design space (see project brief S4): finger count is categorical, finger length /
curvature / aperture / fingertip compliance are continuous, and curvature only means
something conditional on there being >=2 segments. Every point in this space is
*structurally valid by construction*: fingers are built from chains of native MJCF
capsule primitives (`fromto` geoms), not free-form/generated meshes. This matters
for two reasons: (1) Genesis loads primitives directly, without the convex-decomposition
pass we saw fire on the YCB meshes, which is a real throughput cost at population scale;
(2) there is no way to emit an invalid shape, so 100% of sampled candidates are usable.

The arm (7 DOF), its base, and the palm/mount are held fixed. Only the two
per-mount finger bodies (`finger_joint1..N`) are regenerated, by editing a copy of
the original `panda.xml` in place (same body names/joint-naming convention as the
stock file: `left_finger`/`right_finger` for N=2, `finger_0..N-1` for N>2).
"""

from __future__ import annotations

import hashlib
import math
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

# == Structural constants (unchanged from the stock Franka hand -- these are the
#    "mount interface" invariants; they are not searched). ==
FINGER_BASE_Z = 0.0584  # m, hand-link -> finger-body origin offset (stock value)
FINGER_RADIUS = 0.008  # m, capsule radius (finger thickness); not searched for now
N_SEGMENTS = 3  # capsule segments per finger (proximal/mid/distal)
JOINT_MIN_GAP = 0.002  # m, minimum residual half-gap at full close (avoid true zero range)

# == Search bounds (see project brief S4) ==
FINGER_LENGTH_BOUNDS = (0.030, 0.070)  # m
CURVATURE_DEG_BOUNDS = (0.0, 60.0)  # total bend, base segment -> tip segment
APERTURE_BOUNDS = (0.045, 0.100)  # m, max total fingertip-to-fingertip opening
COMPLIANCE_BOUNDS = (0.0, 1.0)  # 0 = rigid, 1 = soft (maps to contact solref timeconst)
FINGER_COUNT_CHOICES = (2, 3)

_SOLREF_TIMECONST_RIGID = 0.005
_SOLREF_TIMECONST_SOFT = 0.05

_HERE = Path(__file__).resolve().parent
_FRANKA_ASSETS_DIR = _HERE.parent.parent / "assets" / "robots" / "franka"
_BASE_XML = _FRANKA_ASSETS_DIR / "panda.xml"
_GENERATED_DIR = _FRANKA_ASSETS_DIR / "generated"


@dataclass(frozen=True)
class GripperParams:
    """One point in the end-effector design space."""

    n_fingers: int = 2
    finger_length: float = 0.045
    curvature_deg: float = 0.0
    aperture: float = 0.080
    compliance: float = 0.0

    def clipped(self) -> "GripperParams":
        return replace(
            self,
            n_fingers=int(self.n_fingers) if int(self.n_fingers) in FINGER_COUNT_CHOICES else 2,
            finger_length=float(np.clip(self.finger_length, *FINGER_LENGTH_BOUNDS)),
            curvature_deg=float(np.clip(self.curvature_deg, *CURVATURE_DEG_BOUNDS)),
            aperture=float(np.clip(self.aperture, *APERTURE_BOUNDS)),
            compliance=float(np.clip(self.compliance, *COMPLIANCE_BOUNDS)),
        )

    def key(self) -> str:
        payload = (
            f"n{self.n_fingers}_l{self.finger_length:.5f}_c{self.curvature_deg:.3f}"
            f"_a{self.aperture:.5f}_p{self.compliance:.4f}"
        )
        digest = hashlib.sha1(payload.encode()).hexdigest()[:10]
        return f"g{digest}"

    def joint_names(self) -> list[str]:
        return [f"finger_joint{i + 1}" for i in range(self.n_fingers)]

    def body_names(self) -> list[str]:
        if self.n_fingers == 2:
            return ["left_finger", "right_finger"]
        return [f"finger_{i}" for i in range(self.n_fingers)]


def finger_local_chain(params: GripperParams) -> np.ndarray:
    """Return the (N_SEGMENTS + 1, 3) polyline of the capsule chain in the finger
    body's own local frame (local +Z = reach/approach direction, local -Y = inward
    toward the grasp centerline -- see module docstring for the frame convention).

    Point 0 is the body origin (finger mount); the last point is the fingertip.
    Segment length is `finger_length / N_SEGMENTS`, so total arc length is invariant
    to curvature (only the *reach* -- how far the tip sits from the mount -- shrinks
    as curvature increases, exactly as a real curling finger would).
    """
    seg_len = params.finger_length / N_SEGMENTS
    pts = [np.zeros(3)]
    for k in range(N_SEGMENTS):
        # direction of segment k: angle phi_k from +Z, bending toward -Y as phi grows.
        phi_k = math.radians(params.curvature_deg * k / max(N_SEGMENTS - 1, 1))
        direction = np.array([0.0, -math.sin(phi_k), math.cos(phi_k)])
        pts.append(pts[-1] + seg_len * direction)
    return np.array(pts)


def fingertip_local_offset(params: GripperParams) -> np.ndarray:
    """Fingertip position in the finger body's local frame (see `finger_local_chain`)."""
    return finger_local_chain(params)[-1]


def hand_to_fingertip_z(params: GripperParams) -> float:
    """Absolute hand-link -> fingertip-midline Z distance for this design.

    Generalizes the stock demo's `HAND_TO_FINGERTIP = 0.105` constant (grasp_demo.py),
    which was tuned for the fixed original finger. This is the controller/geometry
    co-adaptation hook used by `controller_adapt.py`: the scripted grasp height must
    move with finger length/curvature, or every non-default gripper would silently
    grasp at the wrong height while still being scored against a fixed reward.
    """
    return float(FINGER_BASE_Z + fingertip_local_offset(params)[2])


def _quat_about_z(deg: float) -> str:
    theta = math.radians(deg)
    return f"{math.cos(theta / 2):.8f} 0 0 {math.sin(theta / 2):.8f}"


def _solref_for_compliance(compliance: float) -> str:
    timeconst = _SOLREF_TIMECONST_RIGID + compliance * (_SOLREF_TIMECONST_SOFT - _SOLREF_TIMECONST_RIGID)
    return f"{timeconst:.5f} 1"


def _find(root: ET.Element, path: str) -> ET.Element:
    el = root.find(path)
    if el is None:
        raise ValueError(f"expected element not found in base MJCF: {path!r}")
    return el


def _build_finger_body(name: str, joint_name: str, azimuth_deg: float, params: GripperParams) -> ET.Element:
    body = ET.Element("body", {"name": name, "pos": "0 0 " + f"{FINGER_BASE_Z:.6f}", "quat": _quat_about_z(azimuth_deg)})
    finger_mass = 0.015 * (params.finger_length / 0.0454)
    ET.SubElement(
        body, "inertial",
        {"mass": f"{finger_mass:.6f}", "pos": "0 0 0", "diaginertia": "2.375e-6 2.375e-6 7.5e-7"},
    )
    max_travel = max(params.aperture / 2.0 - JOINT_MIN_GAP, JOINT_MIN_GAP)
    ET.SubElement(
        body, "joint",
        {"name": joint_name, "class": "finger", "axis": "0 1 0", "type": "slide", "range": f"0 {max_travel:.6f}"},
    )
    chain = finger_local_chain(params)
    solref = _solref_for_compliance(params.compliance)
    for i in range(N_SEGMENTS):
        p0, p1 = chain[i], chain[i + 1]
        fromto = f"{p0[0]:.6f} {p0[1]:.6f} {p0[2]:.6f} {p1[0]:.6f} {p1[1]:.6f} {p1[2]:.6f}"
        is_distal = i == N_SEGMENTS - 1
        # Visual copy (matches the collision shape -- no separate mesh to keep in sync).
        ET.SubElement(body, "geom", {
            "type": "capsule", "fromto": fromto, "size": f"{FINGER_RADIUS:.5f}",
            "contype": "0", "conaffinity": "0", "group": "2",
            "rgba": "0.901961 0.921569 0.929412 1",
        })
        collision_attrs = {
            "type": "capsule", "fromto": fromto, "size": f"{FINGER_RADIUS:.5f}", "group": "3",
        }
        if is_distal:
            # Only the distal (contact-bearing) segment carries the compliance term --
            # matches the stock file's pattern of a separate softer "fingertip pad".
            collision_attrs["solref"] = solref
        ET.SubElement(body, "geom", collision_attrs)
    return body


def _rebuild_tendon_equality_actuator(root: ET.Element, params: GripperParams) -> None:
    joint_names = params.joint_names()

    tendon = _find(root, "tendon")
    for fixed in list(tendon):
        tendon.remove(fixed)
    fixed = ET.SubElement(tendon, "fixed", {"name": "split"})
    coef = f"{1.0 / params.n_fingers:.6f}"
    for jn in joint_names:
        ET.SubElement(fixed, "joint", {"joint": jn, "coef": coef})

    equality = _find(root, "equality")
    for eq in list(equality):
        equality.remove(eq)
    for jn in joint_names[1:]:
        ET.SubElement(equality, "joint", {
            "joint1": joint_names[0], "joint2": jn, "solimp": "0.95 0.99 0.001", "solref": "0.005 1",
        })

    # Actuator stays a single tendon-driven actuator (Genesis approximates this as a
    # synchronized per-joint force/position actuator -- see sim_episode.py, which
    # commands every finger joint in FINGERS_DOF directly rather than relying on the
    # tendon mechanism itself). Must target the specific <general> that already drives
    # the "split" tendon (actuator8) -- the arm actuators (actuator1..7) are each
    # already bound to their own `joint=...` and MuJoCo rejects an actuator with both
    # a joint and a tendon transmission target.
    actuator = _find(root, "actuator")
    tendon_actuator = None
    for general in actuator.findall("general"):
        if general.get("tendon") == "split":
            tendon_actuator = general
            break
    if tendon_actuator is None:
        raise ValueError("could not find the tendon-driven finger actuator ('split') in the base MJCF")


def generate_gripper_xml(params: GripperParams, out_dir: Path | None = None) -> Path:
    """Write a Franka MJCF variant with the given finger geometry and return its path.

    Idempotent/cached by `params.key()`: re-generating the same params returns the
    same file without recomputation.
    """
    params = params.clipped()
    out_dir = out_dir or _GENERATED_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"panda_{params.key()}.xml"
    if out_path.exists():
        return out_path

    tree = ET.parse(_BASE_XML)
    root = tree.getroot()

    # Resolve mesh assets by a *relative* path (generated/ and assets/ are fixed
    # siblings under _FRANKA_ASSETS_DIR) so the generated file is portable across
    # machines. An earlier version used an absolute path here on the theory that it
    # would "let the generated file live anywhere" -- backwards: an absolute path is
    # only valid on the machine it was computed on. That broke exactly the scenario
    # this project needs (transferring a generated XML, or its parent repo, to a
    # different machine/path -- e.g. session 4's ROCm benchmark instance) with a
    # MuJoCo "Error opening file" pointing at the *origin* machine's path.
    compiler = _find(root, "compiler")
    compiler.set("meshdir", "../assets")

    hand_body = None
    for body in root.iter("body"):
        if body.get("name") == "hand":
            hand_body = body
            break
    if hand_body is None:
        raise ValueError("could not find the 'hand' body in the base Franka MJCF")

    for child in list(hand_body):
        if child.tag == "body" and child.get("name") in ("left_finger", "right_finger"):
            hand_body.remove(child)

    azimuths = [i * (360.0 / params.n_fingers) for i in range(params.n_fingers)]
    for name, joint_name, az in zip(params.body_names(), params.joint_names(), azimuths):
        hand_body.append(_build_finger_body(name, joint_name, az, params))

    _rebuild_tendon_equality_actuator(root, params)

    # Write-then-rename: `out_path.exists()` above is the whole cache, so a process
    # killed mid-write (this project got hit by real host reboots during background
    # runs) would otherwise leave a truncated/empty file that every later run for the
    # same params keeps re-reading and failing to parse. os.replace is atomic on the
    # same filesystem, so out_path only ever exists once fully written.
    tmp_path = out_path.with_suffix(f".tmp{os.getpid()}.xml")
    tree.write(tmp_path, encoding="utf-8", xml_declaration=False)
    os.replace(tmp_path, out_path)
    return out_path


def clear_cache() -> None:
    """Remove all generated variant files (e.g. between unrelated experiment runs)."""
    if _GENERATED_DIR.exists():
        for f in _GENERATED_DIR.glob("panda_g*.xml"):
            f.unlink()
