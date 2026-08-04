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
from mujoco_playground._src.locomotion.g1 import base, g1_constants as consts

m = mujoco.MjModel.from_xml_string(
    Path(consts.FEET_ONLY_FLAT_TERRAIN_XML).read_text(), base.get_assets())
default = m.keyframe("home").qpos[7:]
names = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_ACTUATOR, i) for i in range(m.nu)]

for tag in ("salute_upright", "tennis"):
    ref = np.load(fstr(C.MOTIONS_BM) + "/{tag}.npz")["joint_pos"]
    dev = np.abs(ref - default)                      # (T, 29)
    peak = dev.max(axis=0)
    print(f"\n{'='*72}\n{tag}  —— 参考角度相对 default_pose 的最大偏移\n{'='*72}")
    print(f"{'joint':<30} {'峰值偏移':>9} {'需要的scale':>11}  超出0.5?")
    over = 0
    for i in np.argsort(-peak):
        flag = ""
        if peak[i] > 0.5:
            flag = f"  ← 超 {peak[i]/0.5:.1f}x"
            over += 1
        if peak[i] > 0.15 or flag:
            print(f"{names[i]:<30} {peak[i]:>9.3f} {peak[i]:>11.3f}{flag}")
    print(f"\n  29 个关节里 {over} 个的峰值偏移超过 action_scale=0.5")
    print(f"  全身峰值 {peak.max():.3f} rad ({np.degrees(peak.max()):.0f}°) "
          f"@ {names[int(peak.argmax())]}")
    # 有多少比例的"帧×关节"是够不到的
    frac = float((dev > 0.5).mean())
    print(f"  够不到的 (帧×关节) 占比: {frac*100:.1f}%")
    # 只看上肢
    frac_u = float((dev[:, 15:] > 0.5).mean())
    print(f"  其中上肢 (15~28) 够不到占比: {frac_u*100:.1f}%")
