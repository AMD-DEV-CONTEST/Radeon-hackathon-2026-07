# GRAG-01 – GRAG-18 外部行为矩阵

E5 的验收在**公共 HTTP 缝**上进行，而不是在架构声明上。下表把每条行为绑定到拥有它的
票、它使用的 fixture，以及它要防住的失败。

「要防住的失败」一列不是修辞。一条只写「应当拒绝」的验收项，实现者读完仍然可以选择
在读取之后丢弃结果——那也叫拒绝，但历史内容已经进过模型、预算已经花掉。写清失败长什么
样，实现才知道拒绝必须发生在工作之前。

## 矩阵

| ID | 公共缝上的行为 | 要求的结果 | 票 | fixture | 若做错会怎样 |
|---|---|---|---|---|---|
| GRAG-01 | 在精确 `KnowledgeCardReady` 之前发起发现 | 以稳定原因码拒绝；无任何跨资产读取、无模型调用 | 03 | — | 先读再丢弃同样已把历史材料送进模型并花掉预算，拒绝必须发生在工作之前 |
| GRAG-02 | 接受卡片但不点击发现 | 不产生任何 discovery run | 03 | — | 接受即搜索会花掉本地模型时间，并把历史摘要推给一个没要求比较的人 |
| GRAG-03 | 跑跨主题正例 | 恰好一个候选，含固定关系类型、双边映射、迁移边界、双边溯源；无详情 | 05 | `scenario/cross-topic-positive.json` | 缺任一项的候选仍会以完整外观呈现，用户无从看出缺了什么 |
| GRAG-04 | 跑硬负例语料 | 语义 `NO_MATCH`，零候选，呈现为已完成的搜索 | 05 | `scenario/hard-negative-corpus.json` | 把弃权显示成错误会训练用户反复重试直到出现结果 |
| GRAG-05 | 只有一条有效关系时请求 `top_k=3` | 一个候选；不补位、不返回零分兜底 | 05 | `scenario/cross-topic-positive.json` | 补位让用户把注意力花在几条弱主张上，而非一条强的 |
| GRAG-06 | 提交每一种非法关联提案 | 无候选；安全的校验失败与重试语义 | 05 | `scenario/invalid-false-association.json` | 记成 `NO_MATCH` 会把一次传输事故当作语义结论缓存下来 |
| GRAG-07 | 用同一指纹重复发现 | 同一候选或同一 no-match，且不再调用模型 | 06 | `instance/discovery-fingerprint.json` | 结果可变时用户会一直点到自己满意，关系由坚持而非证据选出 |
| GRAG-08 | 超时或畸形响应后重试 | 允许新的有界技术尝试；先前失败不作为 no-match 返回 | 06 | `instance/discovery-attempt.json` | 复用一次停机会永久抹掉一条可能存在的关系 |
| GRAG-09 | 改变当前卡片、可用历史投影、模型、prompt 或配置 | 新指纹；不复用过期结果 | 06 | `instance/discovery-fingerprint.json` | 忽略模型身份会让升级后的模型继续返回旧模型的缓存判断 |
| GRAG-10 | 确认前索取详情 | Runtime 拒绝；不读取任何历史详情 | 07 | `instance/relation-candidate.json` | 读了再不返回，内容已经加载，门形同虚设 |
| GRAG-11 | 拒绝候选 | 拒绝持久化，详情保持锁定 | 07 | `instance/relation-candidate-decision.json` | 只在界面消隐，换个标签页又出现，用户会认为决定不生效 |
| GRAG-12 | 用不匹配的候选/资产绑定确认 | Runtime 拒绝；不产生任何权限 | 07 | `instance/confirmed-asset-relation.json` | 用当前状态「修正」不匹配，等于依据用户对另一份内容做的决定授予访问 |
| GRAG-13 | 确认精确候选并读取详情 | 确定性双边证据卡，限定在被确认的那一个资产 | 08 | `instance/confirmed-asset-relation.json` | 无界读取把一次批准变成对那段历史的通用搜索 |
| GRAG-14 | 比对详情读取前后的持久化快照 JSON、语句哈希、卡片哈希 | 三者完全相同，且不追加当前内容版本 | 08 | `instance/knowledge-card-readiness.json` | 不会崩溃，只是资产悄悄获得了它没赚到的历史，且哈希与就绪绑定不再吻合 |
| GRAG-15 | 在候选、拒绝或确认之后重启 | SQLite 恢复同样的持久状态与权限 | 09 | `instance/discovery-attempt.json` | 把中断的预留当作成功会发布一个无人校验的候选 |
| GRAG-16 | 修正或删除任一被绑定的资产 | 投影与关系过期；候选/详情访问被撤销 | 09 | `instance/role-graph-projection-*.json` | 界面隐藏而权限仍在，重放请求或另一个标签页照样拿得到详情 |
| GRAG-17 | 通过 canonical 摘要文本尝试提示注入 | 文本仍是数据；不接受工具调用、范围扩大或额外字段 | 05 | `scenario/invalid-false-association.json` | 让模型自选范围后，Runtime 无法对照它从未提供的投影校验标识符 |
| GRAG-18 | 完成 no-match 或拒绝后继续 | M5 路由评估仍然可用 | 07 | `scenario/hard-negative-corpus.json` | 比较无果就卡住，会把一个可选的辅助步骤变成强制关卡 |

## 覆盖核对

| 票 | 拥有的 GRAG |
|---|---|
| 03 | 01, 02 |
| 05 | 03, 04, 05, 06, 17 |
| 06 | 07, 08, 09 |
| 07 | 10, 11, 12, 18 |
| 08 | 13, 14 |
| 09 | 15, 16 |
| 10 | 全部 18 条在公共缝上以确定性 fake 复跑 |
| 11 | 无（真模型门，验的是模型能否产出合法结构化提案，不是产品行为） |

18 条全部有归属，无重复。票 01、02、04 不拥有任何 GRAG 项：它们分别交付合同、M4 图与
投影，这些是上述行为的前提而不是行为本身。

## 与 fixture 的关系

`contracts/examples/e5/` 下的 fixture 由 `scripts/export_e5_fixtures.py` 生成，并由
`tests/unit/test_e5_fixtures.py` 逐份对冻结模型复验。一份悄悄漂移的 fixture 比缺失的
更糟：Wave-1 的 Agent 会照着一个后端永不接受的形状正确地构建，而错配要到真实生产方
落地时才暴露。
