# M27 — B601-RS 原生接入 BotverseX

## 问题

B601 官方流程依赖 CAN 配置、MotorBridge、LeRobot CLI，用户需大量终端操作；与 BotverseX「点点点」定位不符。

## 决策

- **底层**：100% 跟 Seeed 官方开源栈（spawn 官方 CLI，参数同 Wiki）
- **上层**：BotverseX 薄包装 — 安装器 + `/api/b601/*` + 双形态 UI + Copilot
- **UX**：首用向导 + 工作台平级 Tab；日常 M26 Stage + Tab + 高级抽屉
- **3D**：静态 URDF + 遥操时 motorbridge 只读轮询跟手（非 SO-101 `/ws/ui` 栈）

## 实施

| Phase | 交付物 |
|-------|--------|
| P1 | `scripts/install-botversex-agent.sh` + URDF 资产同步 |
| P2 | `robots.json` b601_rs + `runtimes/b601_rs/` + `api/b601.py` |
| P3 | `RobotB601.tsx` + `components/b601/*` |
| P4 | Playbook + Copilot action + site knowledge |
| P5 | `skills_seed` b601_rs + inference/calibrate/joints 端点 |
| P6 | 官方 URDF/STL 入库 + `waitForMeshes` 渲染修复 + `b601-smoke.sh` |

## 验收

- [x] `apps/realtime/static/urdf/b601_rs/` 含 30 个 STL + URDF（git 入库）
- [x] dev 用 `python run_api.py --http`；URDF/mesh 200
- [x] `/robots/b601_rs` 新手上手 / 工作台平级；停止遥操「卸力中」UX
- [x] `POST /api/b601/calibrate/start` + 高级抽屉校准
- [x] 录数 Tab episode 进度 + inference stop
- [x] `GET /api/b601/joints` 遥操时 URDF 跟手
- [x] 训练页 `?runtime=b601_rs` 预填；部署 Tab 列最近 job
- [x] `scripts/b601-smoke.sh` + docs 更新

## 不在范围（M28+）

深度相机抓取、ROS2/MoveIt2、B601-DM、双臂 bimanual
