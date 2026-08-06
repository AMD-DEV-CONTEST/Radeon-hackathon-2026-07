"""
multi-robot Match Scene Builder for Genesis.

Builds a Genesis scene with:
  - Soccer field (green ground, white lines, goals)
  - 6 T1 robots (3 left team + 3 right team)
  - 1 ball
  - Cameras for recording

This module ONLY builds the scene and returns entity handles.
Match logic (role assignment, policy, scoring) is in match_3v3.py.

Usage:
    from match_scene import build_3v3_scene
    scene, robots, ball, cam = build_3v3_scene()
"""

from __future__ import annotations
import math, os
import numpy as np

try:
    import genesis as gs
except Exception:
    gs = None

# Field constants (must match match_3v3.py)
FIELD_L = 14.0
FIELD_W = 9.0
HALF_L = FIELD_L / 2
HALF_W = FIELD_W / 2
GOAL_W = 2.6
GOAL_H = 1.0
POST_R = 0.05
CIRCLE_R = 1.5
LINE_H = 0.005
LINE_W = 0.12
BALL_R = 0.11
ROBOT_HEIGHT = 0.72

# Robot formations
LEFT_START = [(-1.0, 0.0), (-3.5, 1.5), (-6.5, 0.0)]
RIGHT_START = [(1.0, 0.0), (3.5, -1.5), (6.5, 0.0)]


def _add_field_lines(scene):
    """Add white boundary lines, center circle, penalty areas."""
    white = gs.surfaces.Rough(color=(1, 1, 1), roughness=0.8)

    # Boundary lines
    for x, y in [(0, -HALF_W), (0, HALF_W)]:
        scene.add_entity(
            morph=gs.morphs.Box(size=(FIELD_L, LINE_W, LINE_H), pos=(x, y, LINE_H/2), fixed=True),
            surface=white)
    for x, y in [(-HALF_L, 0), (HALF_L, 0), (0, 0)]:
        scene.add_entity(
            morph=gs.morphs.Box(size=(LINE_W, FIELD_W, LINE_H), pos=(x, y, LINE_H/2), fixed=True),
            surface=white)

    # Center circle
    for i in range(32):
        a = 2 * math.pi * i / 32
        cx = CIRCLE_R * math.cos(a)
        cy = CIRCLE_R * math.sin(a)
        scene.add_entity(
            morph=gs.morphs.Box(size=(0.3, LINE_W, LINE_H), pos=(cx, cy, LINE_H/2),
                               euler=(0, 0, math.degrees(a)), fixed=True),
            surface=white)

    # Penalty areas
    pw = 3.0
    for px in [-HALF_L + 1.5, HALF_L - 1.5]:
        scene.add_entity(
            morph=gs.morphs.Box(size=(LINE_W, 6.0, LINE_H), pos=(px, -pw, LINE_H/2), fixed=True),
            surface=white)
        scene.add_entity(
            morph=gs.morphs.Box(size=(LINE_W, 6.0, LINE_H), pos=(px, pw, LINE_H/2), fixed=True),
            surface=white)
    for sx in [-HALF_L, HALF_L]:
        scene.add_entity(
            morph=gs.morphs.Box(size=(3.0, LINE_W, LINE_H), pos=(sx, pw, LINE_H/2), fixed=True),
            surface=white)
        scene.add_entity(
            morph=gs.morphs.Box(size=(3.0, LINE_W, LINE_H), pos=(sx, -pw, LINE_H/2), fixed=True),
            surface=white)


def _add_goals(scene):
    """Add left and right goal posts + crossbars."""
    goal_s = gs.surfaces.Rough(color=(0.95, 0.95, 0.95), roughness=0.5)
    hg = GOAL_W / 2
    pw2 = POST_R * 2
    for gx in [-HALF_L, HALF_L]:
        # Left post
        scene.add_entity(
            morph=gs.morphs.Box(size=(pw2, pw2, GOAL_H), pos=(gx, -hg, GOAL_H/2), fixed=True),
            surface=goal_s)
        # Right post
        scene.add_entity(
            morph=gs.morphs.Box(size=(pw2, pw2, GOAL_H), pos=(gx, hg, GOAL_H/2), fixed=True),
            surface=goal_s)
        # Crossbar
        scene.add_entity(
            morph=gs.morphs.Box(size=(pw2, GOAL_W + pw2, pw2), pos=(gx, 0, GOAL_H), fixed=True),
            surface=goal_s)


def build_3v3_scene(robot_urdf: str, show_viewer: bool = False, record_video: bool = True):
    """Build a multi-robot soccer scene with 6 robots.

    Parameters
    ----------
    robot_urdf : str
        Path to T1 robot MJCF/URDF file.
    show_viewer : bool
        If True, show interactive viewer.
    record_video : bool
        If True, add camera for recording.

    Returns
    -------
    scene : gs.Scene
    robots : list of 6 robot entities [L0, L1, L2, R0, R1, R2]
    ball : ball entity
    cam : camera (or None)
    """
    scene = gs.Scene(
        sim_options=gs.options.SimOptions(dt=0.02, substeps=2),
        rigid_options=gs.options.RigidOptions(
            enable_self_collision=True, tolerance=1e-5, max_collision_pairs=2048),
        viewer_options=gs.options.ViewerOptions(
            camera_pos=(0, -15, 10), camera_lookat=(0, 0, 0.5), camera_fov=50, res=(1280, 720)),
        vis_options=gs.options.VisOptions(
            show_world_frame=False,
            show_link_frame=False,
            show_cameras=False,
            plane_reflection=True,
            ambient_light=(0.7, 0.7, 0.7),
            shadow=True),
        renderer=gs.renderers.Rasterizer(),
        show_viewer=show_viewer,
    )

    # Green ground
    scene.add_entity(
        morph=gs.morphs.Plane(),
        surface=gs.surfaces.Rough(color=(0.12, 0.45, 0.15), roughness=0.9))

    # Field lines and goals
    _add_field_lines(scene)
    _add_goals(scene)

    # 6 robots: left team [0,1,2], right team [3,4,5]
    robots = []
    for i, (x, y) in enumerate(LEFT_START):
        robot = scene.add_entity(
            gs.morphs.MJCF(file=robot_urdf, pos=(x, y, ROBOT_HEIGHT)))
        robots.append(robot)

    for i, (x, y) in enumerate(RIGHT_START):
        robot = scene.add_entity(
            gs.morphs.MJCF(file=robot_urdf, pos=(x, y, ROBOT_HEIGHT)))
        robots.append(robot)

    # Ball at center
    ball = scene.add_entity(
        morph=gs.morphs.Sphere(radius=BALL_R, pos=(0, 0, BALL_R), fixed=False),
        surface=gs.surfaces.Rough(color=(0.1, 0.1, 0.1), roughness=0.4),
        material=gs.materials.Rigid(rho=400.0, friction=0.8))

    # Camera for recording (broadcast angle)
    cam = None
    if record_video:
        cam = scene.add_camera(
            res=(1280, 720), pos=(0, -15, 10), lookat=(0, 0, 0.5), fov=50, GUI=False)

    scene.build(n_envs=1)
    return scene, robots, ball, cam


def reset_positions(scene, robots, ball):
    """Reset all robots and ball to starting positions."""
    import torch

    # Reset robots
    for i, (x, y) in enumerate(LEFT_START + RIGHT_START):
        # Set position via qpos
        pass  # Will be implemented with actual Genesis API after testing

    # Reset ball to center
    ball_qpos = torch.tensor([[0, 0, BALL_R, 1, 0, 0, 0]], device=scene.device)
    ball.set_qpos(ball_qpos)
