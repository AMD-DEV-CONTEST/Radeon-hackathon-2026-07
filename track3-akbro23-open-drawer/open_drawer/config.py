"""Every tunable of the drawer scene, in one place.

Frozen dataclasses, so a run is described by a single `EnvConfig` value.
`n_envs` is a field rather than a module constant, so N=1 and N=256 go through
one code path.

Geometry conventions
--------------------
* The cabinet body origin sits at the CENTRE of its footprint, on the table
  top, so every cabinet geom offset is +z.
* A drawer's origin is its closed position. Its slide joint travels along the
  cabinet's -x, so a positive joint value means pulled out toward the robot.
* "left" is +y, which is also image-left for a camera looking along +x.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

# Fixed rather than timestamped so collect, train and eval chain without anyone
# pasting a generated path between them. Every stage still takes an override.
#   assets/  generated MJCF, rebuilt every scene build
#   data/    the recorded dataset -- expensive, kept apart from disposable runs
#   out/     everything a run produces from it: checkpoints, renders, videos
DATASET_REPO_ID = "local/open_drawer"
DATASET_ROOT = "data/open_drawer"
TRAIN_DIR = "out/train/open_drawer"
CHECKPOINT = f"{TRAIN_DIR}/checkpoints/last/pretrained_model"

SIDES = ("left", "right")


@dataclass(frozen=True)
class TableConfig:
    top_z: float = 0.75
    center: tuple[float, float] = (0.35, 0.0)
    size: tuple[float, float, float] = (1.20, 0.80, 0.05)
    color: tuple[float, float, float, float] = (0.62, 0.47, 0.35, 1.0)


@dataclass(frozen=True)
class FrankaConfig:
    mjcf: str = "xml/franka_emika_panda/panda.xml"
    pos: tuple[float, float, float] = (-0.10, 0.0, 0.75)
    hand_link: str = "hand"

    # From panda.xml: fingertip_pad_collision_1 is a box of half-height 0.0085
    # at z=0.0445 in the finger frame, and the finger link origin is 0.0584
    # below the hand. 0.0584 + 0.0445 = 0.1029 to the pad centre, and
    # 0.0584 + 0.0539 = 0.1123 to the fingertip.
    hand_to_pad: float = 0.1029
    hand_to_fingertip: float = 0.1123
    # Half-thickness of the pad in the closing direction, and the offset from
    # the finger frame to its inner gripping face. The pad box spans local y in
    # [0.0015, 0.0095], so the face the rail touches is at 0.0015 and the finger
    # body extends OUTWARD from there. Jaw separation is 2*(q + pad_face).
    pad_face: float = 0.0015
    pad_half_thk: float = 0.004
    pad_half_len: float = 0.0085

    # Solved, not chosen: IK to a hand pose of (0.30, 0, 1.08) at the grasp
    # orientation, then rendered to confirm the wrist camera frames BOTH rails.
    # That framing is the whole constraint -- there is no fixed camera, so if
    # the two drawers are not both in view at home, nothing grounds the prompt.
    # The last two entries must equal TeacherConfig.q_open; EnvConfig checks it.
    home_qpos: tuple[float, ...] = (
        0.4902, -0.3266, -0.5087, -2.6763, -0.2274, 2.3660, -0.6160, 0.014, 0.014)

    # Arm gains are the reference's. Finger kp is NOT: gripping by position
    # makes grip force kp times the commanded overshoot, and at kp=100 a 4.5 mm
    # overshoot onto the rail is 0.45 N, which will not hold under a pull.
    # 1500 puts the same overshoot at ~6.8 N. This is the number to revisit if
    # the gripper chatters on contact.
    kp: tuple[float, ...] = (4500, 4500, 3500, 3500, 2000, 2000, 2000, 400, 400)
    kv: tuple[float, ...] = (450, 450, 350, 350, 200, 200, 200, 20, 20)
    force_min: tuple[float, ...] = (-87, -87, -87, -87, -12, -12, -12, -100, -100)
    force_max: tuple[float, ...] = (87, 87, 87, 87, 12, 12, 12, 100, 100)

    # Tool axis down, jaws separating along world x so they straddle the rail
    # front-to-back. 180 deg about x points +z at the table; the further 90 deg
    # about z carries the hand's y (the finger travel axis) onto world x.
    # Verified by rendering in inspect_scene, not by trusting the convention.
    grasp_euler_deg: tuple[float, float, float] = (180.0, 0.0, 90.0)

    @property
    def home(self) -> np.ndarray:
        return np.asarray(self.home_qpos, dtype=np.float64)

    def jaw_separation(self, q: float) -> float:
        """Distance between the two inner gripping faces at finger position q."""
        return 2.0 * (q + self.pad_face)


@dataclass(frozen=True)
class CabinetConfig:
    """A two-drawer cabinet standing free on the table.

    NOT fixed. Over-pulling a drawer that has hit its stop transfers the load
    into the cabinet, which then slides toward the robot and can tip -- that is
    what makes releasing on the felt stop necessary rather than optional. A
    policy that just pulls for the maximum duration drags the furniture.

    The base slab carries most of the mass to keep an open drawer from tipping
    it forward on its own. `base_density` against `body_density` is the
    anti-tip budget, and the margin between "a normal pull does not creep the
    cabinet" and "a jammed pull drags it" is measured, not assumed.
    """
    front_x: float = 0.44        # world x of the closed drawer front face
    depth: float = 0.22          # x
    width: float = 0.30          # y
    height: float = 0.16         # z
    panel: float = 0.008         # panel thickness

    # Applied per visual geom in scene.py: Genesis ignores colour written into
    # MJCF, and `surface=` paints a whole entity one colour. Unpainted, the
    # cabinet renders as one grey block with no readable drawer front or rail
    # -- and the wrist camera is the only view the policy gets, so it needs
    # something to servo on. Both drawers are painted IDENTICALLY; the contrast
    # is carcass against front against rail, never left against right.
    carcass_color: tuple[float, float, float, float] = (0.52, 0.47, 0.43, 1.0)
    front_color: tuple[float, float, float, float] = (0.82, 0.80, 0.76, 1.0)
    tray_color: tuple[float, float, float, float] = (0.28, 0.28, 0.30, 1.0)
    rail_color: tuple[float, float, float, float] = (0.15, 0.15, 0.18, 1.0)

    body_density: float = 400.0
    # Ballast, and it sets how hard the cabinet is to drag: mu * m * g. That
    # threshold is the CEILING on the whole task -- once the cabinet slides the
    # pull cannot build past it, so it is both the largest force the arm ever
    # applies and the most the taxels can ever see. It has to sit well above
    # `drawer_frictionloss`, or the cabinet creeps during a legitimate pull
    # instead of only under a genuine over-pull. Measured here: ~7 N to slide
    # the drawer, ~30 N once it is against its stop.
    base_density: float = 4500.0
    drawer_density: float = 250.0
    # Sets the force needed to drag the cabinet, which must sit UNDER what the
    # arm can actually pull: the Panda's wrist joints cap at 12 Nm, so past
    # roughly 25 N at the hand the arm saturates and the over-pull consequence
    # never fires. ~3 kg at 0.6 puts the drag threshold near 17 N. Measured in
    # the friction probe, not trusted from this arithmetic.
    friction: float = 0.6

    # Bar pull standing off the drawer front. `gap` is the slot the rear finger
    # drops into; it must clear the finger, whose body extends outward from the
    # gripping face by at least the pad's own 8 mm -- see the check in
    # EnvConfig.__post_init__. That bound is the PAD, and the finger body behind
    # it is thicker, so this carries margin rather than sitting on the limit.
    gap: float = 0.028
    rail_thk: float = 0.012      # x
    rail_span: float = 0.090     # y
    rail_h: float = 0.012        # z
    # High on the drawer front, not centred on it. The gripper descends
    # vertically onto the rail, so the hand ends up hand_to_pad ABOVE it: at
    # mid-height that is z=0.933 against a cabinet top of 0.91, and the hand
    # body has 23 mm to thread. Up here it clears by ~73 mm. Real drawer pulls
    # sit high on the front for the same reason.
    rail_z: float = 0.135        # above the cabinet base
    bracket_w: float = 0.010

    # The rail is the one COMPLIANT part in the scene, and that compliance is
    # what makes the taxels work at all. KinematicTaxel reads probe
    # PENETRATION, so against a rigid rail the pads sink by micrometres and the
    # reading is flat: measured 0.19 N through a whole pull and 0.22 N while
    # jammed, a 15% change on a 13 N load step. A softer contact lets the pads
    # sink measurably further under load, which is also how a real tactile pad
    # works -- an elastomer deforming, not a rigid probe.
    #
    # Larger timeconst is softer (the reference stiffened, to 0.006, for the
    # opposite reason). Genesis clamps it to > 2 * substep_dt = 5 ms, well
    # below this. `solimp` widens the zone over which the contact ramps to full
    # stiffness, which is what actually buys penetration depth.
    rail_solref: tuple[float, float] = (0.06, 1.0)
    rail_solimp: tuple[float, float, float] = (0.70, 0.90, 0.010)

    # The tray is what makes an open drawer read as a drawer rather than as a
    # floating panel. Clearance to the opening on every side: the slide joint
    # already constrains the drawer to one axis, so the walls do not guide it,
    # and a tray sized to the opening would grind on them every step.
    tray_depth: float = 0.160
    tray_clearance: float = 0.010
    front_clearance: float = 0.003   # per side, front panel to opening edge

    # Friction loss is a constant opposing force in newtons, so it IS the force
    # needed to slide the drawer -- the lower of the two levels the taxels have
    # to tell apart. Raising it to 12 N did move the fingertip force to the
    # 20/40 N band, but it lifted the taxel's free-pull reading into its jammed
    # band and destroyed the separation, so the gentler drawer stays.
    drawer_damping: float = 2.0
    drawer_frictionloss: float = 0.5

    # Model-level envelope. The per-episode stop is written per env with
    # set_dofs_limit, which needs RigidOptions(batch_dofs_info=True).
    travel_max: float = 0.20
    # Capped by REACH, not by the drawer: at 0.13 the rail sits 376 mm from the
    # base axis, and the Panda's inner workspace boundary is not far below that.
    travel_range: tuple[float, float] = (0.060, 0.130)

    pos_jitter: float = 0.020
    yaw_jitter_deg: float = 8.0

    @property
    def center_x(self) -> float:
        return self.front_x + self.depth / 2

    @property
    def opening_w(self) -> float:
        """Clear width of one drawer opening.

        From the divider's face at +panel/2 to the side wall's face at
        width/2 - panel, so width/2 - 1.5*panel. Using width/2 - 2*panel here
        puts the front panel 2 mm off centre in its own hole.
        """
        return self.width / 2 - 1.5 * self.panel

    @property
    def opening_h(self) -> float:
        return self.height - 2 * self.panel

    @property
    def drawer_y(self) -> np.ndarray:
        """(2,) drawer centre y in the cabinet frame, in SIDES order."""
        c = self.panel / 2 + self.opening_w / 2
        return np.array([c, -c], dtype=np.float64)

    @property
    def rail_x(self) -> float:
        """Rail centre x in the cabinet frame, drawer closed."""
        return -self.depth / 2 - self.gap - self.rail_thk / 2

    @property
    def standoff(self) -> float:
        """Front face of the drawer to front face of the rail."""
        return self.gap + self.rail_thk


@dataclass(frozen=True)
class TactileConfig:
    """KinematicTaxel grids on both fingertip pads.

    The probe plane sits at the finger frame's y=0, which is 1.5 mm proud of
    the pad's gripping face, so the probes protrude into whatever is gripped --
    that protrusion IS the reading. Spanning z in [0.040, 0.050] puts the grid
    across the 12 mm rail rather than off its edge.

    Reading is force only. Torque adds 24 more dimensions to say roughly what
    the force already says at this probe count.
    """
    nx: int = 2
    ny: int = 2
    lo: tuple[float, float, float] = (-0.006, 0.0, 0.040)
    hi: tuple[float, float, float] = (0.008, 0.0, 0.050)
    normal: tuple[float, float, float] = (0.0, -1.0, 0.0)

    probe_radius: float = 0.002
    # A pure linear scale on the reading, so it is chosen last: with the grip
    # squeeze reduced, 2000 put the free-pull band at 0.26-0.38 and the jammed
    # band at 0.46-0.77, and 1200 rescales those to ~0.20 and ~0.40.
    normal_stiffness: float = 1200.0
    normal_damping: float = 1.0
    normal_exponent: float = 1.5
    shear_scalar: float = 1.0
    twist_scalar: float = 1.0

    @property
    def n_probes(self) -> int:
        return self.nx * self.ny

    @property
    def dim(self) -> int:
        """Flattened feature width: two fingers, one force vector per probe."""
        return 2 * self.n_probes * 3


@dataclass(frozen=True)
class WristCameraConfig:
    """One camera on the hand, on the +x flat of the gripper.

    The fingers travel along the hand frame's y and the tool axis is +z, so
    +/-x are the only faces a camera fits on. One rather than two: with the
    jaws straddling a rail bolted to a cabinet there is no self-occluding part
    to see around, and halving the render halves the host RAM that bounded
    collection.

    It must frame BOTH drawers at the home pose -- there is no fixed camera, so
    this view is the only thing that grounds "left" against "right". Checked in
    inspect_scene.
    """
    res: tuple[int, int] = (224, 224)   # pi0.5 resizes to this anyway
    fov: float = 75.0
    near: float = 0.005
    far: float = 5.0
    offset: float = 0.055               # along the hand's +x: sideways, world +y
    back: float = 0.050                 # along the hand's -y: toward the base
    forward: float = 0.020              # along the tool axis, past the hand body
    tilt_deg: float = 45.0              # lean off the tool axis, toward the cabinet

    @property
    def mounts(self) -> tuple[tuple[str, tuple, tuple], ...]:
        """(name, offset_pos, offset_euler_deg) in the hand frame.

        Mounted on the gripper's +x flat, as in the reference -- the fingers
        travel along y and the tool axis is z, so +/-x are the only faces a
        camera fits on. The -y shift sets it behind the jaws so it looks out
        over them, which is what keeps the lower finger in frame. Without the
        sideways offset that shift alone puts the camera inside the hand body.

        The ORIENTATION does not carry over. The reference's (180, -tilt, 0)
        tilts in PITCH, about hand y, but the grasp orientation adds 90 degrees
        of wrist yaw that puts hand y on world x -- so pitch pans the view
        sideways and never toward the cabinet. Rendered: at -33 the cabinet is
        a strip on the frame edge, and at -60 and +60 it leaves frame entirely.
        The lean has to be ROLL, about hand x. A 180 roll alone then inverts
        column 1, which `T_to_pos_lookat_up` reads as up, so the scene renders
        upside down. Ry(180) @ Rx(tilt) leans toward the cabinet AND keeps up
        pointing up, which in roll-pitch-yaw order is (tilt, 180, 0).

        Both rails must stay in frame at home. With no fixed camera this view
        is the only thing grounding "left" against "right".
        """
        return (("wrist", (self.offset, -self.back, self.forward),
                 (self.tilt_deg, 180.0, 0.0)),)


@dataclass(frozen=True)
class CameraConfig:
    """One free camera, for looking at the scene. NOT an observation.

    Placed on the ROBOT's side of the cabinet. The drawer fronts face -x, so a
    camera out past the cabinet sees only its back panel.
    """
    res: tuple[int, int] = (960, 720)
    fov: float = 50.0
    pos: tuple[float, float, float] = (0.10, -0.72, 1.15)
    lookat: tuple[float, float, float] = (0.45, 0.0, 0.84)


@dataclass(frozen=True)
class TeacherConfig:
    """The scripted demonstrator.

    It may read simulator state -- it never ships. What it may NOT do is emit
    actions the policy could not infer from what it sees, which is why the
    release fires on the MEASURED taxel force rather than on the drawer's
    privileged joint position. Privileged state is the validator: task_state
    reports release latency against the true stop.
    """
    approach_clear: float = 0.060   # hover above the rail before descending
    q_open: float = 0.014           # jaws straddling the rail: separation 31 mm
    q_grip: float = 0.0             # commanded through the rail; kp sets the squeeze
    grip_steps: int = 60
    max_dq_transit: float = 0.010
    max_dq_fine: float = 0.004
    settle: int = 20

    # The descent lands DELIBERATELY off-centre. A teacher that always arrives
    # centred generates no correction data. Capped below the slot's clearance.
    descent_residual: tuple[float, float] = (0.0005, 0.0030)

    # Pull: commanded hand travel per control step, along the cabinet's -x.
    pull_rate: float = 0.0006
    pull_steps: int = 400
    # Release fires when the peak taxel reading crosses this. MEASURED, not
    # guessed: pulling with the trigger disabled reads ~0.16-0.23 while the
    # drawer is moving and ~0.28-0.46 once it is against its stop, in every env
    # and at each env's own randomized stop. This sits in the gap. The reading
    # is noisy enough to dip back under after firing, which is why the teacher
    # latches it rather than testing it fresh each step.
    #
    # Both errors are costly and asymmetric: too low fires mid-pull and the
    # drawer never opens; too high never fires and the cabinet gets dragged.
    release_force: float = 0.25
    release_steps: int = 40         # opening the jaws
    retract_height: float = 0.080
    action_noise_xy: float = 0.00015


@dataclass(frozen=True)
class SuccessConfig:
    """When an episode counts as done.

    Every criterion is latched over `hold_steps` consecutive steps: a
    single-step test can pass while things are still moving and fail again on
    the next one, which reads as success in a log and as flicker in a video.
    """
    open_eps: float = 0.004         # travel within this of the episode's stop
    closed_eps: float = 0.005       # the other drawer must not have moved
    release_width: float = 0.020    # jaw separation counting as let go
    release_force: float = 0.05     # residual taxel force counting as let go
    cabinet_shift_max: float = 0.010
    hold_steps: int = 8


@dataclass(frozen=True)
class EnvConfig:
    n_envs: int = 1
    seed: int = 0

    dt: float = 0.01
    substeps: int = 4

    # Physics steps per control tick: 4 gives exactly 25 Hz from the 100 Hz
    # simulation. This is the CONTROL rate, not a storage setting -- robot.apply
    # issues one command per tick and holds it, so the teacher and the policy
    # solve the same control problem. It cannot be revised without re-collecting.
    record_every: int = 4

    table: TableConfig = field(default_factory=TableConfig)
    franka: FrankaConfig = field(default_factory=FrankaConfig)
    cabinet: CabinetConfig = field(default_factory=CabinetConfig)
    tactile: TactileConfig = field(default_factory=TactileConfig)
    teacher: TeacherConfig = field(default_factory=TeacherConfig)
    success: SuccessConfig = field(default_factory=SuccessConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    wrist: WristCameraConfig = field(default_factory=WristCameraConfig)

    show_viewer: bool = False
    add_camera: bool = False
    add_wrist_cams: bool = False

    @property
    def record_hz(self) -> float:
        """Control and recording rate. Derived, so it cannot disagree with dt."""
        return 1.0 / (self.dt * self.record_every)

    def prompt(self, side: str) -> str:
        return f"open the {side} drawer"

    def __post_init__(self) -> None:
        if self.n_envs < 1:
            raise ValueError(f"n_envs must be >= 1, got {self.n_envs}")

        cab, tea = self.cabinet, self.teacher
        # The rear finger drops into the slot behind the rail. Its body extends
        # outward from the gripping face, so a gap that only clears the face
        # puts the finger through the drawer front.
        need = tea.q_open + self.franka.pad_face + self.franka.pad_half_thk * 2
        if cab.gap <= need:
            raise ValueError(
                f"cabinet.gap {cab.gap * 1e3:.1f} mm cannot admit a finger at "
                f"q_open={tea.q_open * 1e3:.1f} mm, which needs more than "
                f"{need * 1e3:.1f} mm. Widen the gap or close the jaws further.")
        # Jaws that do not clear the rail collide with it on the way down.
        sep = self.franka.jaw_separation(tea.q_open)
        if sep <= cab.rail_thk:
            raise ValueError(
                f"jaws open to {sep * 1e3:.1f} mm cannot straddle a "
                f"{cab.rail_thk * 1e3:.1f} mm rail.")
        # Home is where every episode starts AND the jaw width the descent
        # begins from. Two copies of one number drift silently.
        if not np.allclose(self.franka.home_qpos[-2:], tea.q_open):
            raise ValueError(
                f"home_qpos fingers {self.franka.home_qpos[-2:]} must equal "
                f"teacher.q_open {tea.q_open}")
        if cab.travel_range[1] > cab.travel_max:
            raise ValueError("travel_range exceeds the model-level travel_max")
        if cab.rail_span + 2 * cab.bracket_w > cab.opening_w:
            raise ValueError("rail plus brackets is wider than the drawer front")
        # The brackets bolt the rail to the drawer front, so the rail has to be
        # somewhere the front actually is.
        front_lo = cab.panel + cab.front_clearance
        front_hi = cab.panel + cab.opening_h - cab.front_clearance
        if not (front_lo < cab.rail_z - cab.rail_h / 2
                and cab.rail_z + cab.rail_h / 2 < front_hi):
            raise ValueError(
                f"rail at z={cab.rail_z * 1e3:.0f} mm falls outside the drawer "
                f"front, which spans {front_lo * 1e3:.0f}..{front_hi * 1e3:.0f} mm")
