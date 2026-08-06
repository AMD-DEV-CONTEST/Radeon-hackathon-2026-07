# GraphVoice Agent Design Document

## 1. 角色定义
- **主 Agent**: 通过自然语言理解用户意图，协调多个工具完成图数据库查询。
- **工具（Tools）**：
  - `cypher_generator`: 接收用户问句 + 上下文，返回 Cypher 查询
  - `db_executor`: 接收 Cypher，执行并返回结果（只读）
  - `result_interpreter`: 接收查询结果，转成友好自然语言

## 2. 工作流（LangGraph 状态机）
- **State**:
  - messages: 对话历史
  - current_query: 原始语音转录文本
  - cypher: 生成的查询
  - db_result: 原始结果
  - final_answer: 自然语言回复
- **Nodes**:
  1. `parse_intent`: 判断是否需要查询数据库（若为闲聊则直接回复）
  2. `generate_cypher`: 调用 `cypher_generator`
  3. `execute_db`: 调用 `db_executor`
  4. `interpret_result`: 调用 `result_interpreter`
  5. `respond`: 合成最终回复（文本 -> TTS）

## 3. 工具详细说明
### cypher_generator
- **输入**: user_query, db_schema, conversation_history
- **输出**: cypher_query (string)
- **实现**: 通过 LLM（Qwen / Hunyuan）的 Function Calling 或显式 Prompt 生成
- **安全**: 强制只读（只允许 MATCH / RETURN），禁止写操作

### db_executor
- **输入**: cypher_query
- **输出**: json 格式结果
- **异常处理**: 查询超时、语法错误返回友好提示

### result_interpreter
- **输入**: db_result, user_query
- **输出**: 中文自然语言摘要（适合语音输出）

## 4. 对话上下文管理
- 使用 `messages` 列表保留最近 N 轮（可配置），用于多轮对话中的指代消解（如“它的朋友呢？”）

## 5. 性能 SLA
- 语音首字延迟目标 < 1s（本地 VAD + 云端 API 往返需优化）
- 查询生成 + 执行 + 解释总耗时 < 5s（可接受）

## 6. 错误降级策略
- 若 Cypher 生成失败 → 提示“无法理解，请重试”
- 若数据库超时 → 返回“查询较慢，稍后重试”
- 若 API 配额用完 → 切换到本地备用模型（如果有）

## 7. 扩展计划
- 未来可增加多轮对话、主动建议、可视化返回等。
