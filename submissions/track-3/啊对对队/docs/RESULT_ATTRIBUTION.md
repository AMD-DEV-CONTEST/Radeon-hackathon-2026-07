# Result Attribution / 结果归因

| Result | Controller | How it is obtained | Claim |
| --- | --- | --- | --- |
| Three delivered long-distance episodes | Bounded Agent task conditioning + v21 PI0.5 3-vote grasp-mode routing + deterministic continuous motion | Agent chooses goal/mode/recovery intent; v21 selects `side_suction` 3/3; scripted control completes 0.531-0.554 m transport under safety gates. | Hybrid simulation result only. Not pure VLA, direct LLM control, hardware, or Sim-to-Real. |
| 8/10 successful trajectories | Deterministic scripted controller (`ScriptedPickPlaceExpert` + `ClosedLoopSupervisor`) | Runs 10 fixed-seed Genesis episodes using privileged simulator state. An episode is successful only when the supervisor reaches `Stage.COMPLETE`; only records with `_result.json` `success=true` enter the demo. | Scripted-controller demonstration provenance only. Not VLA or LLM-agent success. |
| 0/3 | Strict pure VLA | Learned policy supplies the declared task actions in closed loop without expert completion. | Not passed. |
| 0/42, 42/42, 42/42 | Raw VLA, safety-clipped VLA, Harness-Lite offline action-envelope checks | Replays 42 action-contract samples through offline validity gates. | Offline ablation only. Not task-success evidence. |

The [public Bilibili video](https://www.bilibili.com/video/BV1Qkun6qEKn/)
presents the hybrid route. In these clips, the Agent emits no low-level action,
v21 continuous actions are shadowed, and scripted control owns motion.

| 结果 | 控制器 | 结果如何得到 | 可主张内容 |
| --- | --- | --- | --- |
| 3 个长距离交付回合 | 受限 Agent 任务条件 + v21 PI0.5 三票抓取模式路由 + 确定性连续运动 | Agent 选择目标、模式和恢复意图；v21 以 3/3 票选择侧吸；脚本控制在安全门下完成 0.531-0.554 米运输。 | 仅为混合仿真结果，不是纯 VLA、LLM 直接控制、真机或 Sim-to-Real。 |
| 8/10 条成功轨迹 | 确定性脚本控制器（`ScriptedPickPlaceExpert` + `ClosedLoopSupervisor`） | 使用仿真特权状态运行 10 个固定种子的 Genesis 回合。只有监督器到达 `Stage.COMPLETE` 且 `_result.json` 为 `success=true` 的回合才进入演示视频。 | 仅证明脚本控制器的示范来源，不是 VLA 或大模型 Agent 成功率。 |
| 0/3 | 严格纯 VLA | 学习策略在没有专家补全的情况下提供闭环任务动作。 | 未通过。 |
| 0/42、42/42、42/42 | Raw VLA、Safety-clipped VLA、Harness-Lite 离线动作包络检查 | 42 个动作合约样本的离线有效性门测试。 | 仅为离线消融，不是任务成功率。 |

[Bilibili 公开视频](https://www.bilibili.com/video/BV1Qkun6qEKn/) 展示混合路线。
视频中 Agent 不发送低层动作，v21 连续动作处于 shadow，连续运动由脚本控制器负责。
