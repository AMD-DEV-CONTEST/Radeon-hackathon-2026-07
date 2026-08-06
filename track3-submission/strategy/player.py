"""Player — 单个机器人的控制层。

参考 Booster 官方基线 player.py，适配 Genesis + T1。
每个 Player 包装一个 env 中的 robot，提供高层动作方法。
"""

import math
import torch
import numpy as np
from . import param as P


class Player:
    """单个球员的控制 handle。"""

    def __init__(self, robot_idx, team, role, env):
        self.id = robot_idx
        self.team = team          # 'left' or 'right'
        self.role = role          # 'attacker', 'defender', 'goalkeeper'
        self.env = env
        self.action = "init"

        # 跨帧状态
        self._kicking = False
        self._dribble_active = False
        self._last_velocity = np.zeros(3)

    # === 状态读取 ===

    @property
    def pos(self):
        """机器人世界坐标 (x, y, z)"""
        return self.env.all_base_pos[:, self.id, :].cpu().numpy()[0]

    @property
    def pos_2d(self):
        """机器人 2D 位置 (x, y)"""
        p = self.pos
        return np.array([p[0], p[1]])

    @property
    def height(self):
        return self.pos[2]

    @property
    def is_fallen(self):
        return self.height < P.FALL_HEIGHT

    @property
    def quat(self):
        return self.env.all_base_quat[:, self.id, :].cpu().numpy()[0]

    @property
    def yaw(self):
        """从四元数提取 yaw 角"""
        w, x, y, z = self.quat
        return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))

    @property
    def velocity_cmd(self):
        """上一步的速度指令"""
        return self._last_velocity

    # === 底层控制 ===

    def set_velocity(self, vx, vy, vyaw):
        """设置速度指令 (vx, vy, vyaw)。
        这个指令会被 env.step() 传给 walk model 转换为关节目标。
        """
        vx = np.clip(vx, -P.HL_CLIP_LIN, P.HL_CLIP_LIN)
        vy = np.clip(vy, -P.HL_CLIP_LIN, P.HL_CLIP_LIN)
        vyaw = np.clip(vyaw, -P.HL_CLIP_ANG, P.HL_CLIP_ANG)
        # 死区
        if abs(vx) < 0.05: vx = 0.0
        if abs(vy) < 0.05: vy = 0.0
        if abs(vyaw) < 0.05: vyaw = 0.0
        self._last_velocity = np.array([vx, vy, vyaw])

    def stop(self):
        self.set_velocity(0, 0, 0)
        self._kicking = False

    def get_velocity_cmd(self):
        return self._last_velocity

    # === 高层动作 ===

    def chase_ball(self, ball_pos):
        """追球：计算朝球的速度指令"""
        my_pos = self.pos_2d
        ball_2d = np.array([ball_pos[0], ball_pos[1]])
        direction = ball_2d - my_pos
        dist = np.linalg.norm(direction)

        if dist < 0.01:
            self.set_velocity(0, 0, 0)
            return

        # 朝球方向走
        vx = direction[0] / dist * 0.5
        vy = direction[1] / dist * 0.5

        # 朝球转
        target_angle = math.atan2(direction[1], direction[0])
        yaw_diff = target_angle - self.yaw
        # 归一化到 [-pi, pi]
        yaw_diff = math.atan2(math.sin(yaw_diff), math.cos(yaw_diff))
        vyaw = np.clip(yaw_diff * 2.0, -0.5, 0.5)

        self.set_velocity(vx, vy, vyaw)
        self.action = "chase"

    def attack(self, ball_pos, goal_pos):
        """进攻：追球 + 踢球"""
        my_pos = self.pos_2d
        ball_2d = np.array([ball_pos[0], ball_pos[1]])
        dist_to_ball = np.linalg.norm(ball_2d - my_pos)

        if dist_to_ball < P.KICK_ENTER_M:
            # 在踢球范围内：对准球门踢
            goal_2d = np.array([goal_pos[0], goal_pos[1]])
            kick_dir = goal_2d - ball_2d
            kick_dir_norm = kick_dir / (np.linalg.norm(kick_dir) + 1e-6)

            # 站到球后面，对准球门
            behind = ball_2d - kick_dir_norm * P.CHASE_BEHIND_M
            direction = behind - my_pos
            d = np.linalg.norm(direction)
            if d > 0.05:
                vx = direction[0] / d * 0.6
                vy = direction[1] / d * 0.6
            else:
                vx = kick_dir_norm[0] * 0.8
                vy = kick_dir_norm[1] * 0.8

            target_angle = math.atan2(kick_dir[1], kick_dir[0])
            yaw_diff = target_angle - self.yaw
            yaw_diff = math.atan2(math.sin(yaw_diff), math.cos(yaw_diff))
            vyaw = np.clip(yaw_diff * 2.0, -0.5, 0.5)

            self.set_velocity(vx, vy, vyaw)
            self._kicking = True
            self.action = "attack:kick"
        else:
            # 不在踢球范围：追球
            self.chase_ball(ball_pos)
            self.action = "attack:chase"

    def dribble(self, ball_pos, goal_pos):
        """带球推进：小力度推球"""
        my_pos = self.pos_2d
        ball_2d = np.array([ball_pos[0], ball_pos[1]])
        goal_2d = np.array([goal_pos[0], goal_pos[1]])
        dist_to_ball = np.linalg.norm(ball_2d - my_pos)
        dist_to_goal = np.linalg.norm(goal_2d - ball_2d)

        if dist_to_ball < P.DRIBBLE_ENTER_M and dist_to_goal > P.DRIBBLE_SHOOT_RANGE_M:
            # 带球：朝球门方向慢速推球
            direction = goal_2d - my_pos
            d = np.linalg.norm(direction)
            if d > 0.01:
                vx = direction[0] / d * P.DRIBBLE_MAX_SPEED
                vy = direction[1] / d * P.DRIBBLE_MAX_SPEED
            else:
                vx, vy = 0, 0
            self.set_velocity(vx, vy, 0)
            self._dribble_active = True
            self.action = "dribble"
            return True
        else:
            self._dribble_active = False
            return False

    def guard(self, ball_pos, own_goal):
        """守门：球远守门，球近拦截"""
        my_pos = self.pos_2d
        ball_2d = np.array([ball_pos[0], ball_pos[1]])
        goal_2d = np.array([own_goal[0], own_goal[1]])

        # 守门员位置：球门前 0.5m
        guard_pos = goal_2d + np.array([0.5, 0])  # 朝场地中心偏移

        # 如果球靠近球门，前出拦截
        ball_to_goal = np.linalg.norm(ball_2d - goal_2d)
        if ball_to_goal < 2.0:
            # 拦截：站在球和球门之间
            intercept = (ball_2d + goal_2d) / 2
            guard_pos = intercept

        direction = guard_pos - my_pos
        d = np.linalg.norm(direction)
        if d > 0.1:
            vx = direction[0] / d * 0.4
            vy = direction[1] / d * 0.4
        else:
            vx, vy = 0, 0

        # 面朝球
        ball_dir = ball_2d - my_pos
        target_angle = math.atan2(ball_dir[1], ball_dir[0])
        yaw_diff = target_angle - self.yaw
        yaw_diff = math.atan2(math.sin(yaw_diff), math.cos(yaw_diff))
        vyaw = np.clip(yaw_diff * 2.0, -0.5, 0.5)

        self.set_velocity(vx, vy, vyaw)
        self.action = "guard"

    def support(self, attacker_pos, ball_pos, own_goal):
        """支援：站在攻击者侧前方提供接应"""
        my_pos = self.pos_2d
        attacker_2d = np.array([attacker_pos[0], attacker_pos[1]])
        ball_2d = np.array([ball_pos[0], ball_pos[1]])
        own_goal_2d = np.array([own_goal[0], own_goal[1]])

        # 支援位置：攻击者侧前方 2m
        attack_dir = ball_2d - attacker_2d
        d = np.linalg.norm(attack_dir)
        if d > 0.01:
            attack_dir = attack_dir / d
        else:
            attack_dir = np.array([1.0, 0.0])

        # 侧向偏移
        perp = np.array([-attack_dir[1], attack_dir[0]])
        support_pos = attacker_2d + attack_dir * P.SUPPORT_FORWARD_M + perp * P.SUPPORT_WIDTH_M

        # 不要太靠近己方球门
        if np.linalg.norm(support_pos - own_goal_2d) < 2.0:
            support_pos = (support_pos + attacker_2d) / 2

        direction = support_pos - my_pos
        d = np.linalg.norm(direction)
        if d > 0.1:
            vx = direction[0] / d * 0.4
            vy = direction[1] / d * 0.4
        else:
            vx, vy = 0, 0

        # 面朝球
        ball_dir = ball_2d - my_pos
        target_angle = math.atan2(ball_dir[1], ball_dir[0])
        yaw_diff = target_angle - self.yaw
        yaw_diff = math.atan2(math.sin(yaw_diff), math.cos(yaw_diff))
        vyaw = np.clip(yaw_diff * 2.0, -0.5, 0.5)

        self.set_velocity(vx, vy, vyaw)
        self.action = "support"

    def defend(self, ball_pos, own_goal):
        """防守：站在球和己方球门之间"""
        my_pos = self.pos_2d
        ball_2d = np.array([ball_pos[0], ball_pos[1]])
        goal_2d = np.array([own_goal[0], own_goal[1]])

        # 防守位置：球和球门连线上，偏向球门
        defend_pos = (ball_2d + goal_2d * 2) / 3

        direction = defend_pos - my_pos
        d = np.linalg.norm(direction)
        if d > 0.1:
            vx = direction[0] / d * 0.4
            vy = direction[1] / d * 0.4
        else:
            vx, vy = 0, 0

        # 面朝球
        ball_dir = ball_2d - my_pos
        target_angle = math.atan2(ball_dir[1], ball_dir[0])
        yaw_diff = target_angle - self.yaw
        yaw_diff = math.atan2(math.sin(yaw_diff), math.cos(yaw_diff))
        vyaw = np.clip(yaw_diff * 2.0, -0.5, 0.5)

        self.set_velocity(vx, vy, vyaw)
        self.action = "defend"
