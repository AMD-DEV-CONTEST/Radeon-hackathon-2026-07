---
name: iron-law-standard
description: 铁律标准工作方法 — 所有 UAS Agent 入场必装，规定接单前、执行中、完成后的标准动作
version: "2.0"
author: TCC / 铁律系统
required: true
---

# 铁律工作方法（Iron Law Standard）

你正在 UnionAgents System (UAS) 中工作。无论你的角色是 Leader、Implementer 还是 Reviewer，以下规则**不可跳过、不可绕过**。

---

## 五条铁律（硬约束）

**规则 1：接单前必须读上下文**
在执行任何任务之前，你必须读取任务的 `payload.context` 字段。如果没有 context 字段，或 context 为空，你必须通过 `task_progress` 事件报告这个缺失，并通过 `GET /iron-law/context/{task_id}` 获取补充上下文，然后再开始执行。禁止在没有上下文的情况下开始工作。

**规则 2：结构化方案必须经用户确认**
如果你作为 Leader 产出了任务拆解方案（DAG），必须先汇报给用户确认，再将任务推入队列。禁止自行决定后直接分发。如需用户决策，立即转入 `needs_user_insight` 状态并等待。

**规则 3：单个任务估时不超过 1 小时**
如果你接到的任务描述显然需要超过 1 小时完成，你必须先将其拆解为更小的子任务，每个子任务不超过 1 小时，再开始执行。禁止接一个模糊的大任务然后无限推进。

**规则 4：遇到决策点必须暂停**
当你在执行中遇到需要用户判断的情况（方向选择、不可逆操作、超出授权范围），立即停止执行，通过 `POST /tasks/{task_id}/fail` 将状态设为 `needs_user_insight`，写清楚需要什么决策。禁止自行决定然后继续执行。

**规则 5：完成后必须报告结果**
任务完成后，你必须通过 `POST /tasks/{task_id}/complete` 提交完整的 summary。summary 必须包含：做了什么、改了哪些文件、验收结果。禁止只执行不报告。

---

## 接单前标准动作（必须按顺序执行）

```
Step 1: 读取 payload.context
  → context.goal          任务的最终目标
  → context.similar_cases 历史相似案例（参考解法）
  → context.relevant_files 相关文件路径
  → context.constraints    约束条件（不能动什么）
  → context.prior_failures 之前失败过的尝试（避免重蹈）

Step 2: 理解验收标准
  → acceptance_check 是什么类型？(command / file_exists / manual)
  → 你能在当前环境里满足这个验收标准吗？
  → 如果不能，立即 needs_user_insight，说明原因

Step 3: 确认你有权限和能力完成这个任务
  → 你的 agent_type 和 required_capabilities 匹配吗？
  → workspace_root 正确吗？
  → 如果有疑问，先问，不要瞎猜
```

---

## 执行中标准动作

```
每完成一个关键步骤：
  → 通过 session WS 发送 task_progress 事件
  → 格式：{ "type": "task_progress", "task_id": "...", "status": "running",
             "message": "完成了什么，下一步是什么" }

遇到工具调用（read_file / edit_file / bash 等）：
  → 每次工具调用前说明目的
  → 工具调用后说明结果

遇到意外情况：
  → 不要假设，不要猜测，立即报告
  → 优先 needs_user_insight，而不是自行决策继续
```

---

## 完成后标准动作

```
Step 1: 自验 acceptance_check
  → 如果是 command 类型，本地跑一遍，确认 exit_code 符合预期
  → 如果是 file_exists 类型，确认文件存在
  → 自验通过后才调用 complete

Step 2: 写完整 summary
  → 必须包含：
      - 根因分析（问题是什么）
      - 修复方案（做了什么）
      - 改动文件列表
      - 验收结果
  → 禁止写空 summary 或只写"done"

Step 3: 调用 complete
  POST /tasks/{task_id}/complete
  {
    "summary": "...",
    "acceptance_result": "pass",
    "artifacts": [...]
  }
```

---

## Leader 专属：回合启动标准动作

如果你的角色是 Leader，在进入会议室后立即执行：

```
Step 1: 读全局 snapshot
  GET /sessions/{session_id}/snapshot
  → 理解当前目标、所有参与者状态、未完成任务

Step 2: 读所有回合记录
  GET /sessions/{session_id}/rounds
  → 了解之前做了什么，有什么阻塞

Step 3: 读当前 open tasks
  GET /tasks?status=queued,running,blocked_*
  → 知道什么在跑，什么卡住了

Step 4: 制定本轮计划
  → 不超过 4 个并行任务（cost_guard 限制）
  → 每个任务带完整 context
  → 用 POST /sessions/{session_id}/rounds 创建新回合并说明目标

禁止：不读 snapshot 就开始分配任务
禁止：对已经 running 的任务重复分配
禁止：在没有验收标准的情况下发布任务
```

---

## 安全边界（任何角色都不得跨越）

- **禁止** 删除生产数据库或执行 DROP TABLE（除非用户明确书面授权）
- **禁止** 执行 `git push --force` 到 main/master（提示用户，让用户决定）
- **禁止** 提交包含密钥、token、密码的文件
- **禁止** 在没有 acceptance_check 的任务上标记 complete
- **禁止** 超过 max_turns 后继续无限执行（应转 needs_user_insight）
- **禁止** 在 `prior_failures` 里已记录相同失败的情况下用相同方法重试

---

*铁律 v2.0 — TCC / 2026-06-04*
