# AlphaNoah Implementation Gap Analysis

更新时间：2026-07-23

## 阶段切换时的仓库实况

建设开始前，仓库只有 Python 包目录占位、架构文档和环境审计文档：

- `src/alphanoah_a1/` 各目录只有 `.gitkeep`；
- `tests/` 没有测试；
- `pyproject.toml` 的 `dependencies=[]`；
- 没有 Event、Decision、DecisionHook、状态机或数据库实现；
- 没有可运行演示命令；
- 现有包装设备、二维码、机器人和框架内容均为设计稿。

## 本轮选择

第一个验证场景：**合成餐饮冷藏温度 SOP 异常整改闭环**。

选择理由：

- 能以结构化输入完成确定性、可复现演示；
- 能自然展示异常判断、人工确认、任务、证据和复查；
- 不需要引入外部图片、模型、框架或真实 SOP；
- 可在后续把规则分析替换为 AMD 本地模型，而不改变业务状态机。

该场景是 **First validation skill**，不是 AlphaNoah 的产品范围。产品定位是工业现场 Agent：通过二维码降低传统工厂员工反馈问题的门槛，让 AI 辅助分析异常，并连接负责人完成处理闭环。

包装设备运维、质量巡检、安全巡检、二维码、视觉模型、机器人和企业知识库均不在 v0.1 中并行建设。

## 建设后的差距

| 优先级 | 项目 | 当前状态 | 说明 |
|---|---|---|---|
| P0 | 八个核心对象 | Implemented | 标准库 dataclass 和枚举 |
| P0 | DecisionHook | Implemented | 分析后路由及人工结果后二次路由 |
| P0 | 显式状态机 | Implemented | 非法转换拒绝并审计 |
| P0 | SQLite 持久化 | Implemented | 重启恢复、trace 查询、一键重置 |
| P0 | 演示 Skill | Implemented | 合成冷藏温度阈值规则 |
| P0 | 正常/异常测试 | Implemented | 八类自动化测试 |
| P0 | 端到端演示 | Implemented | CLI 明确记录人工 approve/reject |
| P1 | 简单 CLI | Implemented | 运行演示，并只读列出 Event、查看 Event 和 trace 时间线 |
| P1 | 本机 Web 申报表单 | Implemented | 标准库 `http.server`；无列表、审批页面或上传 |
| P1 | 物理手机扫码访问 | Not implemented | 当前只绑定 `127.0.0.1` |
| P1 | 可视化历史时间线 | Partially implemented | CLI 文本时间线已实现 |
| P2 | Ollama Analysis Provider | Implemented and directly verified | 显式 CLI 路径；Task 03B 记录一次 AMD Linux 实机分析 |
| P2 | AMD GPU 指标 | Partially implemented | 只有单次推理前后快照，不是持续采样或 benchmark |
| P2 | 结构化模型输出 | Implemented and directly verified | 严格 validation；Task 03B 一次真实模型输出通过 |
| P2 | 图片输入 | Future work | 当前只用结构化合成事件 |

## 保留、修改和暂停

| 处理 | 模块 | 理由 |
|---|---|---|
| 保留 | 显式状态机、人工确认、SQLite、审计链 | 已实现并直接服务闭环 |
| 保留 | 环境审计 | 作为历史证据，不继续扩散 |
| 修改 | 旧设备运维文档 | 保留为架构扩展，不再代表唯一演示场景 |
| 修改 | HoloAgent/LangChain/LangGraph 状态 | Reference only / adoption-triggered review |
| 暂停 | 物理手机访问、完整 Memory Engine、机器人、多 Agent、RAG | 不影响当前闭环 |
| 已完成单次验收 | Ollama/ROCm 接入 | Task 03B AMD Linux 结构化分析记录；不等于 benchmark |

## 当前能力边界

Windows 侧证明标准库闭环和 42 项测试可运行；Task 03B 另记录一次 AMD
Linux 本地模型集成。本轮仍不证明：

- 单次 GPU 快照足以构成性能 benchmark 或排他性因果证明；
- 图像识别已经实现；
- 合成阈值是现实食品安全标准；
- 当前系统适合生产环境；
- 外部 Agent 框架已成为依赖。
- Food SOP 已成为 AlphaNoah 的产品范围。
