# v21 Agent + VLA Hybrid Results / v21 Agent + VLA 混合结果

## Result / 结果

Three delivered simulation episodes completed pick, lift, long-distance transport, supported placement, and release. Every episode saved both a full-workspace video and a synchronized left-wrist video.

三个交付仿真回合都完成了抓取、抬升、长距离运输、支撑放置和释放。每个回合都保存了全景视频与同步左腕视频。

| Episode | Transport distance | Placement error | v21 route vote | Result |
| --- | ---: | ---: | ---: | --- |
| session-02 candidate-05 | 0.554 m | 24.2 mm | side 3/3 | success |
| session-00 candidate-03 | 0.546 m | 11.5 mm | side 3/3 | success |
| session-01 candidate-08 | 0.531 m | 25.0 mm | side 3/3 | success |

The first gate passed 1/1. A subsequent three-context batch passed 2/3; the failed context was excluded from delivery. Another candidate was rejected before actuation because the VLA selected `top_suction` while the Agent directive required `side_suction`. Rejected episodes are not presented as successful videos.

首个门禁为 1/1；随后三个上下文的批次为 2/3，失败回合没有进入交付。另一个候选在动作执行前被拒绝，因为 VLA 选择了 `top_suction`，而 Agent 指令要求 `side_suction`。这些被拒绝回合没有作为成功视频展示。

## Controller attribution / 控制归因

The correct name is **Agent-conditioned, VLA-routed, scripted-motion hybrid**.

正确名称是 **Agent 条件化 + VLA 模式路由 + 脚本连续运动混合系统**。

1. The Responses Agent receives a structured task observation once before the rollout. It may choose a goal, grasp family, and recovery strategy only.
2. The v21 PI0.5 supervised mode head receives four RGB-D views, a 68-D state, and task text. It votes three times and routes the grasp family only after consensus.
3. The deterministic controller executes pregrasp, suction, lift, transport, placement, and release under force and workspace gates.
4. The VLA runs in `shadow` for continuous actions, so `applied_physics_steps=0`. These episodes are not pure-VLA action rollouts.

1. Responses Agent 在回合开始前读取一次结构化任务观测，只能选择目标、抓取类别和恢复策略。
2. v21 PI0.5 监督模式头读取四路 RGB-D、68 维状态和任务文本，连续投票三次，一致后才决定抓取类别。
3. 确定性控制器在力与工作空间门限下执行预抓取、吸附、抬升、运输、放置和释放。
4. VLA 连续动作处于 `shadow`，因此 `applied_physics_steps=0`；这些回合不是纯 VLA 动作闭环。

## Agent model and API / Agent 模型与 API

The configured primary model was `gpt-5.6-luna`, called through an OpenAI-compatible Responses endpoint with response storage disabled. The gateway returned no valid Luna response during this run, so the client used the declared `gpt-5.5` fallback. The raw trace records `requested_model`, `actual_model`, and `fallback_used`; the repository stores no API key.

配置的首选模型是 `gpt-5.6-luna`，通过兼容 OpenAI Responses 的端点调用，并关闭响应存储。本次运行中网关未返回有效 Luna 响应，因此客户端使用声明的 `gpt-5.5` 回退模型。原始 trace 明确记录 `requested_model`、`actual_model` 和 `fallback_used`；仓库不保存 API Key。

Relevant files:

- `src/parcel_sorter/responses_task_agent.py`: fail-closed Responses client and strict JSON schema.
- `src/parcel_sorter/harness_task_bridge.py`: validated high-level directive to PI0.5 task conditioning.
- `scripts/plan_mobile_pi05_episode_with_agent.py`: one audited Agent planning call.
- `scripts/build_agent_conditioned_demo_config.py`: binds the plan to frozen episode contexts.
- `scripts/collect_mobile_suction_dataset_rocm.py`: requires a matching VLA route and records dual-view media.
- `configs/mobile_pi05_v21_luna_agent_v1.json`: credential-free runtime configuration.

## Claim boundary / 结论边界

This result demonstrates that an Agent can condition a task and a fine-tuned v21 VLA can route a grasp mode that is then executed by a stable controller. It does not demonstrate that GPT controls the arm, that v21 generates successful continuous robot actions, or that strict pure VLA has passed. The previously recorded strict pure-VLA result remains 0/3.

本结果证明：Agent 可以生成受限任务条件，微调后的 v21 VLA 可以选择抓取模式，再由稳定控制器执行。它不能证明 GPT 直接控制机械臂，也不能证明 v21 已经生成成功的连续机器人动作，更不能改写严格纯 VLA 的 0/3 结果。
