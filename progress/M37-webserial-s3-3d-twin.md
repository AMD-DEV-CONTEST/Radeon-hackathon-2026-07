# M37 · WebSerial S3：3D 孪生跟动接入第一动作仪式

- **日期**：2026-08-06
- **完成了什么**：`components/so101/BrowserDirectPanel.tsx` 接入 `UrdfViewer` 3D 孪生——滑条 / 挥手序列的 goal 值实时驱动 SO-101 URDF（count→rad 转换，`jointSmoothing` 平滑）；断开时孪生复位到初始姿态。
- **解决了什么**：
  - 「第一次挥手」现在有完整的可视化闭环：授权 → 扫描 → 挥手，真机与 3D 同时动（M31 brief U1 的 ② 3D 孪生同步立起要素补齐）。
  - 关键巧合：SO-101 URDF（dora-bambot）的关节名就是电机 ID（"1".."6"），STS3215 电机 ID ↔ URDF 关节天然对齐，无需命名映射表。
  - 诚实边界：孪生是**视觉跟动**（零点/方向以真机标定为准，`COUNT_TO_RAD=0.088°/count`），不是标定级控制——代码注释写明。
- **关键命令**：`npx tsc --noEmit --strict ... src/components/so101/BrowserDirectPanel.tsx` → 零错误。
- **最终结果**：已提交。真机验收（Chrome + SO-101 USB 实际挥手 + 3D 同步）待硬件。
- **下一步**：U3 3 秒首录闭环（WebSerial 录制 → 第一条 dataset，数据闭环叙事证据）或 U4 诊断页。
