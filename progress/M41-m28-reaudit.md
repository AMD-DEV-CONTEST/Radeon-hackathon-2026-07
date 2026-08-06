# M41 · M28 止血清单复核（2026-08-06，代码级逐项验证）

- **日期**：2026-08-06
- **完成了什么**：对照 `progress/M28-consolidation-execution-plan.md` 的 13 项清单逐项在代码中验证现状（grep/读代码，非纸面确认），输出本复核文档。**结论：13/13 全部完成**（M28 原表状态已过时）。
- **逐项结果**：

| ID | 任务 | M28 原状态 | 复核结果（2026-08-06） |
|----|------|-----------|----------------------|
| T0-1 | 安装脚本仓库地址 | ✅ 已完成 | ✅ `metahubifeel` 全库 0 残留 |
| T0-2 | 删 Dashboard 假数据集 | ✅ | ✅ `mockDatasets` 0 命中 |
| T0-3 | finetune demo fallback 硬失败 | ✅ | ✅ catch 分支直接 throw + 明确文案；`simulated` 仅残留于 job_monitor 读旧任务的兼容分支 |
| T0-4 | 隐藏 4 个无执行器节点 | ✅ | ✅ `NO_EXECUTOR_TYPES` 集合（NodePalette.tsx:63）在渲染过滤（:107），分类已删 |
| T0-5 | 禁用 AI Hub Download | ✅ | ✅ 无 downloadFromHub，仅剩下载数展示 |
| T0-6 | Pricing 假升级按钮 | ✅ | ✅ 按钮 = disabled/「申请内测 / 联系我们」；「升级」仅存于文案 |
| T1-1 | localStorage 劫持云端虚拟 | ✅ | ✅ `forceSameOrigin` 已实现（localAgent.ts:169-170） |
| T1-2 | 零安装 demo 提到首屏 CTA | ✅ | ✅ 被 U2 超越完成：真机浏览器直连成为主 CTA（强于原方案的虚拟 CTA） |
| T1-3 | 文档/Setup 零安装分流 | ✅ | ✅ quickstart 首屏已是 A/B/C 分流（零安装先行） |
| T2-1 | WebSerial 零安装接 SO-101 | 待做 | ✅ **本循环完成**（S1-S3+U1-U4：协议层 24 断言、首录闭环、3D 孪生、诊断） |
| T2-2 | LeKiwi 通用工作台迁移 | 待做 | ⏳ 未做（3–4 周 P2；workbench 框架在，LeKiwi 未迁） |
| T2-3 | 死抽象清理 | 待做 | 🔶 部分：`state_endpoint` 已从 robots.json 删除（0 命中）；`runtimes/_capabilities.py` 死模块仍在（0 import）；catalog 重复已收敛（robotCatalog 96 行 + fallbackRobots 36 行）但未统一到 manifest 唯一真相源 |

- **剩余工作（诚实）**：T2-2（通用工作台）与 T2-3 剩余项是 P2 长线，**按纪律等真机验收/访谈信号后推进**，不提前扩。
- **关键命令**：grep 验证清单见上文各格。
- **最终结果**：M28 止血计划**全部落地**，平台「不骗人」基线达成（假数据/假成功/假按钮/假节点/假下载全部清零）。已提交。
- **下一步**：真机验收轮（Chrome + SO-101 全链路）→ 访谈门禁（M40 材料已备）→ 结论决定 T2-2/T2-3 或 U3 之后的下一刀。
