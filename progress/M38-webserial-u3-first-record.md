# M38 · U3 3 秒首录闭环（WebSerial 录制 → 第一条 dataset）

- **日期**：2026-08-06
- **完成了什么**：
  - 后端：`apps/realtime/api/datasets.py` 新增 `POST /api/datasets/record` —— 接收浏览器录制的关节轨迹 JSON，落盘为 `apps/realtime/datasets/recording_<id>/`（**LeRobot 风格 parquet**：index/episode_index/frame_index/timestamp/observation.state/action + **botclaw.json** v0.2 元数据，source=webserial_record）。
  - 前端：`BrowserDirectPanel` 庆祝横幅的「把这段存成我的第一条数据」从占位提示变为**真录制**：3 秒、20Hz 采样在线关节位置 → POST 入库 → 成功提示 + 「去实验室看」链接。
- **解决了什么**：
  - 「数据闭环入口」叙事从口号变证据的第一步：浏览器 → 真实关节轨迹 → 第一条 dataset，全程不装 Python。
  - 现有 `GET /api/datasets` 扫描逻辑**零改动**即识别新数据集（用 `_summarize` 验证：列表可见、帧数/parquet 正确）——复用存量索引，不发明新数据格式。
  - 诚实标注：action 以 state 记录（浏览器直录无主从动作差），相机/任务/多集完整对齐在 S5。
- **关键命令**：
  - `python3 -m py_compile apps/realtime/api/datasets.py` → OK
  - 功能测试（临时目录 + 直接调用端点 + `_summarize` 回读）→ 3 帧 0.1s，列表可见 ✓
  - 前端 tsc（BrowserDirectPanel.tsx）→ 零错误
- **最终结果**：已提交。真机 3 秒录制（Chrome + SO-101 USB）待硬件验收。
- **下一步**：U4 串口诊断页（端口枚举/波特率探测/日志导出——第一个真用户的第一个故障点），或真机验收轮（S2-S3 + U3 全链路真机走一遍）。
