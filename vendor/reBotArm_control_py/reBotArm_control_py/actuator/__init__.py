"""actuator 模块 — JointGroup 架构（分组控制，同步发送）。

所有参数均在 config/rebotarm.yaml 中定义，hardware_yaml 字段指定硬件配置文件。

示例::

    rebotarm = RebotArm()   # 自动从 rebotarm.yaml 读取 hardware_yaml
    rebotarm.connect()
    rebotarm.arm.enable()
    rebotarm.gripper.enable()
    rebotarm.arm.mode_pos_vel()       # arm 组切换模式
    rebotarm.gripper.mode_mit()       # gripper 组切换模式

    def loop(r, dt):
        r.arm.send_pos_vel(joint_pos)     # arm 组发送
        r.gripper.send_mit(gripper_pos)   # gripper 组发送

    rebotarm.start_control_loop(loop)
    rebotarm.stop_control_loop()
    rebotarm.disconnect()
"""

from .rebotarm import RebotArm, JointGroup, JointCfg, load_cfg

__all__ = [
    "RebotArm",
    "JointGroup",
    "JointCfg",
    "load_cfg",
]
