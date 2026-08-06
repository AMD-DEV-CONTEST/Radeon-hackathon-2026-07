# E5 / M4 — 契约裁决、所有权边界与执行合同

**这份文档连同 `SCOPE-BOUNDARY.md`、`INTEGRATION-CONTRACT.md` 和 `tickets/01..11`
构成 E5 的执行合同。** 四部分的分工：本文档管**裁决与谁拥有什么**，
`SCOPE-BOUNDARY.md` 管**做什么、不做什么**，`INTEGRATION-CONTRACT.md` 管
**并行时怎么合、fixture 债务归谁**，`tickets/` 是十一份可交给实施 Agent 的票面。

issue #24 正文与 `contracts/checkpoints/e5-m4-execution-v1.json`（PR #28 分支上）目前
与本套文档在票号、拆分和裁决范围上不一致。对账工作单独立项跟踪，见本文档第四节。

- 代码基线：`main@59a20f8`
- 治理基线：PR #28 分支 head `8ae6117`（`docs: enable parallel E5-E7 delivery`，未合并）
- 实施负责人：`1olaqua616-web`（票 01–11，单分支单 Draft PR）
- 质量、晋级、合并权威：`kinnyuww`
- 评审模式：并行期不需要用户逐阶段同步硬审批；公共检查与异步 teammate/Codex
  review 持续运行；最终 E5 阶段门在 E5/E6/E7 全部 `INTEGRATION_READY` 后的批量验收
  窗口记录
- 并行状态：E6（`Eas000n`）、E7（`kinnyuww`）与 E5 同期开发，消费冻结合同与 mock；
  E5 拥有首个共享入口整合权

---

## 一、契约裁决

三线并行下，E5 会改到 E6/E7 也在读的符号。以下裁决写明失败机制，便于后续有人质疑
时直接检验因果，而不是翻出一句「当初这么定的」。

### 裁决 1 — 关系状态的持久化权威

**关系账本（sidecar relation ledger）是候选、决定、确认、失效状态的唯一持久化权威。
`ExperienceAssetV1` 上四个相关字段逐一裁决如下。**

| 快照字段 | 裁决 | 依据 |
|---|---|---|
| `relation_candidates` | 退休进账本 | 见下方哈希互斥机制 |
| `relation_candidate_decisions` | 退休进账本 | 同上 |
| `related_assets` | 退休进账本的 confirmed relation 记录 | 它就是确认关系的简化形态（`related_asset_id` + 自由文本 `relation` + `confirmed_by_user`），受同一机制约束；其自由文本 `relation` 同时要映射到六种固定类型 |
| `knowledge_card_readiness` | 退休进 readiness sidecar 记录，键为 (asset_id, version_id, card_hash)，owner 是票 03 | 见下方版本错位机制 |

**哈希互斥机制（前三个字段）**：快照不可变且带内容哈希。确认一条关系必须持久化
decision，写进快照就得追加一个新的资产内容版本，内容哈希随之改变。而 GRAG-14 要求
详情读取前后快照 JSON、语句哈希、卡片哈希三者全等。两个要求同时成立是不可能的，
因此嵌入方案让 AC-30 的非污染不变量无法满足——这是结构性冲突，不是取舍偏好。

**版本错位机制（`knowledge_card_readiness`）**：就绪由用户在某个版本 V 存在**之后**
显式接受而产生。快照不可变，所以把就绪写进快照必须产生版本 V+1。此时出现两难：
若 V+1 里的就绪记录指向 V，则「描述就绪的版本」与「被判定就绪的版本」永远差一个，
每个消费者都得知道这条错位规则；若指向 V+1 自身，则用户接受的是 V，而 V+1 的内容
与他们审阅过的不同，且 `content_hash` 要覆盖包含它自己的字段，形成自指。两条路都
坏，所以就绪必须作为 sidecar 记录存在于被它描述的快照之外。

**类型符号会被扩展，不是原样冻结。** PR #28 的 handoff manifest 把
`RelationCandidate` / `RelationCandidateDecision` 列为 E5→E6 冻结交接符号，但当前
`RelationCandidate` 只有 `candidate_id`、`related_asset_id`、`title`、`summary`、
`proposed_relation: NonEmptyText`、`reason: NonEmptyText`、
`provenance_refs: list[str]`、`detail_included: Literal[False]`。它无法表达六种固定
关系类型（现在是自由文本）、双边节点映射、边界节点、当前/历史投影绑定、发现指纹、
校验合同版本和生命周期状态；扁平的 `provenance_refs` 也分不出溯源属于哪一侧。

因此 E5 必须扩展这个类型，**E6 的 mock 形状会变**。这是对已冻结交接符号的实质变更，
按并行合同 §6 属于「需要更改 canonical Schema」，票 01 必须在改动前把新形状告知 E6
并留痕。声称「形状不变」会这样失败：E6 按旧形状写完 mock 与断言，E5 合并后 E6 的
真实联调在集成当天才发现字段缺失，而那时三条线都已接近 `INTEGRATION_READY`。

### 裁决 2 — `AgentRunStateV1` 的六个关系字段

**保留，但降级为只读权限快照，每次策略评估时从关系账本重新投影。**

`AgentRunStateV1` 已有 `knowledge_card_version_id`、`knowledge_card_hash`、
`relation_candidate_ids`、`confirmed_relation_ids`、`confirmed_related_asset_ids`、
`confirmed_relation_bindings`，Runtime 用它们判断跨资产工具调用是否放行。这与同一
模型里已有的 `permission_snapshot` 同构，保留不引入新概念。

**让 run state 持有权威的失败机制**：同一资产上的两个并发 run 各自持有一份关系集合
且互不知情，谁写谁赢。更具体的一种：一个长跑 run 在开始时投影了关系集合，随后用户
修正了历史资产、该关系被作废，但 run 内那份副本仍然放行详情读取——这正是 GRAG-16
要抓的过期访问。因此权限判断必须在每次评估时重新从账本投影并复验版本/哈希绑定。

**重投影的实现归票 07**（它拥有权限授予），调用点在 Runtime policy service。矩阵里
不写 owner 会这样失败：这是一个横跨 07、08 与 policy 层的读路径，无人认领时最可能的
结果是三处各写一份投影逻辑，而其中任何一份漏掉版本复验都会重新打开 GRAG-16 的洞。

**待票 01 解决的 ID 语义冲突**：`policy/runtime.py` 现在要求
`confirmed_relation_ids ⊆ relation_candidate_ids`，而 GraphRAG spec §7 给确认关系
独立的 Relation ID 加一个 source candidate ID。按新模型，`confirmed_relation_ids`
装的是 relation ID 而非 candidate ID，这个子集检查会对**每一次合法确认**失败。票 01
须冻结迁移规则；建议改为「每条确认关系的 source_candidate_id ∈ relation_candidate_ids」
——它保住了原检查的本意（不能确认一个本次 run 从未提出过的候选），同时容纳新的
双 ID 模型。

### 裁决 3 — 跨资产工具合同的 free-text `query`

**`RelatedCandidateDiscoveryArguments.query` 与 `ConfirmedRelatedEvidenceArguments.query`
移除；`CurrentExperienceSearchArguments.query` 保留。两者移除的理由不同。**

当前源检索本来就应该接受查询词，移除它会削掉一个正当能力。

**发现侧（`RelatedCandidateDiscoveryArguments`）**：输入改为整张已就绪的知识卡片加
一个 Runtime 拥有的发现意图版本。允许用户或模型自填查询词会这样失败：关系要长期
存续，而查询词是一次性提问；用措辞驱动发现，等于让同一对资产在不同问法下得到不同
关系，关系的含义退化成「上次那句话问出来的结果」。

需要说清的是，**固定发现意图只是消除了一个变异源，它本身不产生可复现性**。结果稳定
来自完整的发现指纹加幂等缓存——指纹覆盖当前卡片版本/哈希与投影哈希、排序后的可用
历史资产/版本/投影哈希、模型身份与冻结修订、prompt 版本、角色与校验合同版本、推理
参数、预筛配置版本。把可复现性归功于固定意图会掩盖真正的机制，实现时就可能漏掉指纹
里的某一项而仍以为结果是稳定的。

**详情侧（`ConfirmedRelatedEvidenceArguments`）**：移除 `query` 之后**不用发现意图
替代**。确认后的详情读取由精确的确认关系、资产、版本/哈希绑定和已校验的映射/边界包
限定，可读集合是被这些绑定算出来的，不存在需要查询词或意图去挑选的余地。给它一个
意图版本会这样失败：它暗示这次读取还有可调的检索行为，而实际上任何可调性都意味着
一次确认可以读出不同的东西——正是「一次确认只解锁一个资产的限定证据」要排除的。

**这条不触及 E6**：并行合同 §4 规定 E6 消费已确认且绑定版本/哈希的 M4 状态与允许的
历史关系，且不得在 `KnowledgeCardReady` 前触发跨资产检索。E6 消费结果，不调用发现
工具；handoff manifest 的四个符号也都不带 `query`。E5 依 §3.3 的首个共享入口整合权
直接实施。

---

## 二、E5 内部所有权矩阵

阻塞边只规定顺序，不阻止两票写同一张表。三线并行之后，重复写入的代价从「E5 内部
返工」升级成「打断 E6/E7 的 mock」。因此每个可变对象只有一个 owner，其余票只读消费。

| 对象 | 唯一 owner | 其他票的关系 |
|---|---|---|
| 冻结合同、生成物、迁移编号与 DDL、共享入口 | 01 | 02–11 只消费；需要改合同必须回到 01 走显式 contract-change review |
| attempt / fingerprint / 关系账本的**接口与 schema** | 01 | 05 与 06 各自实现其一部分，谁都不重新定义形状 |
| M4 artifact schema、编辑与版本化 | 02 | 03 读取以判定可接受性；09 触发其失效 |
| M4 因上游 M1–M3 修正而失效 | 02 | 09 不处理 ready 之前的失效 |
| `KnowledgeCardReady` 状态迁移与 readiness sidecar 记录 | 03 | 02 只提交 M4 artifact；09 只撤销 ready 之后的派生物 |
| 投影与 FTS 索引的创建、激活、重建 | 04 | 09 只在同一事务里提交失效事件 |
| 单次发现的 attempt 记录、candidate 校验与持久化 | 05 | 06 加固其重复/并发/崩溃语义，不改其结果 schema |
| 指纹规范化、租约与崩溃恢复、重试预算、并发合流 | 06 | 05 产出的单次结果在此获得幂等保证 |
| decision、confirmation 写入、durable relation 创建与权限授予 | 07 | 08 只读取已确认的关系记录 |
| 每次策略评估时从账本重投影权限 | 07 | 调用点在 Runtime policy service |
| 证据卡渲染与详情读取 | 08 | 不写 canonical snapshot，不创建 decision |
| ready 之后的跨 artifact 失效与恢复编排 | 09 | 不重定义各 artifact 的状态枚举 |
| 本机证据包 | 10 | 不产出任何 W7900 主张 |
| W7900 精确 head 门 | 11 | 不接受 fake、旧包或异 commit 的运行作为证据 |

### 05 与 06 的边界（原循环依赖已解）

早期票面写着「05 调用 06 的接口」，而 06 被 05 阻塞——那是个真实的循环，现修正为：

- **票 01** 冻结 attempt 记录、指纹字段集与关系账本的 schema 和接口；
- **票 05** 拥有「搜一次拿到答案」：预留一条 attempt、发起一次批量调用、校验、持久化
  candidate 或 no-match、映射技术失败。它实现的是 01 冻结的接口，不是 06 的接口；
- **票 06** 拥有「搜第二次、并发搜、搜到一半崩溃，仍然得到一个自洽答案」：指纹规范化
  的确切口径、幂等缓存、租约与过期、崩溃恢复、重试预算与退避、并发合流。

这样两票都是可演示的垂直切片：05 演示「点一次得到结果」，06 演示「点两次、同时点、
中途断电，结果仍然只有一个」。

---

## 三、通用验证口径

每票至少跑通：

```text
python3 scripts/export_contracts.py --check
bash qa/gates/pr_gate.sh --mode contract
python3 -m unittest discover -s qa/tests -v
python3 -m pytest -q
ruff check .
bash -n scripts/*.sh
python3 -m py_compile scripts/*.py
```

前端受影响时另跑 web 的合同与 view-model 测试；改动 HTTP 行为、迁移、重启或 trace
的票，在票面各自列出其确切命令。

### 证据状态语义

三个词不可互换，混用会让读者无法判断某条主张究竟是「做了没过」「能做还没做」还是
「根本做不了」：

| 状态 | 含义 |
|---|---|
| `PASS` | 在本包记录的 commit 与环境上实际执行且通过 |
| `NOT_VERIFIED` | 环境具备、可以执行，但本包尚未执行 |
| `BLOCKED` | 环境或依赖缺失，本包无法执行；须写明缺什么 |

W7900/ROCm/vLLM 不可用时，相关主张一律 `BLOCKED` 并注明缺失环境，不写
`NOT_VERIFIED`（那会暗示只是没排上），更不写 `PASS`。把 fake 结果写成 `PASS` 会这样
失败：证据包的唯一用途是让第三方在不信任作者的前提下复核，一旦其中混入一条不可复现
的 `PASS`，整包的可信度归零，而不是只损失那一条。

---

## 四、与既有执行清单的已知分歧

本套文档与 issue #24 正文、`contracts/checkpoints/e5-m4-execution-v1.json`（PR #28
分支）在四处不一致。对账不在本 PR 内完成，单独立项跟踪。

| 项 | 本套文档 | 既有清单 | 依据 |
|---|---|---|---|
| 票数与拆分 | 11 票，02 = M4 图，03 = readiness | manifest 10 票，无 M4 票、无 readiness 票，T09 把 UI 与证据卡捆绑 | 本 issue 的标题即 M4 交付；`app/experience_asset/application/` 现只有 m1/m2/m3，manifest 的 T02 要投影一个没有票负责建造的 artifact |
| 快照字段退休范围 | 四个字段逐一裁决（见裁决 1） | issue #24 仅裁 `relation_candidates` 与 `relation_candidate_decisions` | `related_assets` 与 `knowledge_card_readiness` 受同类机制约束，留在快照内会分别触发哈希互斥与版本错位 |
| 类型是否变形 | `RelationCandidate` 必须扩展，须通知 E6 | issue #24 早期表述为「类型冻结、mock 形状不变」 | 现有类型的 `proposed_relation` 是自由文本，`provenance_refs` 是扁平列表，无法表达固定关系类型与双边溯源 |
| 证据票拆分 | 按硬件拆成 10（本机）与 11（W7900） | manifest 为单票 T10 | 合票在无 ROCm 的机器上无法到达终态，会迫使持票者在「长期挂起」与「记录未验证的主张」之间二选一 |

对账完成前，**不要把 `contracts/checkpoints/e5-m4-execution-v1.json` 交给实施
Agent**：它会在 T02 去投影一个没有任何票负责建造的 M4 artifact，而 Agent 面对缺失
上游最可能的两种反应——停下询问，或就地自造一份 M4 schema——后者会绕过票 01 那次
唯一的合同冻结评审，而 E6/E7 正基于该次冻结的符号并行开发。
