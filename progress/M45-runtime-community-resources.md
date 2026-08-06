# M45 · 全 runtime 社区资源区块（用户/社区/设计三角度，打样+三页落地）

- **日期**：2026-08-06
- **背景**：用户指令——所有 runtime 从用户角度/开源社区角度/设计角度丰富内容，不过度复杂；无真机，硬件轮暂停；社区研究入循环。Loop 已更新为 v2（任务 49343c99）。
- **完成了什么**：
  1. **社区调研**（子代理 WebSearch）：SO-101/Reachy/B601/LeKiwi/Unitree G1 五机型的官方文档、社区入口、新手高频问题（含 issue 编号来源），入 research-log。
  2. **打样组件** `components/features/CommunityResources.tsx`：文档链接 + 社区入口 + FAQ（details 折叠）三块，props 驱动，全 runtime 共用；设计上贴合品牌（--ember 链接、深色卡片、无 emoji、无多余动效）。
  3. **三页落地**：RobotSO101（FAQ 含 ID 唯一化 #1244 / 12V 过压 #1010 / 固件 3.10 / chmod 666）、RobotB601（禁重写电机 ID / RS 支持未完整 / CAN 配置 / ID 映射 / 禁热插拔）、RobotLeKiwi（ZMQ 鉴权 #890 / 瞬态读错误 PR #4207 / 校准前配 ID #1042 / ROS2 版本组合）。
- **解决了什么**：runtime 页从「只有操作面板」变成「操作 + 社区入口 + 高频问题自解」，用户卡住时不再只能发客服消息；FAQ 全部带社区来源，诚实不编造（G1 无公开 Discord 就写 GitHub Issues）。
- **关键命令**：三页 + 组件 tsc 严格检查干净（B601 页 3 个 noUnusedLocals 为历史遗留，stash 基线验证非本轮引入）。
- **最终结果**：已提交。Reachy/G1/AmazingHand 待补（下轮）；链接维护（Discord 邀请会过期）计入 roadmap。
- **下一步**：Reachy Mini 页补社区区块（数据已调研好）；或 M4 violet 语义统一。
