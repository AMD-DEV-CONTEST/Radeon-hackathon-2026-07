"""Strategy — multi-robot 比赛策略主逻辑。

参考 Booster 官方基线 main.py，适配 Genesis + T1。
这是决策层：决定每个机器人做什么，然后调用 player 的动作方法。
"""

import math
import numpy as np
import torch
from enum import Enum
from . import param as P
from .player import Player


class Phase(Enum):
    """比赛阶段"""
    NORMAL = "normal"
    KICKOFF = "kickoff"
    STOPPED = "stopped"


class Team:
    """一队 3 个机器人"""

    def __init__(self, team_id, robot_indices, env):
        """
        team_id: 'left' 或 'right'
        robot_indices: [attacker_idx, defender_idx, goalkeeper_idx]
        """
        self.team_id = team_id
        self.env = env

        # 初始角色
        self.players = []
        for i, idx in enumerate(robot_indices):
            role = ['attacker', 'defender', 'goalkeeper'][i]
            p = Player(idx, team_id, role, env)
            self.players.append(p)

        self.attacker_idx = 0  # 当前追球者在 players 列表中的索引
        self.phase = Phase.NORMAL

        # 球门坐标
        if team_id == 'left':
            self.own_goal = np.array([-P.FIELD_LENGTH / 2, 0])
            self.opp_goal = np.array([P.FIELD_LENGTH / 2, 0])
            self.attack_dir = 1.0  # 进攻方向 +x
        else:
            self.own_goal = np.array([P.FIELD_LENGTH / 2, 0])
            self.opp_goal = np.array([-P.FIELD_LENGTH / 2, 0])
            self.attack_dir = -1.0  # 进攻方向 -x

    def get_ball_pos(self):
        return self.env.ball_pos[0].cpu().numpy()

    def get_ball_vel(self):
        return self.env.ball_vel[0].cpu().numpy()

    def select_attacker(self, ball_pos):
        """选离球最近的人追球（参考 Booster _select_closest_attacker）"""
        ball_2d = np.array([ball_pos[0], ball_pos[1]])
        distances = []
        for i, p in enumerate(self.players):
            if p.is_fallen:
                distances.append(float('inf') + P.FALLEN_COST_M)
            else:
                d = np.linalg.norm(p.pos_2d - ball_2d) + P.FALLEN_COST_M * p.is_fallen
                distances.append(d)

        best = int(np.argmin(distances))

        # 防震荡：如果当前追球者距离跟最近者差不多，保持不变
        current = self.attacker_idx
        if current != best:
            if distances[current] <= distances[best] + P.ATTACKER_KEEP_MARGIN_M:
                best = current

        self.attacker_idx = best
        # 更新角色
        for i, p in enumerate(self.players):
            if i == best:
                p.role = 'attacker'
            elif p.role == 'attacker':
                p.role = 'defender'  # 之前的追球者变防守
        return best

    def update_roles(self, ball_pos):
        """根据球的位置动态分配角色"""
        self.select_attacker(ball_pos)

    def act(self):
        """主决策：根据当前状态决定每个机器人的动作"""
        ball_pos = self.get_ball_pos()

        if self.phase == Phase.STOPPED:
            for p in self.players:
                p.stop()
            return

        # 选追球者
        self.update_roles(ball_pos)

        attacker = self.players[self.attacker_idx]
        others = [self.players[i] for i in range(len(self.players)) if i != self.attacker_idx]

        # 追球者：进攻
        if not attacker.is_fallen:
            attacker.attack(ball_pos, self.opp_goal)

        # 其他人：一个守门，一个支援
        if len(others) >= 1:
            # 离己方球门最近的当守门员
            guard = min(others, key=lambda p: np.linalg.norm(p.pos_2d - self.own_goal[:2]))
            if not guard.is_fallen:
                guard.guard(ball_pos, self.own_goal)

        if len(others) >= 2:
            support = [p for p in others if p is not guard][0]
            if not support.is_fallen:
                support.support(attacker.pos, ball_pos, self.own_goal)


class Match:
    """multi-robot 比赛控制器"""

    def __init__(self, env):
        self.env = env

        # 两队各 3 个机器人
        self.left_team = Team('left', [0, 1, 2], env)
        self.right_team = Team('right', [3, 4, 5], env)

        self.phase = Phase.NORMAL
        self.score = {'left': 0, 'right': 0}
        self.steps = 0

    def act(self):
        """每步调用：两队分别决策"""
        ball_pos = self.left_team.get_ball_pos()

        # 两队分别执行策略
        self.left_team.act()
        self.right_team.act()

        # 收集所有 6 个机器人的速度指令
        commands = []
        for team in [self.left_team, self.right_team]:
            for p in team.players:
                commands.append(p.get_velocity_cmd())

        # 转成 tensor 传给 env
        action_tensor = torch.as_tensor(
            np.asarray(commands),
            dtype=self.env.hl_actions.dtype,
            device=self.env.device
        ).reshape(1, 6, 3)

        return action_tensor

    def check_events(self, extras):
        """检查进球/跌倒等事件"""
        kicks = 0
        scored = False
        if isinstance(extras, dict):
            kick_array = extras.get("kick_events")
            if kick_array is not None:
                ka = np.asarray(kick_array).reshape(-1)
                kicks = int(sum(1 for v in ka[:6] if bool(v)))

            terminal = extras.get("terminal_state", {})
            if self._safe_bool(terminal.get("scored_left")):
                self.score['left'] += 1
                scored = True
            if self._safe_bool(terminal.get("scored_right")):
                self.score['right'] += 1
                scored = True

        return kicks, scored

    def _safe_bool(self, val):
        if val is None: return False
        if hasattr(val, 'item'): return bool(val.item())
        if hasattr(val, 'detach'): return bool(val.detach().cpu().numpy().any())
        return bool(val)

    def get_robot_stats(self):
        """返回所有机器人的状态摘要"""
        stats = []
        for team in [self.left_team, self.right_team]:
            for p in team.players:
                stats.append({
                    'team': team.team_id,
                    'role': p.role,
                    'action': p.action,
                    'pos': p.pos.tolist(),
                    'height': float(p.height),
                    'fallen': bool(p.is_fallen),
                })
        return stats
