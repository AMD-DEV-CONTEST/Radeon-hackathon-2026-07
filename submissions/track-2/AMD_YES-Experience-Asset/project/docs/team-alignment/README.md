# 团队 Discover 对齐包

这个文件夹是三人 AMD AI DevMaster Track 2 团队共享的产品发现成果。

组员及其 Coding Agent 应统一从仓库根目录的 [`spec/README.md`](../../spec/README.md)
进入。该入口给出权威文档顺序、按任务选择的阅读路径、公开/私有质量边界和
提交方案前必须完成的 Agent 对齐协议；本目录继续保存权威内容，不在 `spec/`
重复一套容易漂移的需求副本。

## 组员阅读顺序

先阅读 `PRODUCT_BLUEPRINT.md`。它是已经拍板方案的中文可视化说明，包含
打磨体验、前两层项目框架和比赛证据链。

需要负责 Radeon Cloud、ROCm、vLLM、评测或性能调优的组员，再阅读
`BENCHMARK_PLAN.md`。它定义冻结夹具、运行 Manifest、三层指标和
baseline/optimized 对比规则。

`TEAM_QUALITY_CONTRACT.md` 是已批准并交给组员及其 Coding Agent 的质量合同，规定
里程碑、业务护栏、阶段性能偏好和公开证据包，但不包含质量负责人的隐藏测试、
Gold Answer 或精确评分。合同允许组员通过版本化、事前审批的提案，基于组件
证据合理调整性能评测和优化方向，但不得在看到测试结果后反向改靶。

RAG 顺序也是当前硬合同：M1–M4 只使用当前来源和同资产版本；M4 知识卡片就绪
后才发现摘要候选，用户确认关系后才读取选中历史资产的详细证据。任何涉及
Agent/RAG 的组员任务都必须同时读取 `AGENT_ARCHITECTURE.md` 和 AC-30 公共门禁。

需要核对严格范围和验收条件时，再依次阅读：

1. `../kinnyu/CURRENT_ITERATION.md`
2. `../kinnyu/PROJECT.md`
3. `../kinnyu/BACKLOG.md`

负责 E2–E8 排期、所有权、相邻阶段并行或 Issue 创建时，还必须阅读
`../kinnyu/E2_E8_PIPELINE_EXECUTION_PLAN.md`。该方案已获用户批准，但需由
质量负责人审核后才取代 L3 原有的 E2–E7 双 Lane 默认分工。

## 交给组员的 AI Agent

将以下文件提供给 Agent：

1. `AI_AGENT_DISCOVERY_PACKAGE.md`
2. `../kinnyu/CURRENT_ITERATION.md`
3. `AGENT_ARCHITECTURE.md`（若涉及 Agent、RAG、工具、记忆或权限）
4. `BENCHMARK_PLAN.md`（若涉及模型、Runtime、评测或体验指标）
5. `TEAM_QUALITY_CONTRACT.md`
6. 仓库根目录的 `AGENTS.md`

要求 Agent 在提出方案或修改文件前，先按照 AI 对齐包结尾规定的六个标题
输出“理解与对齐报告”。

## 当前状态

- 需求：`APPROVED`
- 工程方案：`APPROVED`，见
  [`../kinnyu/L3_ENGINEERING_PLAN.md`](../kinnyu/L3_ENGINEERING_PLAN.md)
- 产品实现：`E1 ACCEPTED / E2 ACTIVE`；Issue #5 / PR #7、Issue #6 /
  PR #8、PR #12 和流水线治理 PR #13 已审核并合并，计划基线为
  `main@b053f66`
- 里程碑状态：PR #12 的终态修复、畸形响应归一化和精确当前提交
  W7900/ROCm/14B 联合门禁已获质量负责人接受，T06 为 `PASS`
- 任务边界：E1-A1/A2/A3 是同一个 Issue #5 / PR #7 内三个可独立审核的
  checkpoint，不是三个 Issue
- 当前执行：PR #13 已合并到 `main@b053f66`，Issue #15 已冻结三个审计检查点，
  `Eas000n` 的 `codex/e2-m1-experience-brief` 已完成 E2/M1 LangGraph 垂直切片，
  正在最终集成与 CI；E2 尚未提升。E2/E4/E6/E7 使用合并式深审，
  E3/E5 使用异步轻量技术门；
  `evidence/milestones/e1-combined/20260727T055758Z/` 为已接受的当前 E1
  证据包，两个旧包继续保留

这份对齐包只传递已经确认的产品决策和当前边界，不单独授权新增工作范围、
合并、发布、删除数据或修改基础设施。已分配的开发只在对应 Issue、分支和
合并门禁内有效。
