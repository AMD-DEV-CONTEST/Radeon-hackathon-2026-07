# Future Evolution

## 当前基线

当前基线是领域无关 Core Runtime + 标准库 Python + SQLite + 单一规则验证 Skill + CLI。Food SOP 是 **First validation skill**，不是产品范围。任何扩展必须保持：

- Event/Decision/Task/Evidence/Review 的稳定 ID；
- 显式状态转换；
- 人工确认不可伪造；
- 每次状态变化可审计；
- 合成与真实数据边界清楚。

## 下一层扩展顺序

### 1. 工业现场入口与领域适配

Designed only：

- 用二维码建立现场对象或位置的稳定引用；
- 用最小适配器把员工反馈规范化为现有 Event；
- 先选一个工业 Skill 做验证，不并行扩展多个行业；
- 不复制 Event、Task 或 AuditRecord 模型。

### 2. AMD 原型机专项接入

Designed only：

- 在已审计 AMD/ROCm 原型机运行当前闭环；
- 实现最小 `LocalModelProvider`；
- 用固定 Ollama/model digest 输出 AnalysisResult；
- 保留规则 fallback，但不把 Mock 当 GPU 结果；
- 保存真实命令、版本和同步指标。

### 3. 演示体验

Designed only：

- 本地单页 UI；
- 人工 approve/reject/revise；
- 任务和证据表单；
- trace timeline；
- 明确错误提示。

### 4. 可选图片输入

Future work：

- 只在图片来源和许可证明确后加入；
- VLM 输出必须经过现有 Skill schema；
- 图片判断不能绕过 DecisionHook 和人工确认。

## 暂停项

- 多 Agent 和 AgentScope；
- 完整 LangGraph 重构；
- 完整 RAG；
- Skill 市场与自动生成；
- 多行业并行演示；
- 多租户；
- 机器人控制。

## 第三方采用原则

第三方组件只有在即将进入代码、运行、分发或媒体资产时才做针对具体版本的专项审计。仅思想参考时保留引用和边界。

## 状态

| 分类 | 内容 |
|---|---|
| Implemented | 可扩展的领域对象、Skill/Provider 边界和审计链 |
| Partially implemented | 结构化输出接口、CLI |
| Designed only | AMD Provider、UI、图片输入 |
| Future work | 平台化、机器人和生态能力 |
