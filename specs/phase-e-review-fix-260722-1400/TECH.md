# Tech: 阶段 E 复核修复

- Level: S2
- Status: verified

## 实现

- `ControlledRunner` 增加可选 `cancel_check`；每个步骤开始前读取最新的持久化取消信号。
- `app.services.runs._background_execute()` 使用 `asyncio.to_thread()` 执行同步管道，并在进度持久化时保留并发写入的 `cancel_requested`。
- `POST /api/projects/{project_id}/runs/{run_id}/execute` 的成功状态码为 `202`。
- MIME 检测先检查内容签名（PDF、ZIP 文档），再尝试 UTF-8 文本，最后才使用扩展名推断；不匹配直接报错。
- 病毒扫描子进程以 bytes 传入标准输入，避免 `text=True` 与二进制内容冲突。
- Gradio 工作台最多轮询 180 秒，仅在 `completed` 时读取 `result` 工件。

## 风险与回滚

协作式取消不能打断当前步骤内的模型请求；模型调用超时仍由 LLM 客户端配置控制。回滚可撤销本 spec 对应提交。
