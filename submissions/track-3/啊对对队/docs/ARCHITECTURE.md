# Architecture / 架构

The runtime has one common action boundary and three ways to reach it. Genesis
provides physics, rendering, and the Panda MJCF. The project builds
`PolicyContext`, invokes a controller, validates `CartesianAction`, then steps
the simulator.

运行时只有一个动作边界和三条到达它的路径。Genesis 提供物理、渲染和 Panda MJCF；项目构建 `PolicyContext`，调用控制器，验证 `CartesianAction`，再推进仿真。

```text
RGB + state + task -> PolicyContext -> controller -> safety checks -> Genesis
```

1. `ScriptedPickPlaceExpert + ClosedLoopSupervisor` reads privileged state and
   produces the 8/10 video trajectories.
2. SmolVLA or PI0.5 produces learned actions or residuals. In hybrid use,
   Harness-Lite bounds candidates against Cartesian, force, IK, and tool limits.
3. Strict pure VLA gives the learned policy responsibility for all declared task
   actions; the recorded result is 0/3.

1. `ScriptedPickPlaceExpert + ClosedLoopSupervisor` 读取特权状态，产生 8/10 视频轨迹。
2. SmolVLA 或 PI0.5 产生学习动作或残差；混合使用时，Harness-Lite 按笛卡尔、力、IK 和工具边界限制候选动作。
3. 严格纯 VLA 由学习策略负责全部声明任务动作；记录结果为 0/3。

GPT-5.6 Luna/Codex Runtime belongs to development and review work, not this
runtime control diagram. The implementation entry points are
`src/parcel_sorter/genesis_env.py`, `src/parcel_sorter/runner.py`, and
`scripts/run_expert.py`.

## Concrete executable interfaces / 可执行接口

The exact Python policy contract is
`ActionPolicy.predict(context: PolicyContext) -> CartesianAction`.
`PolicyContext` contains the supervisor decision, `RobotState`, task text, and
optional RGB/depth frames. `CartesianAction` contains the target position,
target quaternion, gripper value, and command label; `GenesisParcelEnv.step`
is the simulator execution boundary for that action.

`scripts/run_demo.sh` fixes episode 0 and calls `scripts/run_expert.py`, so it
uses `ScriptedExpertPolicy` without a checkpoint. It is a scripted-agent
simulation demo and does not load a learned policy. The
separate `mobile_vla_service` is a local AF_UNIX persistent-policy service
with its own `mobile-pi05-persistent-policy-service-v1` protocol. It is not
used by the demo and is not a Codex Responses API or another cloud
robot-control API.
