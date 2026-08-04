import time
import mujoco
import mujoco.viewer
from threading import Thread
import threading

from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py_bridge import UnitreeSdk2Bridge, ElasticBand

import config


locker = threading.Lock()

mj_model = mujoco.MjModel.from_xml_path(config.ROBOT_SCENE)
mj_data = mujoco.MjData(mj_model)

# 让机器人从站立 keyframe 起步。keyframe 高度由接触二分求解得 0.7592，
# 脚会陷进地板，MuJoCo 用巨大接触力弹开导致姿态崩坏。
if mj_model.nkey > 0:
    mujoco.mj_resetDataKeyframe(mj_model, mj_data, 0)
    mj_data.ctrl[:] = mj_model.key_qpos[0][7:]
    print(f"[init] 已加载 keyframe, base_z={mj_data.qpos[2]:.4f}", flush=True)


if config.ENABLE_ELASTIC_BAND:
    elastic_band = ElasticBand()
    if config.ROBOT == "h1" or config.ROBOT == "g1":
        band_attached_link = mj_model.body("torso_link").id
    else:
        band_attached_link = mj_model.body("base_link").id
    viewer = mujoco.viewer.launch_passive(
        mj_model, mj_data, key_callback=elastic_band.MujuocoKeyCallback
    )
else:
    viewer = mujoco.viewer.launch_passive(mj_model, mj_data)

mj_model.opt.timestep = config.SIMULATE_DT
num_motor_ = mj_model.nu
dim_motor_sensor_ = 3 * num_motor_

time.sleep(0.2)


def SimulationThread():
    global mj_data, mj_model

    ChannelFactoryInitialize(config.DOMAIN_ID, config.INTERFACE)
    unitree = UnitreeSdk2Bridge(mj_model, mj_data)

    if config.USE_JOYSTICK:
        unitree.SetupJoystick(device_id=0, js_type=config.JOYSTICK_TYPE)
    if config.PRINT_SCENE_INFORMATION:
        unitree.PrintSceneInformation()

    while viewer.is_running():
        step_start = time.perf_counter()

        locker.acquire()

        if config.ENABLE_ELASTIC_BAND:
            if elastic_band.enable:
                mj_data.xfrc_applied[band_attached_link, :3] = elastic_band.Advance(
                    mj_data.qpos[:3], mj_data.qvel[:3]
                )
        unitree.ApplyPD()          # 🔴 每个仿真步重算 PD（对齐真机驱动器）
        mujoco.mj_step(mj_model, mj_data)

        locker.release()

        time_until_next_step = mj_model.opt.timestep - (
            time.perf_counter() - step_start
        )
        if time_until_next_step > 0:
            time.sleep(time_until_next_step)

        # 实时率监测：仿真时间 / 墙钟时间。<1 说明仿真跑不动，
        # 而控制端仍按墙钟 50Hz 发指令，动作在仿真里就被加速播放了。
        global _t0
        try:
            _t0
        except NameError:
            _t0 = time.perf_counter()
        _wall = time.perf_counter() - _t0
        if _wall > 0 and int(_wall * 2) != int((_wall - mj_model.opt.timestep) * 2):
            print(f"[rt] sim={mj_data.time:6.2f}s wall={_wall:6.2f}s "
                  f"实时率={mj_data.time/_wall:.3f}", flush=True)


def PhysicsViewerThread():
    while viewer.is_running():
        locker.acquire()
        viewer.sync()
        locker.release()
        time.sleep(config.VIEWER_DT)


if __name__ == "__main__":
    viewer_thread = Thread(target=PhysicsViewerThread)
    sim_thread = Thread(target=SimulationThread)

    viewer_thread.start()
    sim_thread.start()
