"""Generated MJCF: one cabinet, carcass and both drawers in a single body tree.

One entity rather than sixteen box entities. As separate entities the carcass
and two drawers would be sixteen things to create and sixteen per-env `set_pos`
calls every reset; as MJCF it is one and one, and the drawers come with their
slide joints already attached to the carcass.

The cabinet has a freejoint: it stands on the table rather than being bolted to
it, so over-pulling a stopped drawer drags it. See CabinetConfig.

Nothing here sets colour. Genesis ignores per-geom `rgba` from MJCF, and the
two drawers are meant to be indistinguishable anyway -- that is what makes the
prompt load-bearing.
"""
from __future__ import annotations

from pathlib import Path

from .config import ASSETS_DIR, CabinetConfig, SIDES


def _xyz(*v) -> str:
    return " ".join(f"{x:.6f}" for x in v)


def _geom(name: str, size, pos, density: float, friction: float | None = None,
          solref=None, solimp=None) -> str:
    attrs = ""
    if friction is not None:
        attrs += f' friction="{friction:.3f} 0.005 0.0001"'
    if solref is not None:
        attrs += f' solref="{_xyz(*solref)}"'
    if solimp is not None:
        attrs += f' solimp="{_xyz(*solimp)}"'
    return (f'      <geom name="{name}" type="box" size="{_xyz(*size)}" '
            f'pos="{_xyz(*pos)}" density="{density:.1f}"{attrs}/>')


def _carcass_geoms(cab: CabinetConfig) -> list[str]:
    """Base, top, back and three verticals. Origin is the footprint centre on
    the table top, so everything is +z."""
    hd, hw, t = cab.depth / 2, cab.width / 2, cab.panel
    mid_z = t + cab.opening_h / 2         # centre of the open volume
    hh = cab.opening_h / 2

    return [
        # The base carries the ballast: an extended drawer moves mass forward,
        # and without a heavy floor the cabinet tips on a legitimate pull.
        _geom("base", (hd, hw, t / 2), (0, 0, t / 2), cab.base_density, cab.friction),
        _geom("top", (hd, hw, t / 2), (0, 0, cab.height - t / 2), cab.body_density),
        _geom("back", (t / 2, hw, hh), (hd - t / 2, 0, mid_z), cab.body_density),
        _geom("side_py", (hd, t / 2, hh), (0, hw - t / 2, mid_z), cab.body_density),
        _geom("side_ny", (hd, t / 2, hh), (0, -(hw - t / 2), mid_z), cab.body_density),
        _geom("divider", (hd, t / 2, hh), (0, 0, mid_z), cab.body_density),
    ]


def _drawer_body(cab: CabinetConfig, side: str, y: float) -> str:
    """One drawer: slide joint, front panel, tray, and the rail on two brackets.

    Geoms are in the drawer's own frame, whose origin is the closed position at
    the drawer's centre y. The joint travels along -x, so a positive joint
    value is pulled out toward the robot.
    """
    hd, t = cab.depth / 2, cab.panel
    # Centre of the opening, which is also where the rail sits.
    mid_z = t + cab.opening_h / 2
    front_hw = cab.opening_w / 2 - cab.front_clearance
    front_hh = cab.opening_h / 2 - cab.front_clearance

    tray_hw = front_hw - cab.tray_clearance
    tray_hh = front_hh - cab.tray_clearance

    # Brackets sit flush with the rail's ends and span the whole standoff, from
    # the front panel out to the rail's front face.
    bracket_y = cab.rail_span / 2 - cab.bracket_w / 2

    geoms = [
        _geom(f"{side}_front", (t / 2, front_hw, front_hh),
              (-hd + t / 2, 0, mid_z), cab.drawer_density),
        _geom(f"{side}_tray", (cab.tray_depth / 2, tray_hw, tray_hh),
              (-hd + t + cab.tray_depth / 2, 0, mid_z), cab.drawer_density),
        # The only compliant geom in the scene. Contact params are per-geom and
        # MuJoCo mixes them with the other side's, so softening the rail alone
        # gets roughly half the effect -- the fingertip pads keep their own.
        _geom(f"{side}_rail", (cab.rail_thk / 2, cab.rail_span / 2, cab.rail_h / 2),
              (cab.rail_x, 0, cab.rail_z), cab.drawer_density, cab.friction,
              solref=cab.rail_solref, solimp=cab.rail_solimp),
    ] + [
        _geom(f"{side}_bracket_{tag}", (cab.standoff / 2, cab.bracket_w / 2, cab.rail_h / 2),
              (-hd - cab.standoff / 2, sign * bracket_y, cab.rail_z), cab.drawer_density)
        for tag, sign in (("py", 1.0), ("ny", -1.0))
    ]

    joint = (f'      <joint name="slide_{side}" type="slide" axis="-1 0 0" '
             f'range="0 {cab.travel_max:.4f}" damping="{cab.drawer_damping:.3f}" '
             f'frictionloss="{cab.drawer_frictionloss:.3f}"/>')
    return "\n".join([f'    <body name="drawer_{side}" pos="{_xyz(0, y, 0)}">',
                      joint, *geoms, "    </body>"])


def write_cabinet_mjcf(cab: CabinetConfig, assets_dir: Path = ASSETS_DIR) -> Path:
    """The whole cabinet. Drawer bodies are emitted in SIDES order."""
    drawers = [_drawer_body(cab, side, y)
               for side, y in zip(SIDES, cab.drawer_y)]
    body = "\n".join(['    <body name="cabinet" pos="0 0 0">',
                      "      <freejoint/>",
                      *_carcass_geoms(cab),
                      *drawers,
                      "    </body>"])

    path = assets_dir / "cabinet.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""<mujoco model="cabinet">
  <compiler angle="radian"/>
  <worldbody>
{body}
  </worldbody>
</mujoco>
""")
    return path


def cabinet_colors(cab: CabinetConfig) -> list:
    """Per-geom colours in the order `write_cabinet_mjcf` emits them.

    Geom order is only known here, so the colour list is built here too rather
    than being reconstructed in scene.py and silently drifting. Order is
    link-major, matching how Genesis flattens vgeoms: the carcass's six, then
    each drawer's five.
    """
    carcass = [cab.carcass_color] * 6                      # base, top, back, 2 sides, divider
    drawer = [cab.front_color, cab.tray_color, cab.rail_color,
              cab.rail_color, cab.rail_color]              # front, tray, rail, 2 brackets
    return carcass + drawer * len(SIDES)


def write_all(cab: CabinetConfig, assets_dir: Path = ASSETS_DIR) -> dict[str, Path]:
    """Regenerate every asset this config implies. Called by build_scene."""
    return {"cabinet": write_cabinet_mjcf(cab, assets_dir)}
