"""Render one frame at several azimuths to pick a three-quarter front view.

MuJoCo's azimuth is the camera bearing in the horizontal plane. Which bearing
looks right depends on root_quat, so guessing does not work; rendering the
options is faster.
"""
from pathlib import Path

import mujoco
import numpy as np

from mujoco_playground._src.locomotion.g1 import base, g1_constants as C

REF = str(C.MOTIONS_BM) + "/salute.npz"
OUT = C.RENDER_OUT / "camtest"
OUT.mkdir(parents=True, exist_ok=True)

m = mujoco.MjModel.from_xml_string(
    Path(C.FEET_ONLY_FLAT_TERRAIN_XML).read_text(), base.get_assets())
W = H = 420
m.vis.global_.offwidth = max(m.vis.global_.offwidth, W)
m.vis.global_.offheight = max(m.vis.global_.offheight, H)
d = mujoco.MjData(m)
r = mujoco.Renderer(m, height=H, width=W)

ref = np.load(REF)
t = 70                                   # the held part of the salute
d.qpos[0:3] = ref["root_pos"][t]
d.qpos[3:7] = ref["root_quat"][t]
d.qpos[7:] = ref["joint_pos"][t]
d.qvel[:] = 0
mujoco.mj_forward(m, d)

# Robot heading: where the torso's local +x points in world coordinates.
tor = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "torso_link")
fwd = d.xmat[tor].reshape(3, 3) @ np.array([1.0, 0, 0])
print(f"robot forward (world) = {np.round(fwd, 3)}")
print(f"facing azimuth        = {np.degrees(np.arctan2(fwd[1], fwd[0])):.1f} deg")
print("For a front view the camera azimuth should be facing_azimuth + 180.")

cam = mujoco.MjvCamera()
mujoco.mjv_defaultCamera(cam)
cam.distance, cam.elevation = 3.0, -8
cam.lookat[:] = [d.qpos[0], d.qpos[1], 0.8]

tiles = []
azis = [-90, -45, 0, 45, 90, 135, 180, 225]
for a in azis:
    cam.azimuth = a
    r.update_scene(d, camera=cam)
    img = r.render().astype(np.uint8).copy()
    img[:6, :, :] = 0                     # separator
    tiles.append(img)

row1 = np.hstack(tiles[:4])
row2 = np.hstack(tiles[4:])
grid = np.vstack([row1, row2])
import imageio.v2 as iio
iio.imwrite(OUT / "azimuth_grid.png", grid)
print(f"\nsaved {OUT/'azimuth_grid.png'}")
print("top row azimuth:    " + "  ".join(f"{a:>5}" for a in azis[:4]))
print("bottom row azimuth: " + "  ".join(f"{a:>5}" for a in azis[4:]))
