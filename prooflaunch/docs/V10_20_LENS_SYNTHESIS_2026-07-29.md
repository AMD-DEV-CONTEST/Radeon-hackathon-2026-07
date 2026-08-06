# Cortex-X V10：20 个公开机制镜头的可证伪综合

**冻结日期：** 2026-07-29  
**用途：** 将 10 位研究代表与 10 位 AI 产品/技术代表的公开工作，转译成 ProofLaunch 的架构约束、产品机制和淘汰条件。

## 先说清楚边界

这些名字是“公开机制镜头”，不是虚构圆桌，也不是名人背书。本文不声称他们参与、认可或评价过 ProofLaunch；只引用其公开论文、开源项目或官方产品机制。冲突观点不会被平均成一句口号，而会落成对照实验。

## 10 个研究者机制镜头

| ID | 公开代表 | 可迁移机制 | 在 ProofLaunch 的落点 | 必须击败的反证/淘汰条件 |
|---|---|---|---|---|
| R01 | 梁文锋 / DeepSeek 研究团队 | 稀疏专家、共享专家、负载平衡与系统—模型协同；借机制，不借规模结论 | BT30 稀疏 Adapter Router；单 Radeon 只激活 top-2；通用 Adapter 永久兜底 | 专家路由坍塌、峰值显存越界、通用回归 >0.5%，立即淘汰 |
| R02 | Yann LeCun | 在抽象潜空间预测未来并规划，而非执着逐像素预测 | BT26 action-conditioned Campaign World Model；最多 8 分支、3 层深度 | 三步预测、策略盲评或校准任一不过门，退回确定性 V9 |
| R03 | Demis Hassabis / AlphaEvolve 团队 | 候选生成器 + 自动评价器 + 进化搜索；评价器决定搜索是否有意义 | BT26/BT27/BT32 的候选搜索、Genome 变异和局部修复 | 若搜索只学会攻击 Judge、对冻结基线无增益或成本失控，封存 |
| R04 | Andrew Ng | Reflection、Tool Use、Planning、Multi-Agent 必须由 eval 和错误分析驱动 | BT29 单 Supervisor 编排与 BT31 rich-feedback 修复环 | 没有逐类错误账本、20–50 条回放或增量改善时，不增加 Agent |
| R05 | Percy Liang | 透明、可复现、多场景、多指标、明确未覆盖范围的整体评测 | 28 项 V10 质量门、五条冻结基线、原始输出与失败证据 | 任何“总分掩盖硬失败”、缺原始输出或不可复现结果均不得晋级 |
| R06 | Fei-Fei Li | 空间智能要求模型理解对象、区域、关系和可行动环境 | BT32 Region-Time Tensor、BT36 空间化 Campaign Canvas | 像素/帧定位弱、局部编辑破坏身份或只剩聊天框，产品突破失败 |
| R07 | Tri Dao | IO-aware：真实瓶颈是数据移动和内存层级，不只看 FLOPs | 单卡训练的冻结塔、top-2 Adapter、分块 4K 修复和峰值显存门 | 没有 Radeon 实测的延迟/VRAM 改善，不得把理论效率写成结果 |
| R08 | Shunyu Yao | 推理与行动交替；外部行动带回的新证据必须更新计划 | BT34 direct/retrieve/search/simulate/team/human 路由与工具 trace | 未引用证据的动作、不可重放工具调用或隐藏失败均为硬失败 |
| R09 | Chelsea Finn | 元学习的价值是少量新数据下快速、稳定适配 | BT30 角色 Adapter 与 BT33 跨 Campaign 记忆迁移 | 少样本没有正迁移或出现灾难性遗忘/污染，关闭持续写入 |
| R10 | Yoshua Bengio | Scientist AI 式假设、世界模型、不确定性和可证伪推断 | 12 个 BreakthroughBetSpec、Twin 区间、负控制与 HOLD/REJECT 状态 | 不能表述不确定性、不能发现反例或把模拟写成事实，直接拒绝 |

## 10 个 AI 产品与技术机制镜头

| ID | 公开代表 | 可迁移机制 | 在 ProofLaunch 的落点 | 必须击败的反证/淘汰条件 |
|---|---|---|---|---|
| P01 | Dylan Field / Figma 产品团队 | 代码—画布双向、设计系统上下文、并行探索、直接操纵 | BT36 Campaign Operating Space；资产、证据和状态必须是可编辑对象 | 输出只能复制文本、设计与代码漂移或没有 token/component 约束则失败 |
| P02 | Scott Belsky / Adobe GenStudio 团队 | 计划→创建→审批→激活→报告是一条内容供应链 | Brief/Evidence/Twin/Genome/Asset/Proof/Experiment 统一对象流 | 若创作、合规、投放和效果仍靠文件搬运，不能称为 GTM 员工 |
| P03 | Guillermo Rauch / Vercel AI 团队 | 审批、durability、timeout、sandbox、eval harness、telemetry 是运行时原语 | 单 Supervisor、幂等节点、工具超时、审批节点、OpenTelemetry 字段 | 重放造成重复副作用、工具挂死无降级或无 trace，生产门失败 |
| P04 | Dharmesh Shah / HubSpot Breeze 团队 | CRM/意图信号应直接驱动研究、个性化、会议和 pipeline 行动 | GTM 对象绑定受众、账户、信号、报价、渠道和 OutcomeEvent | 没有来源时仍输出个性化事实，或只生成泛化 campaign，失败 |
| P05 | Harrison Chase / LangChain 团队 | Agent Development Lifecycle；持久执行和人在回路不是后补丁 | 长任务 checkpoint、interrupt、resume、replay-safe task | 崩溃不能恢复、批准恢复后重复写入或人工边界不清，失败 |
| P06 | Satya Nadella / Microsoft Copilot Studio 团队 | 专家 Agent 可跨数据与工具协作，但必须有治理、身份与统一体验 | BT29 动态 Agency：唯一状态所有者、角色权限、A2A 只作协议边界 | 无约束 swarm、重复工作、身份/权限不可审计或用户看到多头结论，淘汰 |
| P07 | Sam Altman / OpenAI Agents 产品团队 | 长时任务需要受控 sandbox、工具、memory、trace，并承认 computer-use 仍需监督 | 沙箱化工具契约、高风险动作人工批准、长任务证据收据 | 无沙箱、无审批或用研究预览可靠性冒充生产可靠性，失败 |
| P08 | Amjad Masad / Replit Agent 团队 | 稳定里程碑自动 checkpoint；每次重大改动可解释并可回滚 | BT36 append-only snapshot、fork、merge、rollback 与成本记录 | 不能从已验证状态恢复或 checkpoint 不含变更范围，失败 |
| P09 | Bret Taylor / Sierra 团队 | 原子单位从一次聊天变成长周期业务过程；上下文与结果形成产品壁垒 | BT33 记忆、BT35 实验、Outcome War Room 和结果计价思维 | 只优化 token/会话，不验证业务结果或记忆不可删除，失败 |
| P10 | Nitasha Chopra / Copilot Studio 产品团队 | 多 Agent 只有在复用专家能力、共享上下文并保持主界面连贯时才有价值 | Agency Map 只显示目标、状态、依赖和预算；不暴露内部思维链 | 协调成本 >15%、用户认知负担上升或子 Agent 直接争抢用户，失败 |

## 综合后形成的 8 条非传统顶层决策

1. **产品主对象不是聊天记录。** 主对象是可 fork、merge、time-travel、审计的 Campaign 状态图；聊天只是一种输入通道。
2. **模拟不是看板装饰。** Twin 和 World Model 只能输出 predicted/simulated；一键转成可随机化的实验假设，不能直接转成“收入提升”。
3. **Agent 数量不是先进性。** 单一 Supervisor 持有权威状态；只有 value-of-parallelism 为正且在预算内才创建 bounded specialist。
4. **4K 不是尺寸声明。** 正式母版必须同时过 OCR、色差、产品身份、时序、音画对齐、权利、批准和 Claim locator。
5. **训练不以“训过”为成功。** 六阶段计划每阶段都需独立接受/回滚；没有审计语料与 Radeon trace 就保持 planned/blocked。
6. **研究失败可以完成，营销失败不能伪装。** 12 个赌注均需证据；失败写入负结果并退出主路径，至少 3 个同时过 T/P/X 才谈 V10 晋级。
7. **评价器先被评价。** Judge 至少 100 个人类标签且 TPR/TNR 均严格高于 80%；4A 结论必须来自至少 5 位独立评审。
8. **每个惊艳细节都有反证。** 任何交互、模型或视觉突破都同时声明基线、阈值、失败样本、成本、回滚和不能外推的范围。

## 一手来源

- DeepSeek-V3: https://github.com/deepseek-ai/DeepSeek-V3
- V-JEPA 2: https://ai.meta.com/research/vjepa/
- AlphaEvolve: https://deepmind.google/blog/alphaevolve-impact/
- Andrew Ng Agentic AI: https://www.deeplearning.ai/the-batch/check-out-our-course-on-how-to-build-ai-agents
- HELM: https://crfm.stanford.edu/helm/index.html
- Fei-Fei Li spatial intelligence briefing: https://hai.stanford.edu/assets/files/fei-fei-li-un-security-council-briefing.pdf
- FlashAttention: https://arxiv.org/abs/2205.14135
- ReAct: https://arxiv.org/abs/2210.03629
- MAML: https://arxiv.org/abs/1703.03400
- Scientist AI: https://arxiv.org/abs/2502.15657
- Figma design agent: https://www.figma.com/blog/the-figma-agent-is-here/
- Adobe GenStudio concepts: https://experienceleague.adobe.com/en/docs/genstudio-for-performance-marketing/user-guide/intro/concepts
- Vercel AI SDK 7: https://vercel.com/blog/ai-sdk-7
- HubSpot Breeze sales use cases: https://www.hubspot.com/products/artificial-intelligence/use-cases/sales
- LangChain Agent Development Lifecycle: https://www.langchain.com/blog/the-agent-development-lifecycle
- Microsoft multi-agent orchestration: https://www.microsoft.com/en-us/microsoft-copilot/blog/copilot-studio/new-and-improved-multi-agent-orchestration-connected-experiences-and-faster-prompt-iteration/
- OpenAI Agents SDK sandbox: https://openai.com/index/the-next-evolution-of-the-agents-sdk/
- Replit checkpoints and rollbacks: https://docs.replit.com/references/version-control/checkpoints-and-rollbacks
- Sierra Horizon: https://sierra.ai/blog/horizon
- Copilot Studio 2026 capabilities: https://www.microsoft.com/en-us/microsoft-copilot/blog/copilot-studio/6-core-capabilities-to-scale-agent-adoption-in-2026/

