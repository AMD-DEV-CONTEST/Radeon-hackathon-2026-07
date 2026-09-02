StagePoster Job Lifecycle v1.0

目标：定义异步任务状态、进度、持久化、取消、重试和恢复MVP：单个 Go 后端进程 + SQLite + 有界内存队列 + 私有 ComfyUI

1. 为什么必须异步

一次海报生成可能包括：

Brief 校验

风格规划

Workflow 选择

素材预处理

上传 ComfyUI 输入

等待 GPU 队列

模型生成

获取输出

Logo 和文字排版

生成预览

持久化结果

创建任务接口应立即返回 job_id，不能长时间保持 HTTP 连接。

2. 顶层状态

状态

含义

是否终态

queued

等待执行

否

running

正在执行

否

cancelling

正在取消

否

completed

已完成

是

failed

已失败

是

cancelled

已取消

是

详细执行步骤由 stage 表示。

3. Stage

queued
  ↓
planning
  ↓
preparing_assets
  ↓
submitting
  ↓
waiting_for_engine
  ↓
generating
  ↓
retrieving_outputs
  ↓
compositing
  ↓
finalizing
  ↓
completed

建议进度：

Stage

进度

queued

0

planning

1 至 10

preparing_assets

11 至 25

submitting

26 至 30

waiting_for_engine

31 至 35

generating

36 至 80

retrieving_outputs

81 至 87

compositing

88 至 95

finalizing

96 至 99

completed

100

进度是近似值。

前端应优先展示 Stage 文案，而不是把百分比当成精确模型进度。

4. 状态转换

允许：

queued → running
queued → cancelled
queued → failed

running → running
running → cancelling
running → completed
running → failed

cancelling → cancelled
cancelling → completed
cancelling → failed

禁止：

completed → running
failed → running
cancelled → running

重试必须创建新 Job。

5. 创建任务顺序

后端按以下顺序执行：

校验访问权限和限流。

校验 Project。

校验 Creative Brief。

校验 Asset。

校验风格和 Workflow 能力。

检查 Idempotency-Key。

保存 Brief 快照。

在 SQLite 创建 queued Job。

提交数据库事务。

将 Job 放入内存队列。

返回 202 Accepted。

不能先放队列再写 SQLite。

6. 幂等

创建任务必须携带：

Idempotency-Key

规则：

相同 Key、相同 Project、相同 Body，返回原 Job。

相同 Key、不同 Body，返回 IDEMPOTENCY_CONFLICT。

Key 有保留期限。

用户明确点击“再次生成”时使用新 Key。

避免：

双击生成

浏览器自动重试

网络断线导致重复任务

同一素材重复占用 GPU

7. 队列设计

黑客松 MVP 推荐：

有界内存队列

SQLite 持久化任务状态

一个后端进程

默认一个 GPU Worker

FIFO

最大队列长度可配置

可选独立后处理 Worker

不建议 MVP 上 Redis。

原因：

当前只有一台 GPU 服务器。

SQLite 已经负责持久状态。

ComfyUI 自己也有内部执行队列。

Redis 会增加部署和故障点。

黑客松优先保证可运行性。

StagePoster Queue 是产品级队列。

ComfyUI Queue 是推理引擎内部队列。

两者不能混为一谈。

8. SQLite 持久化

要求：

开启 WAL。

使用短事务。

数据库放服务器本地磁盘。

不共享 SQLite 文件。

只运行一个后端实例。

每次状态变化都写入数据库。

保存 Job Event。

建议 Job 字段：

id
project_id
status
stage
progress
message
brief_snapshot_json
plan_snapshot_json
workflow_id
workflow_version
comfy_prompt_id
attempt
retry_of
error_code
error_detail
created_at
queued_at
started_at
completed_at
updated_at
cancel_requested_at

9. 重启恢复

后端启动时：

查询非终态任务。

检查是否存在 comfy_prompt_id。

尝试查询 ComfyUI Queue 或 History。

能恢复则同步状态。

无法恢复则标记 JOB_INTERRUPTED。

保留 Brief 和 Plan。

允许用户重试。

MVP 可以不自动续跑，但不能让任务永远停在 running。

10. ComfyUI 执行映射

内部过程：

Worker
  ↓
加载 API Workflow
  ↓
注入 Prompt 和素材
  ↓
上传或映射输入图片
  ↓
提交 Workflow
  ↓
保存 prompt_id
  ↓
监听 WebSocket
  ↓
查询 History
  ↓
获取输出文件

ComfyUI 的节点进度需要转换成 StagePoster 的 Stage。

不能把原始 WebSocket 消息直接转发给前端。

WebSocket 断开时，应优先通过 History 和 Queue 查询恢复。

11. 前端轮询

推荐：

前 10 秒每秒一次。

之后每两秒一次。

网络错误使用退避。

页面刷新后恢复。

网络查询失败不能新建 Job。

到达终态后停止。

选择轮询的原因：

实现简单

容易调试

适合 Tunnel

不需要维护额外长连接

不影响 ComfyUI 内部使用 WebSocket

12. 取消

接口：

POST /jobs/{job_id}/cancel

规则：

Queued 任务可立即取消。

Running 任务尽力取消。

保存 cancel_requested_at。

只中断目标任务。

如果取消前已经生成完成，可进入 completed。

中间结果默认不作为正式输出返回。

前端在终态前显示：

cancelling

13. 重试

Failed Job
  ↓
POST /retry
  ↓
New Job

MVP 支持：

same_plan

即复用原 Brief 和 Plan，重新执行。

后续可增加：

replan
new_seed
lower_quality
fallback_workflow

必须限制重试次数。

14. 超时

建议分别配置：

API 请求超时

素材处理超时

ComfyUI 提交超时

GPU Queue 等待超时

模型生成超时

排版超时

总任务超时

不要让前端硬编码超时时间。

超时错误必须说明是否可以重试。

15. 失败分类

用户可修正

素材缺失

文件格式错误

图片太小

风格和排版不兼容

文案过长

未确认素材权利

这类问题必须在使用 GPU 前发现。

可重试基础设施错误

ComfyUI 暂时不可用

网络短暂中断

History 暂时未返回

文件写入临时失败

不可直接重试的工程错误

Workflow 无效

模型文件缺失

Custom Node 缺失

输出节点配置错误

字体文件缺失

这类问题需要后端修复。

16. Job Event

每个关键步骤保存事件：

timestamp
job_id
status
stage
event_type
message
request_id
comfy_prompt_id
metadata

至少记录：

Job Accepted

Plan Created

Assets Prepared

Workflow Submitted

Engine Started

Engine Completed

Outputs Retrieved

Composition Completed

Job Completed

Job Failed

Cancel Requested

Retry Created

这份事件链是黑客松现场排错的小型飞行记录仪。

17. 完成条件

只有满足以下条件，Job 才能进入 completed：

所有候选图存在

Logo 和文字排版成功

输出文件可读取

Output 元数据已写 SQLite

Preview URL 可访问

文件尺寸和格式正确

ComfyUI 执行成功不等于 StagePoster Job 完成。

18. Mock Runner

Mock 模式必须走相同状态机：

queued
→ planning
→ preparing_assets
→ generating
→ compositing
→ completed

支持模拟：

成功

参数错误

素材错误

生成失败

取消

重试

最终返回仓库中的固定 Mock 海报。

19. 容量限制

建议：

最大 GPU 活跃任务：1
单客户端最大排队任务：3
全局最大排队任务：可配置
最大候选数量：4

队列满时返回：

429 或 503
retryable=true
Retry-After

不能无限接收任务。

20. 验收标准

Job 在执行前已持久化。

前端可观察全部关键阶段。

页面刷新不丢失任务。

重复提交不会产生重复 GPU Job。

取消语义明确。

重试会创建新任务。

重启后无永久 Running Job。

ComfyUI ID 不暴露给前端。

Mock 和真实 Runner 使用同一状态机。

Completed 时输出 URL 确实可用。
