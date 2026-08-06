"""Genesis Soccer Scene — RoboCup standard field dimensions.

Run:  python src/soccer_env/soccer_scene.py

Field dimensions sourced from the Booster baseline (src/framework/types.py):
  - Field: 14m x 9m
  - Goal width: 2.6m, height: ~1.0m
  - Center circle radius: 1.5m
  - Penalty area: 3m x 6m
  - Goal area: 1m x 4m
  - Ball radius: 0.11m
"""

import genesis as gs

# ------------------------------------------------------------------
# Field constants (RoboCup, from baseline types.py)
# ------------------------------------------------------------------
FIELD_L = 14.0        # field length (x axis)
FIELD_W = 9.0         # field width  (y axis)
HALF_L = FIELD_L / 2  # 7.0
HALF_W = FIELD_W / 2  # 4.5

GOAL_W = 2.6          # goal width
GOAL_H = 1.0          # goal height
POST_R = 0.05         # goal post radius (half-width of square post)

CIRCLE_R = 1.5        # center circle radius

PEN_AREA_L = 3.0      # penalty area length (x)
PEN_AREA_W = 6.0      # penalty area width  (y)

GOAL_AREA_L = 1.0     # goal area length (x)
GOAL_AREA_W = 4.0     # goal area width  (y)

BALL_R = 0.11          # ball radius
LINE_H = 0.005         # line thickness (height above ground)
LINE_W = 0.12           # line width


def build_scene():
    gs.init(backend=gs.gpu)

    scene = gs.Scene(
        sim_options=gs.options.SimOptions(dt=0.01),
        viewer_options=gs.options.ViewerOptions(
            camera_pos=(12, -12, 8),
            camera_lookat=(0, 0, 0.5),
            res=(1280, 720),
        ),
        vis_options=gs.options.VisOptions(
            show_world_frame=False,
            show_link_frame=False,
            show_cameras=False,
            plane_reflection=True,
            ambient_light=(0.7, 0.7, 0.7),
            shadow=True,
        ),
        show_viewer=True,
    )

    # ---- Ground ----
    scene.add_entity(
        morph=gs.morphs.Plane(),
        surface=gs.surfaces.Rough(color=(0.12, 0.45, 0.15), roughness=0.9),
    )

    # ---- Surface helpers ----
    white = gs.surfaces.Rough(color=(1, 1, 1), roughness=0.8)
    goal_surface = gs.surfaces.Rough(color=(0.95, 0.95, 0.95), roughness=0.5)
    ball_surface = gs.surfaces.Rough(color=(0.1, 0.1, 0.1), roughness=0.4)

    # ---- Field boundary lines ----
    # Bottom line
    scene.add_entity(
        morph=gs.morphs.Box(size=(FIELD_L, LINE_W, LINE_H), pos=(0, -HALF_W, LINE_H / 2), fixed=True),
        surface=white,
    )
    # Top line
    scene.add_entity(
        morph=gs.morphs.Box(size=(FIELD_L, LINE_W, LINE_H), pos=(0, HALF_W, LINE_H / 2), fixed=True),
        surface=white,
    )
    # Left line
    scene.add_entity(
        morph=gs.morphs.Box(size=(LINE_W, FIELD_W, LINE_H), pos=(-HALF_L, 0, LINE_H / 2), fixed=True),
        surface=white,
    )
    # Right line
    scene.add_entity(
        morph=gs.morphs.Box(size=(LINE_W, FIELD_W, LINE_H), pos=(HALF_L, 0, LINE_H / 2), fixed=True),
        surface=white,
    )
    # Center line
    scene.add_entity(
        morph=gs.morphs.Box(size=(LINE_W, FIELD_W, LINE_H), pos=(0, 0, LINE_H / 2), fixed=True),
        surface=white,
    )

    # ---- Center circle (approximate with 32 thin boxes) ----
    import math
    n_segments = 32
    for i in range(n_segments):
        angle = 2 * math.pi * i / n_segments
        cx = CIRCLE_R * math.cos(angle)
        cy = CIRCLE_R * math.sin(angle)
        scene.add_entity(
            morph=gs.morphs.Box(
                size=(0.3, LINE_W, LINE_H),
                pos=(cx, cy, LINE_H / 2),
                euler=(0, 0, math.degrees(angle)),
                fixed=True,
            ),
            surface=white,
        )

    # ---- Penalty areas (both sides) ----
    pen_half_w = PEN_AREA_W / 2
    # Left penalty area
    pen_left_x = -HALF_L + PEN_AREA_L / 2
    scene.add_entity(morph=gs.morphs.Box(size=(LINE_W, PEN_AREA_W, LINE_H), pos=(pen_left_x, -pen_half_w, LINE_H / 2), fixed=True), surface=white)
    scene.add_entity(morph=gs.morphs.Box(size=(LINE_W, PEN_AREA_W, LINE_H), pos=(pen_left_x, pen_half_w, LINE_H / 2), fixed=True), surface=white)
    scene.add_entity(morph=gs.morphs.Box(size=(PEN_AREA_L, LINE_W, LINE_H), pos=(-HALF_L, pen_half_w, LINE_H / 2), fixed=True), surface=white)
    scene.add_entity(morph=gs.morphs.Box(size=(PEN_AREA_L, LINE_W, LINE_H), pos=(-HALF_L, -pen_half_w, LINE_H / 2), fixed=True), surface=white)

    # Right penalty area
    pen_right_x = HALF_L - PEN_AREA_L / 2
    scene.add_entity(morph=gs.morphs.Box(size=(LINE_W, PEN_AREA_W, LINE_H), pos=(pen_right_x, -pen_half_w, LINE_H / 2), fixed=True), surface=white)
    scene.add_entity(morph=gs.morphs.Box(size=(LINE_W, PEN_AREA_W, LINE_H), pos=(pen_right_x, pen_half_w, LINE_H / 2), fixed=True), surface=white)
    scene.add_entity(morph=gs.morphs.Box(size=(PEN_AREA_L, LINE_W, LINE_H), pos=(HALF_L, pen_half_w, LINE_H / 2), fixed=True), surface=white)
    scene.add_entity(morph=gs.morphs.Box(size=(PEN_AREA_L, LINE_W, LINE_H), pos=(HALF_L, -pen_half_w, LINE_H / 2), fixed=True), surface=white)

    # ---- Goal areas (both sides) ----
    ga_half_w = GOAL_AREA_W / 2
    # Left goal area
    ga_left_x = -HALF_L + GOAL_AREA_L / 2
    scene.add_entity(morph=gs.morphs.Box(size=(LINE_W, GOAL_AREA_W, LINE_H), pos=(ga_left_x, -ga_half_w, LINE_H / 2), fixed=True), surface=white)
    scene.add_entity(morph=gs.morphs.Box(size=(LINE_W, GOAL_AREA_W, LINE_H), pos=(ga_left_x, ga_half_w, LINE_H / 2), fixed=True), surface=white)
    # Right goal area
    ga_right_x = HALF_L - GOAL_AREA_L / 2
    scene.add_entity(morph=gs.morphs.Box(size=(LINE_W, GOAL_AREA_W, LINE_H), pos=(ga_right_x, -ga_half_w, LINE_H / 2), fixed=True), surface=white)
    scene.add_entity(morph=gs.morphs.Box(size=(LINE_W, GOAL_AREA_W, LINE_H), pos=(ga_right_x, ga_half_w, LINE_H / 2), fixed=True), surface=white)

    # ---- Goals (left and right) ----
    post_w = POST_R * 2
    half_goal = GOAL_W / 2

    def add_goal(goal_x: float):
        # Left post
        scene.add_entity(
            morph=gs.morphs.Box(
                size=(post_w, post_w, GOAL_H),
                pos=(goal_x, -half_goal, GOAL_H / 2),
                fixed=True,
            ),
            surface=goal_surface,
        )
        # Right post
        scene.add_entity(
            morph=gs.morphs.Box(
                size=(post_w, post_w, GOAL_H),
                pos=(goal_x, half_goal, GOAL_H / 2),
                fixed=True,
            ),
            surface=goal_surface,
        )
        # Crossbar
        scene.add_entity(
            morph=gs.morphs.Box(
                size=(post_w, GOAL_W + post_w, post_w),
                pos=(goal_x, 0, GOAL_H),
                fixed=True,
            ),
            surface=goal_surface,
        )

    add_goal(-HALF_L)
    add_goal(HALF_L)

    # ---- Soccer ball ----
    ball = scene.add_entity(
        morph=gs.morphs.Sphere(
            radius=BALL_R,
            pos=(0, 0, BALL_R),
            fixed=False,
        ),
        surface=ball_surface,
        material=gs.materials.Rigid(rho=400.0, friction=0.8),
    )

    # ---- K1 Robot (if URDF available) ----
    import os
    k1_paths = [
        os.path.expanduser("~/BoosterStudioProjects/booster_assets/robots/K1/K1_22dof.urdf"),
        "/workspace/booster_assets/robots/K1/K1_22dof.urdf",
        "booster_assets/robots/K1/K1_22dof.urdf",
    ]
    urdf_path = next((p for p in k1_paths if os.path.exists(p)), None)

    if urdf_path:
        print(f"[scene] Loading K1 from: {urdf_path}")
        robot = scene.add_entity(
            gs.morphs.URDF(
                file=urdf_path,
                pos=(0, 0, 0.5),
            ),
        )
    else:
        print("[scene] K1 URDF not found, skipping robot. Place booster_assets in one of:")
        for p in k1_paths:
            print(f"  {p}")
        robot = None

    # ---- Build ----
    scene.build()
    print("[scene] Build complete. Starting simulation...")

    return scene, ball, robot


if __name__ == "__main__":
    scene, ball, robot = build_scene()

    # Run simulation: ball drops from center, robot stands
    for i in range(10000):
        scene.step()
