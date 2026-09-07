"""Session 7: cross-simulator replication -- MuJoCo scene assembly.

Injects the table + YCB pick objects (banana/lemon/plum) + bowl into a frozen
design's already-generated gripper MJCF (gripper_gen.py's output, confirmed to be
plain standard MJCF with zero Genesis-specific extensions -- see cross_simulator_
findings.md's setup notes). Reuses the SAME .obj/.ply mesh files Genesis uses for
these objects (assets/ycb/<name>/), not new/approximated geometry.

Mass: MuJoCo's geom `density` attribute auto-derives mass+inertia from mesh volume,
exactly mirroring Genesis's `gs.materials.Rigid(rho=300.0)` -- same density constant,
same mesh, so masses match by construction rather than being separately tuned.

Friction: deliberately NOT copied from Genesis's per-object overrides. Per the
project brief's explicit instruction not to tune MuJoCo to match Genesis, this uses
a single uniform friction (1.0 sliding -- MuJoCo's own default is close to this;
Genesis's lemon/plum explicit override was also 1.0, banana had no override in
either engine) applied via the <default> class, not selected to reproduce Genesis's
number.

Collision geometry: bowl uses the coacd-decomposed convex pieces (prepare_assets.py)
since its concavity is functionally load-bearing for success detection. Banana/lemon/
plum use their existing collision.ply directly as a single mesh geom (MuJoCo auto-
hulls a single mesh geom to its convex hull) -- these objects are close enough to
convex already that decomposition would not change the physics in any way that
matters here (see prepare_assets.py's docstring).
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT.parent.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent.parent))

from prepare_assets import decompose, single_hull_obj  # noqa: E402

_ASSETS_YCB = _ROOT.parent.parent.parent / "assets" / "ycb"

TABLE_TOP_Z = 0.75
TABLE_CENTER = (0.35, 0.0)
TABLE_TOP_SIZE = (1.20, 0.80, 0.05)
FRANKA_POS = (-0.10, 0.0, TABLE_TOP_Z)  # FRANKA_EULER=(0,0,0) in Genesis -- no rotation needed

# Same nominal table-relative xy positions as scene_config.YCB_LAYOUT's active pool
# (session 1); z is filled in per object below.
OBJECT_LAYOUT = {
    "011_banana": {"pos": (0.31, 0.22), "yaw": 35.0},
    "014_lemon": {"pos": (0.34, -0.08), "yaw": 0.0},
    "018_plum": {"pos": (0.44, 0.08), "yaw": 0.0},
}
BOWL_POS = (0.50, -0.10)

RHO = 300.0  # kg/m^3 -- matches Genesis's gs.materials.Rigid(rho=300.0) exactly

# Contact bitmask scheme (see build_scene_xml's docstring comment for the full
# rationale) -- hoisted to module level so other scripts (e.g. domain_rand
# consumers) can identify Franka-vs-scene geoms without re-deriving the scheme.
FRANKA_CONTYPE, FRANKA_CONAFFINITY = "1", "2"
SCENE_CONTYPE, SCENE_CONAFFINITY = "2", "3"


def _euler_to_quat_z(deg: float) -> str:
    import math
    theta = math.radians(deg) / 2
    return f"{math.cos(theta)} 0 0 {math.sin(theta)}"


def build_scene_xml(gripper_xml_path: Path, out_name: str) -> Path:
    tree = ET.parse(gripper_xml_path)
    root = tree.getroot()

    compiler = root.find("compiler")
    # meshdir is relative to the gripper XML's own directory (../assets, per session
    # 4's portability fix) -- add an absolute-path <mesh> per YCB asset below instead
    # of relying on a shared meshdir, since the YCB assets live in a different tree.

    # Genesis mounts the Franka via scene.add_entity(gs.morphs.MJCF(..., pos=FRANKA_POS,
    # euler=FRANKA_EULER)) -- an entity-level transform applied OUTSIDE the MJCF file,
    # not baked into it (the raw MJCF's link0 has no pos, i.e. defaults to world
    # origin). Reusing the MJCF as-is without applying this offset silently leaves the
    # whole robot floating at the world origin instead of mounted on the table --
    # confirmed by inspecting link0's world pos ([0,0,0]) and finding link3/link4
    # already penetrating the table by up to 7.3cm at the qpos=0 rest pose, before any
    # motion at all. Apply it here to the worldbody's root Franka body (link0).
    link0 = root.find("worldbody").find("body[@name='link0']")
    link0.set("pos", f"{FRANKA_POS[0]} {FRANKA_POS[1]} {FRANKA_POS[2]}")

    # Contact groups (bitmask scheme, see below): FRANKA=1, SCENE=2 (table/objects/
    # bowl). A pair collides iff (contype_a & conaffinity_b) or (contype_b & conaffinity_a)
    # is nonzero.
    #   Franka geoms:  contype=1, conaffinity=2  -> only ever checks against SCENE
    #   Scene geoms:   contype=2, conaffinity=3  -> checks against FRANKA (bit1) AND
    #                                                other SCENE geoms (bit2, so table/
    #                                                objects/bowl still collide with
    #                                                EACH OTHER -- objects must rest on
    #                                                the table and land in the bowl)
    # (franka, franka): (1&2)=0, (1&2)=0 -> no collision (self-collision disabled)
    # (franka, scene):  (1&3)=1 -> collision enabled
    # (scene, scene):   (2&3)=2 -> collision enabled
    # (module-level FRANKA_CONTYPE/FRANKA_CONAFFINITY/SCENE_CONTYPE/SCENE_CONAFFINITY, above)

    default = root.find("default")
    contact_default = ET.SubElement(default, "default", {"class": "ycb"})
    ET.SubElement(contact_default, "geom", {
        "friction": "1.0 0.005 0.0001", "density": str(RHO),
        "contype": SCENE_CONTYPE, "conaffinity": SCENE_CONAFFINITY,
    })

    # Franka self-collision filtering. Genesis auto-detects and excludes geometry
    # pairs that inherently overlap at the neutral pose (confirmed in prior sessions'
    # logs: "Filtered out geometry pairs causing self-collision for the neutral
    # configuration"); stock MuJoCo does not do this automatically. Without it, this
    # scene has 25 already-penetrating contacts at rest (qpos=0) -- some 7cm deep --
    # whose constraint-resolution forces are large enough to overpower a finger
    # actuator's PD force outright (confirmed empirically: fingers commanded open
    # instead crept to a small negative/over-closed qpos and stuck there). Rather
    # than hand-curate Genesis's specific excluded pairs, disable collision within
    # the whole Franka body via contype/conaffinity bitmasks (arm/hand/fingers keep
    # colliding with everything ELSE in the scene -- table, objects, bowl -- just not
    # with each other). The task is scripted and never depends on Franka self-contact.
    collision_default = None
    for d in default.iter("default"):
        if d.get("class") == "collision":
            collision_default = d
            break
    if collision_default is not None:
        geom_el = collision_default.find("geom")
        geom_el.set("contype", FRANKA_CONTYPE)
        geom_el.set("conaffinity", FRANKA_CONAFFINITY)
    # gripper_gen.py's finger capsules set group="3" directly, without class="collision"
    # (so they don't inherit the override above) -- tag them the same way explicitly.
    for g in root.iter("geom"):
        if g.get("group") == "3" and g.get("class") != "collision":
            g.set("contype", FRANKA_CONTYPE)
            g.set("conaffinity", FRANKA_CONAFFINITY)

    asset = root.find("asset")
    worldbody = root.find("worldbody")

    # Table (schematic box, matches build_scene.py's tabletop -- legs omitted, not
    # load-bearing for this task, and MuJoCo table geoms are static regardless).
    table_body = ET.SubElement(worldbody, "body", {"name": "table", "pos": f"{TABLE_CENTER[0]} {TABLE_CENTER[1]} {TABLE_TOP_Z - TABLE_TOP_SIZE[2]/2}"})
    ET.SubElement(table_body, "geom", {
        "type": "box", "size": f"{TABLE_TOP_SIZE[0]/2} {TABLE_TOP_SIZE[1]/2} {TABLE_TOP_SIZE[2]/2}",
        "rgba": "0.62 0.47 0.35 1", "contype": SCENE_CONTYPE, "conaffinity": SCENE_CONAFFINITY,
    })

    # Pick objects: free-floating bodies, single mesh geom (auto-hulled by MuJoCo),
    # density-derived mass.
    for name, layout in OBJECT_LAYOUT.items():
        mesh_name = f"{name}_collision"
        ET.SubElement(asset, "mesh", {"name": mesh_name, "file": str(single_hull_obj(name).resolve())})
        x, y = layout["pos"]
        body = ET.SubElement(worldbody, "body", {"name": name, "pos": f"{x} {y} {TABLE_TOP_Z + 0.05}", "quat": _euler_to_quat_z(layout["yaw"])})
        ET.SubElement(body, "freejoint", {"name": f"{name}_free"})
        ET.SubElement(body, "geom", {"class": "ycb", "type": "mesh", "mesh": mesh_name, "rgba": "0.8 0.75 0.3 1"})

    # Bowl: fixed body, coacd-decomposed convex pieces so the interior cavity is real.
    bowl_paths = decompose("024_bowl")
    bowl_body = ET.SubElement(worldbody, "body", {"name": "024_bowl", "pos": f"{BOWL_POS[0]} {BOWL_POS[1]} {TABLE_TOP_Z}"})
    for i, p in enumerate(bowl_paths):
        mesh_name = f"bowl_hull_{i}"
        ET.SubElement(asset, "mesh", {"name": mesh_name, "file": str(p.resolve())})
        ET.SubElement(bowl_body, "geom", {"type": "mesh", "mesh": mesh_name, "rgba": "0.5 0.1 0.1 1", "friction": "1.0 0.005 0.0001", "contype": SCENE_CONTYPE, "conaffinity": SCENE_CONAFFINITY})

    # Per-finger position actuators: Genesis's scripted controller (sim_episode.py)
    # commands each finger JOINT directly (control_dofs_position/force on
    # rt.fingers_dof), bypassing the stock MJCF's combined tendon actuator entirely
    # (gripper_gen.py's own comment notes Genesis "approximates" the tendon as
    # per-joint control for exactly this reason). MuJoCo has no equivalent
    # convenience -- add one explicit position actuator per finger joint so the
    # ported controller can mirror Genesis's direct per-joint control instead of
    # going through the tendon/tendon-actuator path.
    actuator = root.find("actuator")
    # Remove the stock tendon-driven actuator ("split", actuator8): its ctrl defaults
    # to 0, which the affine bias law resolves to a CLOSED target -- left in place
    # alongside the new per-finger actuators below, it actively fights them (confirmed:
    # fingers stayed pinned near fully-closed despite commanding them open). Genesis's
    # controller never used this actuator either (see the comment above), so removing
    # it just means both replications drive the fingers the same way.
    for general in list(actuator.findall("general")):
        if general.get("tendon") == "split":
            actuator.remove(general)

    finger_joints = [j for j in root.iter("joint") if j.get("class") == "finger"]
    for j in finger_joints:
        # Explicit ctrlrange is required: the base MJCF sets <compiler autolimits="true">,
        # which -- for an actuator with no ctrlrange given -- compiles to ctrllimited=true
        # with range [0,0], silently clamping every ctrl write to 0 regardless of what's
        # assigned (confirmed: fingers stayed pinned at ~0 even after removing the
        # tendon-actuator conflict above, until this was added).
        jrange = j.get("range", "0 0.04")
        ET.SubElement(actuator, "position", {"name": f"{j.get('name')}_pos", "joint": j.get("name"), "kp": "200", "kv": "10", "ctrlrange": jrange})

    # Written next to the source gripper XML so its relative compiler meshdir
    # (session 4's portability fix: "../assets", resolved relative to the MJCF file's
    # own location) still resolves correctly for the Franka meshes.
    out_path = gripper_xml_path.parent / f"{out_name}.xml"
    tree.write(out_path)
    return out_path


if __name__ == "__main__":
    import mujoco

    p = build_scene_xml(Path("assets/robots/franka/generated/panda_g2cfc5f524b.xml"), "test_scene")
    print("wrote", p)
    m = mujoco.MjModel.from_xml_path(str(p))
    print("LOADED OK. nbody:", m.nbody, "nq:", m.nq)
