# Skill Model

## 当前最小契约

Task 04.5C 建立了模型无关、不可变、无可执行回调的最小 Skill 边界：

```text
SkillDefinition
→ DeterministicSkillResolver
→ SkillContext
→ explicit analysis input
```

`SkillDefinition` 只描述当前有消费者的字段：

```text
skill_id
version
status: active | deprecated
supported_event_types
supported_asset_types
analysis_instructions
escalation_rules
knowledge_query_hints
```

`SkillContext` 是传入分析层的有界投影，包含 Skill 身份、版本、分析约束、
升级规则、知识查询提示和确定性解析原因。它不携带 Provider、数据库连接、
Python 回调、工具定义或模型路由策略。

## 确定性解析

当前 `DeterministicSkillResolver` 只读取已经存在的稳定 Event 字段：

- `event_type`；
- `metadata.asset_type`。

解析先检查字段匹配，再排除 deprecated Skill，并按实际命中的字段数量计算
specificity。唯一最高匹配才会产生 `SkillContext`；零匹配、仅 deprecated
匹配和同等 specificity 冲突都会显式失败。定义输入顺序、JSON 顺序和文件
顺序不会决定结果。当前没有通用 fallback，也不允许 LLM 选择 Skill。

## 分析集成

```text
Event
→ SkillResolver
→ SkillContext
→ KnowledgeQuery（合并有界 knowledge_query_hints）
→ KnowledgeRetriever
→ KnowledgeContext
→ ReliableAnalysisProvider
→ concrete AnalysisProvider
→ validated AnalysisResult
→ existing Decision Runtime
```

Skill Context 和 Knowledge Context 通过正式接口显式进入 Provider。Ollama
Prompt 将固定系统规则、Event、Skill Context、Knowledge Context 和输出契约
分段组织。Skill 与知识都不能覆盖强制人工确认、严格 JSON schema 或设备
控制禁令。

无匹配 Skill 时，Event 保持持久化并进入 `FAILED`，写入
`skill_resolution_failed` 审计记录；模型不会被调用，也不会创建 Decision。
未启用 SkillResolver 时，原有无 Skill 分析路径保持兼容。

## First validation skill

Food SOP 仍是验证通用 Runtime 闭环的第一个规则 Skill，不是 AlphaNoah 的
产品范围。其确定性温度规则、任务模板和复查行为保持在
`FoodColdHoldingSkill` 内，不进入通用 `SkillDefinition`。

阈值和数据均为合成演示内容，不是现实食品安全 SOP 或操作建议。

## Task 04.5C 演示定义

仓库包含两个可删除的合成声明式演示 Skill：

| Skill | 场景约束 | 明确边界 |
|---|---|---|
| `restaurant-aircon-shutdown` | 闭店空调、能耗、现场占用和值班复查 | 远程断电仅能作为待授权建议 |
| `industrial-equipment-shutdown` | 工业设备停机、残余能源、维护升级和适用的锁定挂牌指引 | 不指令未授权人员操作或隔离设备 |

它们使用相同 Runtime 和 Provider 边界，但产生不同的 Skill Context 和合成
Knowledge Context。它们不构成真实餐饮或工业合规能力，也不是正式
Equipment Skill。

## 当前与未来边界

| 分类 | 内容 |
|---|---|
| Implemented | 最小 Skill 契约、确定性解析、显式分析输入、审计身份/版本/解析原因 |
| Demo only | 两个合成 Skill 定义、合成知识和 CLI `--demo-skills` 开关 |
| Existing validation flow | Food SOP 确定性规则 Skill |
| Not implemented | 动态 Skill、Skill 市场、低代码编辑器、LLM Skill 选择、工具执行、远程注册表、完整 RAG、Embedding、Vector DB |

企业落地前，Skill 指令和知识必须由现场负责人、安全负责人及相应领域人员
审查。当前演示规则不能替代真实企业 SOP、法规判断或授权操作程序。
