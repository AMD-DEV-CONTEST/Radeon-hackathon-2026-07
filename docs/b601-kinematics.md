# B601-RS 运动学与重力补偿

BotverseX 通过 Pinocchio + `reBotArm_control_py` 为 B601-RS 提供 FK/IK、笛卡尔移动和重力补偿，与 LeRobot 遥操/录制**互斥**（`runtime_lock`）。

## 安装

```bash
bash scripts/b601_pinocchio_install.sh
```

安装后重启 Local Agent。健康检查：`GET /api/b601/kinematics/health`

## 坐标系

- 基座：`base_link`（与 URDF / Seeed wiki 一致）
- 末端：`gripper_end`

## API

| 端点 | 说明 |
|------|------|
| `POST /api/b601/kinematics/fk` | 关节角 → 末端位姿 |
| `POST /api/b601/kinematics/ik` | 目标位姿 → 关节角 |
| `GET /api/b601/kinematics/ee_pose` | 当前末端位姿 |
| `POST /api/b601/kinematics/move_pose` | IK + 实机运动（默认 `dry_run=true`） |
| `POST /api/b601/kinematics/move_joints` | 关节空间运动 |
| `WS /api/b601/kinematics/ws/ee_pose` | 20Hz 末端位姿流 |

## IK 失败排查

1. 目标点是否在工作空间内（参考 Ready Pose: 约 0.31, 0.02, 0.33 m）
2. 旧版 Ready Pose (0.3, 0, 0.3, pitch=0.7) 对本 URDF 不可达 — UI 已改用 FK 验证过的预设
2. 姿态是否导致腕部奇异
3. 关节限位 — API 会在超限时报错
4. Pinocchio 未安装 → 运行安装脚本

## 重力补偿

- `POST /api/b601/gravity_comp/start` — `mode: basic|lock`，可选 `joint_gains`
- `POST /api/b601/gravity_comp/stop` — **必须先点停止**，会 safe_home + disable

**安全**：停止脚本时电机会失能，臂可能下落 — 停止前请扶住机械臂。

参考 Seeed wiki：`9_gravity_compensation.py`、`10_gravity_compensation_lock.py`
