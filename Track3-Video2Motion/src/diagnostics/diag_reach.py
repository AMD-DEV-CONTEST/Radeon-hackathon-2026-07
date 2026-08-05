"""可达性检查：action_scale 够不够把关节送到参考角度？

位置执行器在稳态下 q ≈ ctrl，而 ctrl = default_pose + action * action_scale，
action ∈ [-1, 1]。所以关节能到达的范围就是 default_pose ± action_scale。

如果参考轨迹要求的偏移超出这个范围，策略**物理上做不出那个动作** ——
再怎么训练也没用。这是"手上动作做不出来"最直接的候选解释。
"""
import sys

import numpy as np
from pathlib import Path
import mujoco

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as C  # noqa: E402
from mujoco_playground._src.locomotion.g1 import base, g1_constants as consts

m = mujoco.MjModel.from_xml_string(
    Path(consts.FEET_ONLY_FLAT_TERRAIN_XML).read_text(), base.get_assets())
default = m.keyframe("home").qpos[7:]
names = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_ACTUATOR, i) for i in range(m.nu)]

# Which motions to check; every one that exists under motions_bm by default.
tags = sys.argv[1:] or sorted(p.stem for p in C.MOTIONS_BM.glob("*.npz"))
for tag in tags:
    ref = np.load(f"{C.MOTIONS_BM}/{tag}.npz")["joint_pos"]
    dev = np.abs(ref - default)                      # (T, 29)
    peak = dev.max(axis=0)
    print(f"\n{'='*72}\n{tag}  — peak deviation of the reference from default_pose\n{'='*72}")
    print(f"{'joint':<30} {'peak dev':>9} {'scale needed':>13}  over 0.5?")
    over = 0
    for i in np.argsort(-peak):
        flag = ""
        if peak[i] > 0.5:
            flag = f"  <- {peak[i]/0.5:.1f}x over"
            over += 1
        if peak[i] > 0.15 or flag:
            print(f"{names[i]:<30} {peak[i]:>9.3f} {peak[i]:>11.3f}{flag}")
    print(f"\n  {over} of 29 joints exceed action_scale=0.5")
    print(f"  overall peak {peak.max():.3f} rad ({np.degrees(peak.max()):.0f} deg) "
          f"@ {names[int(peak.argmax())]}")
    # 有多少比例的"帧×关节"是够不到的
    frac = float((dev > 0.5).mean())
    print(f"  unreachable (frame x joint): {frac*100:.1f}%")
    # 只看上肢
    frac_u = float((dev[:, 15:] > 0.5).mean())
    print(f"  unreachable in the upper body (15-28): {frac_u*100:.1f}%")
