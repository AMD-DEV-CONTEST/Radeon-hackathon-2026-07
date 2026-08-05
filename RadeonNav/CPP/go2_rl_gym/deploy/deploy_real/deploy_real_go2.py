from pathlib import Path
LEGGED_GYM_ROOT_DIR = str(Path(__file__).parents[2])
import numpy as np
import time
import torch

from unitree_sdk2py.core.channel import ChannelPublisher,ChannelSubscriber,ChannelFactoryInitialize
from unitree_sdk2py.idl.default import unitree_go_msg_dds__LowCmd_,unitree_go_msg_dds__LowState_
from unitree_sdk2py.idl.unitree_go.msg.dds_ import LowCmd_ as LowCmdGo
from unitree_sdk2py.idl.unitree_go.msg.dds_ import LowState_ as LowStateGo

from unitree_sdk2py.utils.crc import CRC

from common.command_helper import create_zero_cmd,create_damping_cmd
from common.rotation_helper import get_gravity_orientation
from common.remote_controller import RemoteController, KeyMap
from config_go2 import Config

HIGHLEVEL = 0xEE
LOWLEVEL = 0xFF
TRIGERLEVEL = 0xF0
PosStopF = 2.146e9
VelStopF = 16000.0


def init_cmd_go2(cmd:LowCmdGo):
    cmd.head[0] = 0xFE
    cmd.head[1] = 0xEF
    cmd.level_flag = 0xFF
    cmd.gpio = 0
    for i in range(12):
        cmd.motor_cmd[i].mode = 0x0A  # 0x01
        cmd.motor_cmd[i].q = PosStopF
        cmd.motor_cmd[i].dq = VelStopF  # or qd
        cmd.motor_cmd[i].kp = 0.0
        cmd.motor_cmd[i].kd = 0.0
        cmd.motor_cmd[i].tau = 0.0


class Controller:
    def __init__(self,config:Config) -> None:
        self.config = config
        self.remote_controller = RemoteController()
        self.use_remote_controller = True

        self.policy = torch.jit.load(config.policy_path)
        self._warm_up()

        self.qj = np.zeros(config.num_actions,dtype=np.float32)
        self.dqj = np.zeros(config.num_actions,dtype=np.float32)
        self.action = np.zeros(config.num_actions,dtype=np.float32)
        self.target_dof_pos = config.default_angles.copy()
        self.obs = np.zeros(config.num_obs,dtype=np.float32)
        self.cmd = np.array([0.8, 0, 0],dtype=np.float32)
        self.counter = 0

        self.low_cmd = unitree_go_msg_dds__LowCmd_()
        self.low_state = unitree_go_msg_dds__LowState_()
        self.lowcmd_publisher = ChannelPublisher(config.lowcmd_topic,LowCmdGo)
        self.lowcmd_publisher.Init()
        self.lowstate_subscriber = ChannelSubscriber(config.lowstate_topic,LowStateGo)
        self.lowstate_subscriber.Init(self.LowStateHandler,10)
        # self.replay_buffer = ReplayBuffer(max_replay_buffer_size=200,flag='real_new')

        self.wait_for_low_state()
        init_cmd_go2(self.low_cmd)

    def _warm_up(self):
        obs = torch.ones((1,45))
        for _ in range(10):
            _ = self.policy(obs)
        print('Network has been warmed up.')

    def wait_for_low_state(self):
        while self.low_state.tick == 0:
            time.sleep(self.config.control_dt)
        print("Successfully connected to the robot.")

    def LowStateHandler(self,msg:LowStateGo):
        self.low_state = msg
        self.remote_controller.set(self.low_state.wireless_remote)

    def send_cmd(self,cmd:LowCmdGo):
        cmd.crc = CRC().Crc(cmd)
        self.lowcmd_publisher.Write(cmd)

    def zero_torque_state(self):
        print("Enter zero torque state.")
        print("Waiting for the *start* signal...")
        while self.remote_controller.button[KeyMap.start] != 1:
            create_zero_cmd(self.low_cmd)
            self.send_cmd(self.low_cmd)
            time.sleep(self.config.control_dt)
        print("Start signal received.")
        print("Press *select* button to exit.")


    def move_to_default_pos(self):
        print('Moving to default pos.')
        total_time = 2
        num_step = int(total_time / self.config.control_dt)

        dof_idx = self.config.joint2motor_idx
        default_pos = self.config.default_angles


        init_dof_pos = np.zeros(12,dtype=np.float32)
        for i in range(12):
            init_dof_pos[i] = self.low_state.motor_state[dof_idx[i]].q

        for i in range(num_step):
            alpha = i / num_step
            for j in range(12):
                motor_idx = dof_idx[j]
                target_pos = default_pos[j]
                self.low_cmd.motor_cmd[motor_idx].q = init_dof_pos[j] * (1 - alpha) + target_pos * alpha
                self.low_cmd.motor_cmd[motor_idx].dq = 0.0  # qd
                self.low_cmd.motor_cmd[motor_idx].kp = 40.0
                self.low_cmd.motor_cmd[motor_idx].kd = 0.6
                self.low_cmd.motor_cmd[motor_idx].tau = 0.0
            self.send_cmd(self.low_cmd)
            time.sleep(self.config.control_dt)


    def default_pos_state(self):
        print("Enter default pos state.")
        print("Waiting for the *Button A* signal...")
        while self.remote_controller.button[KeyMap.A] != 1:
            for i in range(12):
                motor_idx = self.config.joint2motor_idx[i]
                self.low_cmd.motor_cmd[motor_idx].q = self.config.default_angles[i]
                self.low_cmd.motor_cmd[motor_idx].dq = 0.0  # qd
                self.low_cmd.motor_cmd[motor_idx].kp = 40.0
                self.low_cmd.motor_cmd[motor_idx].kd = 0.6
                self.low_cmd.motor_cmd[motor_idx].tau = 0
            self.send_cmd(self.low_cmd)
            time.sleep(self.config.control_dt)


    def run(self):
        self.counter += 1
        for i in range(12):
            self.qj[i] = self.low_state.motor_state[self.config.joint2motor_idx[i]].q
            self.dqj[i] = self.low_state.motor_state[self.config.joint2motor_idx[i]].dq

        ang_vel = np.array([self.low_state.imu_state.gyroscope], dtype=np.float32) * self.config.obs_scales_ang_vel
        quat = self.low_state.imu_state.quaternion
        gravity_orientation = get_gravity_orientation(quat)  # imu_state quaternion: w, x, y, z

        if self.use_remote_controller:
             self.cmd[0] = self.remote_controller.ly
             self.cmd[1] = self.remote_controller.lx * -1
             self.cmd[2] = self.remote_controller.rx * -1

        qj_obs = self.qj.copy()
        qj_obs = (qj_obs - self.config.default_angles) * self.config.obs_scales_dof_pos
        dqj_obs = self.dqj.copy()
        dqj_obs = dqj_obs * self.config.obs_scales_dof_vel

        self.obs[:3] = ang_vel
        self.obs[3:6] = gravity_orientation
        self.obs[6:9] = self.cmd * self.config.command_scale
        self.obs[9:21] = qj_obs
        self.obs[21:33] = dqj_obs
        self.obs[33:45] = self.action

        obs_tensor = torch.from_numpy(self.obs).unsqueeze(0)
        results = self.policy(obs_tensor)
        if isinstance(results, tuple):
            self.action = results[0]
        else:
            self.action = results
        self.action = self.action.detach().numpy().squeeze()

        target_dof_pos = self.config.default_angles + self.action * self.config.action_scale
        # target_dof_pos = self.config.default_angles

        for i in range(12):
            motor_idx = self.config.joint2motor_idx[i]
            self.low_cmd.motor_cmd[motor_idx].q = target_dof_pos[i]
            self.low_cmd.motor_cmd[motor_idx].dq = 0.0
            self.low_cmd.motor_cmd[motor_idx].kp = 20.0
            self.low_cmd.motor_cmd[motor_idx].kd = 0.5
            self.low_cmd.motor_cmd[motor_idx].tau = 0

        self.send_cmd(self.low_cmd)
        time.sleep(self.config.control_dt)
        
        # === 调试：遥控器 & 模型输出 ===
        # print(f"RC: lx={self.remote_controller.lx:+.2f} ly={self.remote_controller.ly:+.2f} "
        #        f"rx={self.remote_controller.rx:+.2f}")
        # print(f"OBS cmd: {self.obs[6:9]}")                 # 遥控器信号在 obs 的位置
        # print(f"RAW action: {self.action[:4]}...")         # 只看前 4 个，防止刷屏
        # print(f"TARGET Q: {target_dof_pos[::3]}")          # 每 3 个关节抽 1 个，易读

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("net", type=str, help="network interface")
    args = parser.parse_args()

    config_path = f"{LEGGED_GYM_ROOT_DIR}/deploy/deploy_real/configs/go2.yaml"
    config = Config(config_path)

    ChannelFactoryInitialize(0, args.net)

    controller = Controller(config)

    controller.zero_torque_state()
    controller.move_to_default_pos()
    controller.default_pos_state()

    while True:
        try:
            controller.run()
            if controller.remote_controller.button[KeyMap.select] == 1:
                break
        except KeyboardInterrupt:
            break


    create_damping_cmd(controller.low_cmd)
    controller.send_cmd(controller.low_cmd)
    print('Exit')

