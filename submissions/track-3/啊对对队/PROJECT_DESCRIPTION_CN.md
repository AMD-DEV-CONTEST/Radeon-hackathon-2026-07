# 项目说明

Parcel Sorter ROCm 在单张 AMD Radeon GPU 与 ROCm 7.2.1 上运行 Genesis
包裹抓取、抬升、搬运和放置任务。仓库测试了两种仿真机器人形态：固定单臂
Franka Panda 工作站，以及带两条 Panda 机械臂的全向轮式 Bi-Franka。

当前提交主线是 **Agent 条件化 + v21 PI0.5 VLA 抓取模式路由 + 脚本连续
运动**。受限 Responses Agent 只生成高层任务意图，微调后的 v21 模式头对抓取
类别投票，确定性控制器在工作空间、接触力、IK 和工具指令门限下执行连续动作。

三个交付混合回合都完成了抓取、抬升、0.531-0.554 米运输、支撑放置和释放，
放置误差为 11.5-25.0 毫米。v21 在每个回合中均以 3/3 票选择 `side_suction`，
三条轨迹都保留全景和左腕视频。公开演示见
[Bilibili](https://www.bilibili.com/video/BV1Qkun6qEKn/)。

结果归因保持透明：Agent 不发送低层动作；v21 连续动作处于 shadow 模式，实际
物理执行步数为零；连续运动由脚本控制器完成。因此三条成功属于 Agent+VLA
混合系统，不能写成纯 VLA。严格纯 VLA 结果仍为 0/3。

仓库提供源码、固定配置、数据生成与审计脚本、训练证据、双视角原始视频、模型
哈希和 Radeon 复现命令。完整 PI0.5 DROID 基座与 v21 LoRA adapter 通过
[Hugging Face](https://huggingface.co/L2658183739/agengt-vla) 单独发布。
