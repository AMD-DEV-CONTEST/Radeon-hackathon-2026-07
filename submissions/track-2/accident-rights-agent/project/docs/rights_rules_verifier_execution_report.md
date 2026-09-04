# Rights Workflow、规则引擎与 Verifier 执行报告

执行日期：2026-07-29
阶段范围：RGT-01～06、RULE-01～03、VER-01～05
基线提交：`df9a143 Add local three-agent experience dashboard`

## 1. 仓库与同步审计

- 主工作区在 `main`，实施前 `git status` 干净，基线为 `df9a143`。
- GitHub Fork 的 `submission/accident-rights-agent` 仍停留在此前
  `0325716` 快照。
- 独立同步工作树
  `/private/tmp/accident-rights-sync.L0SV1P/fork` 干净，包含尚未推送的
  `2eb4f36`，其快照源为 `df9a143`。
- 本阶段未修改该同步工作树，未 push、force push、重写分支或修改远端。
- Radeon Cloud Active Instance 已销毁；本阶段未创建实例、挂载/修改持久
  卷、下载模型或产生 GPU 费用。

## 2. 开发项映射

| ID | 状态 | 实现与验收 |
|---|---|---|
| RGT-01 | 完成 | 确定性送达日期解析；落款日期弱证据；可信日期冲突进入 `disputed` |
| RGT-02 | 完成 | 版本化期限规则、2026 官方工作日历、ISO 8601 + Asia/Shanghai、失败关闭 |
| RGT-03 | 完成 | 取证、复核、鉴定、报案和理赔沟通任务；逾期仅给不保证可行的补救占位 |
| RGT-04 | 完成 | 补证重要性、时限、合法方式、替代方案、降级和条件化反事实 |
| RGT-05 | 完成 | 事实/证据/法律可追溯的复核申请草稿；缺字段时列出阻断原因 |
| RGT-06 | 完成 | 五态审批、精确版本/输入哈希绑定、修改后自动失效、外部状态防护 |
| RULE-01 | 完成 | RuleDefinition、哈希校验、as-of/jurisdiction 解析、规则冲突检测 |
| RULE-02 | 完成 | 技术符合性与法律属性分离，缺登记/鉴定时保留 suspected/insufficient |
| RULE-03 | 完成 | 赔偿路径及交强险/商业险/未覆盖层分离，缺数据禁止估算金额 |
| VER-01 | 完成 | Evidence/Fact 存在性、状态、案件归属和完整引用链 |
| VER-02 | 完成 | Law/Rule/条款/source ID/版本/日期/地区/权威语料适用性 |
| VER-03 | 完成 | 车辆、责任概率、原因力、赔偿层、期限、任务、旧审批一致性 |
| VER-04 | 完成 | 中英文风险词典与模式，hard block/rewrite，结果进入审计链 |
| VER-05 | 完成 | 汇总所有校验为 pass/warn/block；即使 pass 仍要求人工批准 |

## 3. LangGraph、API 与恢复

现有图已扩展为：

```text
liability
  → rights_workflow
  → missing_delivery_date / deadline_disputed（按需）
  → verifier
  → policy_blocked / approval_pending
  → human_approval
  → changes_requested（按需）
```

所有新增节点复用 `NodeResult`、`inputs_hash`、timeout、retry_count 和 SQLite
checkpoint。集成测试在 `rights_workflow` 后人为中断，再恢复到
`approval_pending`；恢复后高成本结果与原节点输出完全相同。

新增审批 API：

```text
POST /workflows/{thread_id}/approval
```

新增 CLI：

```text
approve THREAD_ID --decision approved|rejected|changes_requested
```

状态接口已暴露送达日期、期限、任务、补证清单、草稿、Policy Gate、审批和
失败原因。本阶段没有大幅改写现有前端。

## 4. 法律核验与版本策略

本阶段逐条核验并保存官方来源、检索时间、生效日期和内容哈希：

- 《道路交通事故处理程序规定》第五十六、七十一、一百一十二、一百一十三条；
- 《公安机关办理行政案件程序规定》第三十五条；
- 国务院办公厅 2026 年部分节假日安排；
- 《道路交通安全法》第七十六条；
- 《民法典》第一千二百一十三条；
- 机动车交通事故责任强制保险条例相关层次依据；
- GB 17761—2024 与车辆属性认定保护规则。

截至 2026-07-29，2026 年 5 月发布的是修改征求意见稿，未替代当前有效的
公安部令第 146 号。因此 proposed 内容未进入有效规则选择。

期间工具只在以下条件同时满足时计算：

1. 送达日期为 `confirmed`；
2. Rule ID 在案件日期及管辖范围内有效；
3. 期限单位、起算日和日历要求完整；
4. 官方工作日历覆盖计算区间；
5. 本地权威语料中存在匹配 `LegalCitation`。

任一条件不足时返回 `disputed/needs_legal_review`。

## 5. Demo 输出摘录

真实执行后的精简输出示例见
`docs/examples/rights_workflow_demo.json`。关键结果：

```json
{
  "delivery_date_result": {
    "status": "confirmed",
    "extracted_date": "2026-07-28",
    "date_type": "delivery_receipt_date"
  },
  "deadlines": [
    {
      "matter_type": "accident_determination_review",
      "rule_id": "RULE-CN-DEADLINE-ACCIDENT-REVIEW-2017",
      "due_at": "2026-07-31T23:59:59+08:00",
      "status": "active"
    }
  ],
  "review_application_draft": {
    "status": "draft",
    "blocking_fields": [
      "applicant.name",
      "applicant.identity_or_role",
      "challenged_document.document_number"
    ]
  },
  "policy_gate": {
    "decision": "pass_with_warnings",
    "approval_required": true
  },
  "approval_status": "pending",
  "document_status": "draft"
}
```

## 6. 自动测试结果

执行：

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check app tests
.venv/bin/mypy app
.venv/bin/python -m compileall -q app
```

结果：

```text
pytest: 90 passed, 2 non-blocking dependency warnings
ruff: all checks passed
mypy: success, no issues in 71 source files
compileall: passed
```

新增测试文件覆盖用户要求的 14 个 Rights、Rules、Verifier 和 Graph 测试
模块，并补充重复补证去重、真实审批审计 ID 与审批过期状态。P0 场景包括：

- 落款日期不触发起算、日期冲突、有效/即将届满/已过期限；
- 技术超标但车辆属性证据不足；
- 车辆属性与赔偿路径冲突；
- Evidence/Law ID 缺失、法律版本失效；
- 高风险确定性语言和篡改/删除证据建议；
- 人审前禁止外部状态、文书修改后审批失效；
- Liability 到 approval_pending 的中断恢复。

## 7. 降级、限制与未完成项

1. 当前无 Radeon Active Instance；本阶段确定性规则、Mock/Deterministic
   模型、单元和集成测试均离线完成，未产生新的 ROCm 性能数据。
2. 只内置 2026 年官方工作日历；其他年份返回
   `disputed/needs_legal_review`。
3. 截止日 `23:59:59` 仅用于内部提醒，实际受理窗口或电子提交时点需人审。
4. 规则包仍是全国层；省市登记管理差异、完整诉讼时效和保险报案期限未
   硬编码。
5. 复核、重新鉴定和逾期补救建议均不保证受理或成功。
6. 保险金额缺保单、限额、条款、损失和免责数据时固定为
   `insufficient_data`。
7. UI 本轮只提供现有状态/API/CLI 契约，没有大规模改写体验面板。

## 8. 下一阶段接口

UI 可直接读取：

- `delivery_date_result`
- `deadlines`
- `rights_tasks`
- `evidence_collection_plan`
- `review_application_draft`
- `policy_gate`
- `approval_state`
- `node_results` 与 `errors`

下一阶段 AMD 优化可在同一图上测量 `rights_workflow` 和 verifier 的本地
推理占比、Case Capsule 前后 token、Prefix Cache、TTFT、吞吐、VRAM 和
稳定性；确定性日期/规则/校验节点不需要大模型调用。
