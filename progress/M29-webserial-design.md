# M29 · WebSerial 零安装接入设计（当前执行主线立项）

- **日期**：2026-08-06
- **完成了什么**：为「不装 2.9GB Agent 让人第一次让机械臂动起来」的执行定义完成技术立项：WebSerial 选型、架构决策、分步实施计划；建立 `docs/research-log.md` 研究日志；roadmap 新增 P0 主线章节。
- **解决了什么**：
  - 证明技术答案现成：Chrome/Edge 72% 覆盖 + 仓库内 `apps/realtime/dora-bambot` 快照已有完整浏览器 Feetech 驱动（baud 1e6、0x02/0x03/0x82、校验和 ~Σ&0xFF），无需从零发明协议。
  - 明确适用边界：仅 Feetech 总线（SO-101 主线）；Reachy/B601 不属本路径——守住「不吹跨机型」的内部共识红线。
  - 明确架构决策：浏览器直连串口绕过 realtime 服务器（零安装的兑现点）；3D 跟随用本地状态；Agent 路径保留并存。
- **关键命令 / 配置**：无代码改动（本轮纯设计）。参考实现：`apps/realtime/dora-bambot/_next/static/chunks/881-47c588f365fe1541.js`。
- **最终结果**：`docs/webserial-design.md`（设计全文）+ `docs/research-log.md`（研究依据）+ `docs/roadmap.md`（WebSerial P0 章节）。下一步 S1：`apps/web/src/lib/webserial.ts` 协议层移植。
