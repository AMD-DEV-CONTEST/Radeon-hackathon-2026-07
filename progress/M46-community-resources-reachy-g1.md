# M46 · 社区资源区块补齐：Reachy Mini + Unitree G1

- **日期**：2026-08-06
- **完成了什么**：CommunityResources 区块补齐最后两块——
  - `RobotReachyMini.tsx`：官方仓库（自带 docs/troubleshooting）+ HF SDK 文档 + Pollen Discord/论坛 + 5 条 FAQ（daemon 卡死 #623、Zenoh 7447 端口转发 #677、电机红灯插错槽、麦克风 FPC 排线、7V-5A 电源）。
  - `RobotPreview.tsx`：按 `runtimeId === 'unitree_g1'` 条件渲染（G1 是 Preview 壳页）——官方开发者文档 + sdk2 仓库 + GitHub Issues（**如实标注无公开 Discord**）+ 5 条 FAQ（EDU 版 SDK #43、固定 IP 网段、ClientStub #28、仿真/真机索引不一致、价格 $16k+）。
- **解决了什么**：至此 6 个 runtime（SO-101/B601/LeKiwi/Reachy/G1）全部有「文档 + 社区 + FAQ」三块社区资源，设计一致（同一组件），内容全部带来源。AmazingHand（Preview 灵巧手）社区无公开资料，如实跳过。
- **关键命令**：Reachy/G1 两页 tsc 严格检查干净；工作区 0 脏文件。
- **最终结果**：已提交。用户指令「所有 runtime 从用户/社区/设计角度丰富内容」的主体已完成——下一步转向功能改进（b 类）或设计一致性（M4 violet 语义）。
- **下一步**：M4 violet 语义统一（violet 同时是「引导/随机表演/空间遥操」三种语义）；或用户角度功能改进（如训练页 GPU 状态可视化）。
