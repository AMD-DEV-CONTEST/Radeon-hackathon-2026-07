# Case Log: 文件意图约束泛化修复

## Intent

Goal: 修复真实用户查询在清单、存在性与单文件定位之间发生语义串线的问题，并避免只针对已知句式打补丁。

Success criteria:
- 相似文件存在时，缺失的主题与文档角色交集必须返回 `no_match`
- 清单、否定、alternatives、年份和实验编号在逐文件边界上生效
- 既有私有评测的召回、拒答和自动选择安全性不退化

Risk: medium，涉及共享检索与用户可见决策行为。

## Root Cause

- 清单识别仅覆盖少数固定词，口语化“列一下”“都找出来”等被误判为单文件定位。
- 主题和文件角色硬约束只在个别分支中执行，普通定位仍可能让近似候选越权成为答案。
- 年份与强实体检查拼接了所有候选，低位候选可以替第一名提供证据。
- 否定作用域没有跨越“Word 自动”“期末”等修饰语，导致备份和试卷反而被解析为必需角色。
- 备份角色使用全文判断，正文中的 `copy` 被误认为文件副本。

## Changes

- `IntentPlan` 新增 request mode、topic operator、excluded topics、required/excluded roles。
- 模型意图编译器可以补充召回语义，但不能覆盖确定性硬约束。
- 混合检索先宽召回，再逐文件检查课程主题、角色、排除项、年份、编号与项目标识。
- alternatives 使用 `any`；普通合取使用 `all`；课程域主题是硬边界，细粒度回忆用于排序。
- 备份、模板、试卷等排除角色只依据文件元数据，不再扫描整篇正文。
- 课程简称与课程身份词独立维护；`CPU`、`SQL`、线程等技术扩展词只参与召回，不能证明候选属于某门课程。
- “课设报告/课程设计报告”使用独立文档角色，默认排除模板、指导书、必备知识和跨课程报告；缺少完成版时明确 `no_match`。
- 新增独立合成对抗集，覆盖口语清单、缺失交集、否定、alternatives、错误年份和错误编号。

## Verification

- `python -m unittest discover -s tests -t . -q`: 75 tests passed。
- `python -m py_compile core.py api.py app.py scripts/private_retrieval_check.py`: passed。
- 仓库外 60 条私有清单：37/37 single-target Top-1、40/40 Recall@5、3/3 multi-target full coverage、12/12 no-answer、100% auto-selection precision、0 unsafe wrong auto-selections。
- 私有查询、文件名、路径、正文和完整报告未写入仓库。

## Reusable Lessons

- 相似度只能决定“召回谁”，不能证明“约束已满足”。自动选择前必须逐候选验证，而不是在候选集合之间借证。
- 否定词解析必须考虑修饰语和复合文件角色；文件版本角色应优先看元数据，正文术语不能决定它是不是备份。
- 修复真实失败后必须同时运行独立对抗集和冻结私有清单，否则很容易用拒答率换掉召回率。

## Residual Risk

- 当前私有清单仍是 analyst-reviewed private-alpha labels，不等同于 owner-approved gold corpus。
- 本次本地门禁验证的是确定性检索路径；Radeon Cloud 上的 LoRA、BGE、reranker 和 Qwen3-14B 端到端路径仍需用同一冻结清单复跑。
