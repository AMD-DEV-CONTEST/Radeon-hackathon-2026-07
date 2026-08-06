# E5 / M4 执行合同

Issue #24（`[E5] Deliver M4 Insight and Boundary Map with gated RAG`）的实施拆分。
本目录不改变 E5 的已批准范围、AC 映射或验收路线，只把它拆成可以交给实施 Agent 的
票面，并写明票与票之间的边界、集成方式和裁决依据。

## 阅读顺序

交给实施 Agent 时按这个顺序给，一次只给当前那一票：

| 顺序 | 文档 | 作用 |
|---|---|---|
| 1 | [`SCOPE-BOUNDARY.md`](SCOPE-BOUNDARY.md) | 交付什么、不交付什么。每条「不做」都写明失败机制和注意力该去哪里 |
| 2 | [`OWNERSHIP-AND-DECISIONS.md`](OWNERSHIP-AND-DECISIONS.md) | 三条契约裁决、十一项所有权矩阵、通用验证口径、与既有清单的分歧 |
| 3 | [`INTEGRATION-CONTRACT.md`](INTEGRATION-CONTRACT.md) | 波次与并发、分支与 PR、每票的输入输出、共享文件写入权、fixture 债务归属 |
| 4 | [`GRAG-BEHAVIOR-MATRIX.md`](GRAG-BEHAVIOR-MATRIX.md) | GRAG-01–18 逐条绑定到票、fixture 与它要防住的失败 |
| 5 | [`BOUNDARIES.md`](BOUNDARIES.md) | 迁移、失效、隐私、回滚、证据追加五条边界 |
| 6 | `tickets/<NN>-*.md` | 当前这一票 |

只给票面而不给前三份会失败：票面写的是「这一票交付什么行为」，而边界、裁决和共享
文件写入权都在前三份里。Agent 拿到孤立票面时，遇到「要不要顺手把相邻的事做了」
「这个字段能不能改」只能自行决定，而这类决定不会在票面的验收清单里暴露出来。

## 票面

| # | 票 | 阻塞于 | 交付的端到端行为 |
|---|---|---|---|
| 01 | [合同与 fixture 冻结](tickets/01-contract-and-fixture-freeze.md) | — | 关系账本迁移；M4 图、就绪、六种关系类型、六种发现结果、Runtime 拥有的发现意图冻结；快照四字段逐一退休；三份场景 fixture 与每个中间 artifact 的实例 fixture；全部 E5 端点定路径并注册 |
| 02 | [M4 洞察与边界图](tickets/02-m4-insight-and-boundary-map.md) | 01 | 用户生成、阅读、修正洞察与边界图，每条可点开证据，缺口显式可见，上游修正使其失效 |
| 03 | [KnowledgeCardReady](tickets/03-knowledge-card-ready.md) | 02 | 显式接受铸出绑定精确版本与卡片哈希的就绪；就绪前发现被拒且不产生任何跨资产读或模型调用；接受本身不启动搜索 |
| 04 | [角色图投影与 FTS5 摘要索引](tickets/04-role-graph-projection-and-lexical-index.md) | 01 | 确定性只读投影的事务性构建与激活；摘要索引与可复现的中英文归一；显式词法 no-match |
| 05 | [显式发现：零或一个候选](tickets/05-explicit-discovery-one-candidate-or-no-match.md) | 04 | 一次显式动作、一次批量调用、严格提案校验、必需迁移边界、双边溯源；硬负例为语义 `NO_MATCH`；非法提案为校验失败 |
| 06 | [指纹幂等与技术失败重试](tickets/06-fingerprint-idempotency-and-retry.md) | 01 | 同指纹返回同结果且不再调模型；技术失败可重试且不被缓存成 no-match；并发同指纹共享一次预留 |
| 07 | [确认与拒绝，绑定不符即关闭](tickets/07-confirm-decline-fail-closed.md) | 05 | 确认前详情被拒；确认在一个事务内创建关系并只授权一个历史资产；拒绝持久化；错绑定失败关闭 |
| 08 | [确定性证据卡与非污染](tickets/08-evidence-card-and-non-contamination.md) | 01 | 应用代码确定性渲染的双边证据卡，无第二次模型调用与建议；读取前后快照 JSON 与两个哈希全等 |
| 09 | [失效、过期与重启恢复](tickets/09-invalidation-staleness-and-resume.md) | 08 | mutation × artifact 失效矩阵；在策略层而非界面层撤销访问；重启恢复候选、拒绝、确认、权限与终态 |
| 10 | [本机确定性证据包](tickets/10-local-evidence-packet.md) | 06, 09 | 公共缝上跑通 GRAG-01–18、公共 QA、迁移升级与重建、披露扫描；终态为 `prepared` 或 `not-run` |
| 11 | [W7900 精确 head 门](tickets/11-w7900-exact-head-gate.md) | 10 | 已批准 loopback 路径上一个正例结构化提案与一个语义硬负例，记录精确 commit 与模型运行时身份；环境不可用时终态为 `BLOCKED` |

依赖是阻塞链，不是建议顺序：某票只有在阻塞它的票全部完成后才可开始。06 与 07 都只
依赖各自的前序且互不阻塞。

## 并行状态

首波 `W0`（票 01）单独执行，其产出是其余每一票的输入。第二波 `W1`（票 02、04、06、
08）四路并行，各自对着票 01 的冻结合同与实例 fixture 构建。其余票暂不并行，等 W1 跑完
拿到实测再决定——详见 [`INTEGRATION-CONTRACT.md`](INTEGRATION-CONTRACT.md) 第七节。

`W1` 中只有票 02 能在本波内标记 `INTEGRATION_READY`；04、06、08 携带 fixture 债务，
需在各自上游落地后改跑真实产物才算完成。把「已构建」当成「已完成」会让证据包声称某项
行为通过，而那次通过用的是本项目自己编的输入，第三方无法复现。

## Fixture

`contracts/examples/e5/` 由 `scripts/export_e5_fixtures.py` 生成，
`tests/unit/test_e5_fixtures.py` 逐份对冻结模型复验：

- `instance/` — 每个中间 artifact 的一份可用实例（M4 图、就绪记录、当前与历史投影对、
  发现指纹、attempt、候选、决定、已确认关系）。Wave-1 的票对着它们构建，而不是各自
  编一份；一份编出来的形状会让 Agent 照着后端永不接受的样子正确构建。
- `scenario/` — 三份 sanitized 场景：跨主题正例、硬负例语料、非法关联提案。

重新生成用 `python3 scripts/export_e5_fixtures.py`，核对用 `--check`。
