# E2 / M1 Contract、Schema 与 Fixture 检查点

状态：`READY_FOR_QUALITY_OWNER_CONFIRMATION`

本文件只请求质量负责人确认 E2 的第一个检查点。它不宣称 E2 完成，不批准
E2 合并，也不把当前分支上的 Backend/UI/W7900 工作提升为已验收状态。

机器可读冻结清单：
[`contracts/checkpoints/e2-m1-contract-fixtures-v1.json`](../../contracts/checkpoints/e2-m1-contract-fixtures-v1.json)。

## 1. 确认后能解锁什么

质量负责人确认该检查点后，`1olaqua616-web` 可以按流水线规则开始 E3 的
合同、Mock、公共 Fixture、负例、测试和隔离模块准备。E3 此时仍然：

- 不能接入未合并的 E2 真实状态；
- 不能修改共享 canonical schema、API 主入口或 migration；
- 不能标记 Ready、合并或宣称 E3 完成；
- 必须等 E2 合并并通过最终质量门后，才能同步 `main`、真实联调并转为
  Ready。

## 2. 冻结范围

| 类别 | 冻结内容 |
|---|---|
| 输入 | 对话、粘贴文本、`.txt`、`.md`、带来源声明的公共改编 Fixture |
| 产物 | 可编辑并自动保存的 `Experience Brief v0.1` 与 M1 Workspace |
| 用户动作 | 编辑、回答、跳过、推迟、暂停、恢复、按当前证据确认、运行当前来源 Agent |
| 错误 | `404` 不存在、`409` 版本冲突、`422` 合同/状态违规，以及可见的模型/策略终态 |
| 进度 | 只来自保存版本、已确认陈述、未解决问题、产物状态和持久化终态；不提供虚构 ETA |
| 失效 | 新版本使旧 Agent Trace 失效；修改已完成 M1 会重开 M1；未来 M2 必须绑定获准的 M1 版本 |
| 检索 | M1 仅允许当前来源；跨资产 RAG、发布、网络、Shell、导出和审批工具全部拒绝 |

八个 API 和完整 Schema 列表以机器可读冻结清单为准。Schema 由
`scripts/export_contracts.py` 生成，`--check` 必须能证明仓库中的 JSON
Schema 和 OpenAPI 与代码一致。M1 不新增编号 migration，因为当前 SQLite
Repository 保存完整、不可变的 canonical JSON 版本。

## 3. Fixture 与失败边界

第一个检查点直接冻结五类公共 Fixture：

- `chair_public_complete`：正常形成来源可追溯的 Brief；
- `chair_incomplete`：提出不超过三个、有理由的问题，缺失信息不得补造；
- `chair_conflicting`：保留冲突并请求确认，不静默选边；
- `chair_correction`：产生新版本并保留被纠正判断；
- `chair_resume`：从最后持久化版本恢复。

其余 `privacy_risk` 与 `route_ineligible` 仍保留在全局七类公共 Fixture
合同中，但主要由 E6/M5 消费；本检查点不提前实现其路线或审批行为。

负例覆盖空输入、扩展名错误、公共改编来源缺失、空编辑、问答动作不匹配、
陈旧版本、带缺口确认、导入提示注入、未授权检索与越权工具提议。质量负责人
可使用同一公开要求的私有变体，但私有 Fixture、Gold 和评分不得进入本 PR。

## 4. 质量与赛道映射

- AC：`AC-01`、`AC-03`、`AC-04`、`AC-10`、`AC-13`、`AC-15`–
  `AC-18`、`AC-22`、`AC-23`、`AC-25`。
- L1：`M1 Experience Brief`。
- L2：Canonical state、Persistence and resume、Evidence discipline、
  Retrieval phase integrity、Runtime permission、Local inference、Failure
  behavior、Observability。
- Track 2：私有本地推理、多步骤计划、Tool Calling 提议与 Runtime 权限分离、
  当前来源本地检索、结果验证和持久化终态。
- 提交影响：冻结后可让 E3 使用稳定的 M1 边界准备 Mock/测试；真实
  W7900 `Serving Reference S1`、完整 Vertical Slice V1 和 E2 提升仍属于
  后两个检查点。

## 5. 跨 Lane、审核与证据

| 责任 | 人员/约束 |
|---|---|
| E2 负责人 | `Eas000n` |
| 独立审核与确认 | `kinnyuww` |
| 确认后的相邻阶段准备 | `1olaqua616-web`，仅限 E3 隔离准备 |
| 证据 | `evidence/milestones/e2-m1-contract/<run_id>/`，绑定准确实现 commit |
| 回滚 | 回退本检查点实现 commit；E2 保持未提升，E3 保持 blocked |

PR 应保持 Draft，并在正文中明确“只请求确认第一个检查点”。绿色 CI 不能替代
质量负责人确认。
