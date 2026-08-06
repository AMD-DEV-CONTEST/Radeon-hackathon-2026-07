ProofLaunch Cortex-X V9：1200 项蒸馏优先、全球 Top-3 目标的下一代 4A GTM 员工计划
一、不可妥协原则
1. 不重复造轮子
任何新代码开始前必须经过 Reuse-or-Justify Gate：
搜索成熟上游实现。
核验 revision、许可证、维护状态、ROCm 可行性。
在同一输入和硬件上 smoke/benchmark。
能以 Adapter、Wrapper、Workflow 或 Patch 复用就禁止重写。
只有上游无法满足 Campaign World Model、跨 Agent 信用、4A 失败归因或 Radeon 约束时才允许原创。
原创部分必须说明“现有轮子为什么不够”和可证伪收益。
对上游的 AMD/ROCm 修复优先提交上游 PR。
直接吸收的底座包括：
图像：[FLUX.2 Klein](https://github.com/black-forest-labs/flux2)、Grounding DINO、SAM2.1、Real-ESRGAN、SwinIR。
视频：[Wan2.2](https://github.com/Wan-Video/Wan2.2)、LTX-Video、[SeedVR2](https://github.com/IceClear/SeedVR2)、[rCM](https://github.com/NVlabs/rcm)、[Causal Forcing](https://github.com/thu-ml/Causal-Forcing)。
训练：[ms-swift](https://github.com/modelscope/ms-swift)、Transformers、PEFT、TRL、EvalScope。
Agent：LangGraph、Agent-R1 的 Step-level MDP、MATPO/MARTI 的多角色训练思想。
蒸馏：[OPSD](https://github.com/siyan-zhao/OPSD)、TRL Distillation Trainer、GKD、TCOD、SDFT。
4K：直接复用 SeedVR2 一步修复、ComfyUI 成熟 workflow 思路和 FFmpeg mastering，不重新发明超分算法。
2. 五层蒸馏
Model Distillation：教师 logits、特征、偏好和校准蒸馏。
Agent Distillation：规划、工具选择、轨迹、停止策略和失败归因蒸馏。
Workflow Distillation：把成熟 GitHub 工作流压缩为可测试的 typed capability。
Creative Distillation：把 4A 专家对 Brief、Big Idea、Art、Copy 的判断蒸馏为 Agency Critic。
Visual Distillation：把产品、Logo、文字、安全区和时间区域级质量蒸馏为局部奖励。
特别采用 2026 年研究结论：
OPSD 可提高 token 效率，但长推理 privileged distillation 可能压制回溯和自纠正；必须监控高熵分叉 token。[Rethinking OPSD](https://arxiv.org/abs/2607.05184)
On-policy distillation 必须诊断教师/学生思维兼容性和教师新增信息量，不能盲目 KL 拟合。[OPD Dynamics](https://github.com/thunlp/OPD)
多轮 Agent 采用时间课程，避免长轨迹 KL 失稳。[TCOD](https://github.com/kokolerk/TCOD)
视频采用 step distillation、cache/trajectory optimization 和一致性蒸馏思想；不在单卡上重训 10B 模型。[Efficient Video Diffusion](https://arxiv.org/abs/2604.15911)
3. 每个 TODO 的 D/A/I/E 关闭标准
以下 1200 项全部适用 [D/A/I/E]：
D — Distillation：记录复用/蒸馏的上游、revision、教师、输入输出及没有重写什么。
A — Academic：记录对应论文假设、对照组和可证伪指标。
I — Innovation：记录相对传统方案新增的机制及弯道超车理由。
E — Evidence：必须存在代码、测试、数据、指标、截图、Radeon trace 或负实验报告。
任一字段为空，TODO 不得标记完成。实验被证伪可以完成 TODO，但不得进入最终产品。
二、全球 Top-3 与 4A 终极验收
五名合格评审的 4A 总分平均 ≥4.7/5，任一维度 ≥4.5。
无重大修改 publishable rate ≥95%。
相对三个最强可执行开放基线，人类偏好胜率 ≥75%，95% Wilson 下界 >65%。
冻结 GTM Multimodal Bench 相对 Base 提升 ≥35%。
通用多模态能力绝对回归 ≤1%。
Agent 端到端成功率 ≥97%，工具误调用率 <0.5%。
轨迹未来状态预测准确率 ≥92%，失败归因 Top-1 ≥90%。
结构化输出合法率 ≥99.8%。
Critical unsupported Claim 为 0；全部 Claim 定位覆盖率 100%。
记忆检索 precision ≥97%，过期事实召回率 0。
最多两轮修复后的 Release Pass ≥99%。
OCR ≥99.9%，品牌色 ΔE2000 ≤1.5，产品/Logo 身份通过率 ≥99%。
三段视频时间一致性相对逐帧超分基线改善 ≥20%，A/V alignment ≥0.93。
所有核心推理、生成、增强和审计均提供真实 Radeon + ROCm 证据。
“全球 Top-3”只能作为通过以上第三方对照后的结果表述，不能靠内部自评直接宣称。
三、1200 项 D/A/I/E TODO
Workstream 01 — 官方赛制与 Top-3 证据契约

0001 [D/A/I/E] 冻结赛道一报名资格。

0002 [D/A/I/E] 冻结团队人数限制。

0003 [D/A/I/E] 冻结 AMD Developer Program 要求。

0004 [D/A/I/E] 冻结官方截止时间。

0005 [D/A/I/E] 冻结官方 fork 要求。

0006 [D/A/I/E] 冻结官方 PR 要求。

0007 [D/A/I/E] 冻结 Radeon GPU 要求。

0008 [D/A/I/E] 冻结 ROCm 要求。

0009 [D/A/I/E] 冻结核心本地推理要求。

0010 [D/A/I/E] 冻结闭源 API 禁止边界。

0011 [D/A/I/E] 冻结允许的开源模型范围。

0012 [D/A/I/E] 冻结 LoRA 允许范围。

0013 [D/A/I/E] 冻结 ControlNet 允许范围。

0014 [D/A/I/E] 冻结蒸馏模型允许范围。

0015 [D/A/I/E] 冻结完整源码要求。

0016 [D/A/I/E] 冻结 README 要求。

0017 [D/A/I/E] 冻结 PDF 要求。

0018 [D/A/I/E] 冻结 3–5 分钟视频要求。

0019 [D/A/I/E] 冻结海报/PPT 要求。

0020 [D/A/I/E] 建立赛制机器可读 schema。

0021 [D/A/I/E] 建立赛制逐项 evidence locator。

0022 [D/A/I/E] 建立 40 分工作流门。

0023 [D/A/I/E] 建立 20 分创新门。

0024 [D/A/I/E] 建立 20 分价值门。

0025 [D/A/I/E] 建立 20 分 Radeon 门。

0026 [D/A/I/E] 定义 100 分自检算法。

0027 [D/A/I/E] 设定自检最低 95 分。

0028 [D/A/I/E] 建立评分证据不可变清单。

0029 [D/A/I/E] 定义实体电商演示输入。

0030 [D/A/I/E] 定义 AI Agent 演示输入。

0031 [D/A/I/E] 定义完整 Campaign Pack。

0032 [D/A/I/E] 定义快速实时 Demo Pack。

0033 [D/A/I/E] 定义 4K mastering 表述。

0034 [D/A/I/E] 禁止原生 4K 虚假表述。

0035 [D/A/I/E] 定义 Top-3 比较对象选择法。

0036 [D/A/I/E] 定义 Top-3 重叠任务集。

0037 [D/A/I/E] 定义不可比较功能标记。

0038 [D/A/I/E] 定义基线运行预算。

0039 [D/A/I/E] 定义人类盲评协议。

0040 [D/A/I/E] 定义基线匿名化协议。

0041 [D/A/I/E] 定义随机展示顺序。

0042 [D/A/I/E] 定义 Wilson 区间算法。

0043 [D/A/I/E] 定义 publishable 判定。

0044 [D/A/I/E] 定义重大返工判定。

0045 [D/A/I/E] 定义评分冲突仲裁。

0046 [D/A/I/E] 建立虚假领先声明扫描。

0047 [D/A/I/E] 建立最终 Claim approval。

0048 [D/A/I/E] 建立提交前资格检查。

0049 [D/A/I/E] 建立提交前材料检查。

0050 [D/A/I/E] 冻结 Competition Contract V3。
Workstream 02 — 全球开源轮子吸收与魔改治理

0051 [D/A/I/E] 建立上游项目总目录。

0052 [D/A/I/E] 建立模型类目录。

0053 [D/A/I/E] 建立训练类目录。

0054 [D/A/I/E] 建立 Agent 类目录。

0055 [D/A/I/E] 建立图像类目录。

0056 [D/A/I/E] 建立视频类目录。

0057 [D/A/I/E] 建立超分类目录。

0058 [D/A/I/E] 建立分割类目录。

0059 [D/A/I/E] 建立 OCR 类目录。

0060 [D/A/I/E] 建立音频类目录。

0061 [D/A/I/E] 建立评测类目录。

0062 [D/A/I/E] 建立营销 Agent 目录。

0063 [D/A/I/E] 固定 FLUX.2 revision。

0064 [D/A/I/E] 固定 Wan2.2 revision。

0065 [D/A/I/E] 固定 LTX-Video revision。

0066 [D/A/I/E] 固定 SeedVR2 revision。

0067 [D/A/I/E] 固定 Real-ESRGAN revision。

0068 [D/A/I/E] 固定 SwinIR revision。

0069 [D/A/I/E] 固定 Grounding DINO revision。

0070 [D/A/I/E] 固定 SAM2.1 revision。

0071 [D/A/I/E] 固定 SigLIP2 revision。

0072 [D/A/I/E] 固定 CLAP revision。

0073 [D/A/I/E] 固定 ms-swift revision。

0074 [D/A/I/E] 固定 PEFT revision。

0075 [D/A/I/E] 固定 TRL revision。

0076 [D/A/I/E] 固定 LangGraph revision。

0077 [D/A/I/E] 固定 Agent-R1 revision。

0078 [D/A/I/E] 固定 MATPO revision。

0079 [D/A/I/E] 固定 MARTI revision。

0080 [D/A/I/E] 固定 OPSD revision。

0081 [D/A/I/E] 固定 TCOD revision。

0082 [D/A/I/E] 固定 rCM revision。

0083 [D/A/I/E] 固定 Causal Forcing revision。

0084 [D/A/I/E] 记录所有上游许可证。

0085 [D/A/I/E] 记录所有上游硬件假设。

0086 [D/A/I/E] 记录所有 CUDA-only 部分。

0087 [D/A/I/E] 记录所有 ROCm-ready 部分。

0088 [D/A/I/E] 建立最小 smoke 脚本。

0089 [D/A/I/E] 建立统一 adapter interface。

0090 [D/A/I/E] 禁止直接散落上游调用。

0091 [D/A/I/E] 建立 upstream patch 目录。

0092 [D/A/I/E] 建立 patch 来源说明。

0093 [D/A/I/E] 建立 patch 回归测试。

0094 [D/A/I/E] 建立替换上游的迁移测试。

0095 [D/A/I/E] 建立上游健康度评分。

0096 [D/A/I/E] 建立维护停止回退。

0097 [D/A/I/E] 建立 wheel-vs-build 基准。

0098 [D/A/I/E] 建立重复代码扫描。

0099 [D/A/I/E] 每个新模块执行复用审查。

0100 [D/A/I/E] 冻结 Reuse Manifest V1。
Workstream 03 — 2026 学术雷达与可证伪创新

0101 [D/A/I/E] 建立论文证据注册表。

0102 [D/A/I/E] 保存论文版本日期。

0103 [D/A/I/E] 保存官方实现链接。

0104 [D/A/I/E] 保存实验硬件规模。

0105 [D/A/I/E] 保存原始任务范围。

0106 [D/A/I/E] 保存已知失败模式。

0107 [D/A/I/E] 解构统一多模态预训练。

0108 [D/A/I/E] 解构 RAE 统一视觉表征。

0109 [D/A/I/E] 解构多模态数据协同。

0110 [D/A/I/E] 解构 world-model emergence。

0111 [D/A/I/E] 解构 modality-specialized MoE。

0112 [D/A/I/E] 解构 TraceR1。

0113 [D/A/I/E] 解构 Agent-R1。

0114 [D/A/I/E] 解构 M3-Agent。

0115 [D/A/I/E] 解构 NS-Mem。

0116 [D/A/I/E] 解构 TaskMem。

0117 [D/A/I/E] 解构 SAGE。

0118 [D/A/I/E] 解构 MATPO。

0119 [D/A/I/E] 解构 MARTI。

0120 [D/A/I/E] 解构 Test-Time Scaling。

0121 [D/A/I/E] 解构 ViPO。

0122 [D/A/I/E] 解构 OPSD。

0123 [D/A/I/E] 解构 OPSD 失败报告。

0124 [D/A/I/E] 解构 OPD Dynamics。

0125 [D/A/I/E] 解构 SDFT。

0126 [D/A/I/E] 解构 TCOD。

0127 [D/A/I/E] 解构 CaOPD。

0128 [D/A/I/E] 解构 SDPO。

0129 [D/A/I/E] 解构 rCM。

0130 [D/A/I/E] 解构 Causal Forcing。

0131 [D/A/I/E] 解构 SeedVR2。

0132 [D/A/I/E] 建立直接采用清单。

0133 [D/A/I/E] 建立等价简化清单。

0134 [D/A/I/E] 建立消融实验清单。

0135 [D/A/I/E] 建立不可行清单。

0136 [D/A/I/E] 为每项研究写假设。

0137 [D/A/I/E] 为每项假设写对照。

0138 [D/A/I/E] 为每项假设写指标。

0139 [D/A/I/E] 为每项假设写预算。

0140 [D/A/I/E] 为每项假设写停止条件。

0141 [D/A/I/E] 禁止只有主观样例的实验。

0142 [D/A/I/E] 禁止使用论文宣传分数代替复现。

0143 [D/A/I/E] 建立负实验仓库。

0144 [D/A/I/E] 建立研究结果排行榜。

0145 [D/A/I/E] 建立证据强度等级。

0146 [D/A/I/E] 建立可迁移性评分。

0147 [D/A/I/E] 建立单卡适配评分。

0148 [D/A/I/E] 建立商业价值评分。

0149 [D/A/I/E] 建立创新组合选择器。

0150 [D/A/I/E] 冻结 Research Ledger V1。
Workstream 04 — 五层蒸馏总架构

0151 [D/A/I/E] 定义 DistillationEpisodeV1。

0152 [D/A/I/E] 定义教师身份字段。

0153 [D/A/I/E] 定义学生身份字段。

0154 [D/A/I/E] 定义 privileged context。

0155 [D/A/I/E] 定义 deployment context。

0156 [D/A/I/E] 定义 teacher revision。

0157 [D/A/I/E] 定义 student revision。

0158 [D/A/I/E] 定义 token signal。

0159 [D/A/I/E] 定义 feature signal。

0160 [D/A/I/E] 定义 reward signal。

0161 [D/A/I/E] 定义 trajectory signal。

0162 [D/A/I/E] 定义 region signal。

0163 [D/A/I/E] 定义 workflow signal。

0164 [D/A/I/E] 定义 uncertainty signal。

0165 [D/A/I/E] 建立模型 logits 蒸馏。

0166 [D/A/I/E] 建立 hidden feature 蒸馏。

0167 [D/A/I/E] 建立视觉 crop 蒸馏。

0168 [D/A/I/E] 建立 layout 蒸馏。

0169 [D/A/I/E] 建立视频时间蒸馏。

0170 [D/A/I/E] 建立 Agent 计划蒸馏。

0171 [D/A/I/E] 建立 Agent 工具蒸馏。

0172 [D/A/I/E] 建立 Agent 停止蒸馏。

0173 [D/A/I/E] 建立失败归因蒸馏。

0174 [D/A/I/E] 建立 4A Critique 蒸馏。

0175 [D/A/I/E] 建立审计修复蒸馏。

0176 [D/A/I/E] 建立成熟 workflow 蒸馏。

0177 [D/A/I/E] 建立教师质量门。

0178 [D/A/I/E] 建立教师新增信息门。

0179 [D/A/I/E] 建立师生思维兼容门。

0180 [D/A/I/E] 建立 top-k overlap 诊断。

0181 [D/A/I/E] 建立 token advantage 诊断。

0182 [D/A/I/E] 建立 high-entropy fork 诊断。

0183 [D/A/I/E] 保护 reconsideration token。

0184 [D/A/I/E] 保护 verification token。

0185 [D/A/I/E] 保护 backtracking token。

0186 [D/A/I/E] 对 style-token KL 裁剪。

0187 [D/A/I/E] 校准 privileged-context 差异。

0188 [D/A/I/E] 监控学生过度自信。

0189 [D/A/I/E] 建立 CaOPD 对照。

0190 [D/A/I/E] 建立离线 KD 对照。

0191 [D/A/I/E] 建立 on-policy KD 对照。

0192 [D/A/I/E] 建立 self-KD 对照。

0193 [D/A/I/E] 建立无 KD 对照。

0194 [D/A/I/E] 计算能力保留率。

0195 [D/A/I/E] 计算校准误差。

0196 [D/A/I/E] 计算 token 效率。

0197 [D/A/I/E] 计算训练墙钟收益。

0198 [D/A/I/E] 淘汰无新增信息教师。

0199 [D/A/I/E] 导出 Distillation Card。

0200 [D/A/I/E] 冻结 Distillation Stack V1。
Workstream 05 — Campaign World Model

0201 [D/A/I/E] 定义 Campaign state。

0202 [D/A/I/E] 定义 Evidence state。

0203 [D/A/I/E] 定义 Audience state。

0204 [D/A/I/E] 定义 Market state。

0205 [D/A/I/E] 定义 Brand state。

0206 [D/A/I/E] 定义 Creative state。

0207 [D/A/I/E] 定义 Asset state。

0208 [D/A/I/E] 定义 Channel state。

0209 [D/A/I/E] 定义 Risk state。

0210 [D/A/I/E] 定义 Memory state。

0211 [D/A/I/E] 定义 Uncertainty state。

0212 [D/A/I/E] 定义 Cost state。

0213 [D/A/I/E] 定义合法动作。

0214 [D/A/I/E] 定义非法动作。

0215 [D/A/I/E] 定义状态转移。

0216 [D/A/I/E] 定义终止状态。

0217 [D/A/I/E] 定义阻塞状态。

0218 [D/A/I/E] 定义人工审批状态。

0219 [D/A/I/E] 定义研究动作。

0220 [D/A/I/E] 定义规划动作。

0221 [D/A/I/E] 定义创意动作。

0222 [D/A/I/E] 定义生成动作。

0223 [D/A/I/E] 定义审计动作。

0224 [D/A/I/E] 定义修复动作。

0225 [D/A/I/E] 定义回退动作。

0226 [D/A/I/E] 建立 next-state predictor。

0227 [D/A/I/E] 建立 risk predictor。

0228 [D/A/I/E] 建立 quality predictor。

0229 [D/A/I/E] 建立 cost predictor。

0230 [D/A/I/E] 建立 uncertainty predictor。

0231 [D/A/I/E] 生成三条未来轨迹。

0232 [D/A/I/E] 建立 counterfactual rollout。

0233 [D/A/I/E] 建立 Pareto 轨迹选择。

0234 [D/A/I/E] 建立预期 4A value。

0235 [D/A/I/E] 建立预期风险 value。

0236 [D/A/I/E] 建立预期延迟 value。

0237 [D/A/I/E] 建立预期多样性 value。

0238 [D/A/I/E] 建立状态哈希链。

0239 [D/A/I/E] 建立状态 diff。

0240 [D/A/I/E] 建立状态 replay。

0241 [D/A/I/E] 建立状态压缩。

0242 [D/A/I/E] 建立状态可视化。

0243 [D/A/I/E] 校准状态预测。

0244 [D/A/I/E] 记录预测与实际偏差。

0245 [D/A/I/E] 将偏差转困难样本。

0246 [D/A/I/E] 区分世界模型错。

0247 [D/A/I/E] 区分执行器错。

0248 [D/A/I/E] 区分数据错。

0249 [D/A/I/E] 评测未来状态准确率。

0250 [D/A/I/E] 冻结 World Model V1。
Workstream 06 — 动态 Agent 拓扑

0251 [D/A/I/E] 禁用固定 Persona 群聊。

0252 [D/A/I/E] 定义 Capability Policy。

0253 [D/A/I/E] 定义 Evidence capability。

0254 [D/A/I/E] 定义 Audience capability。

0255 [D/A/I/E] 定义 Competition capability。

0256 [D/A/I/E] 定义 Strategy capability。

0257 [D/A/I/E] 定义 Creative capability。

0258 [D/A/I/E] 定义 Copy capability。

0259 [D/A/I/E] 定义 Art capability。

0260 [D/A/I/E] 定义 Channel capability。

0261 [D/A/I/E] 定义 Production capability。

0262 [D/A/I/E] 定义 Compliance capability。

0263 [D/A/I/E] 定义 Experiment capability。

0264 [D/A/I/E] 定义 Critic capability。

0265 [D/A/I/E] 定义 Supervisor meta-policy。

0266 [D/A/I/E] 按任务熵激活 capability。

0267 [D/A/I/E] 按风险激活 reviewer。

0268 [D/A/I/E] 按冲突激活 arbiter。

0269 [D/A/I/E] 按低价值裁撤 worker。

0270 [D/A/I/E] 区分 width search。

0271 [D/A/I/E] 区分 depth search。

0272 [D/A/I/E] 区分 feedback search。

0273 [D/A/I/E] 研究阶段优先宽度。

0274 [D/A/I/E] 制作阶段优先深度。

0275 [D/A/I/E] 修复阶段优先反馈。

0276 [D/A/I/E] 建立共享事实黑板。

0277 [D/A/I/E] 禁止共享隐式推理。

0278 [D/A/I/E] 建立输出 schema。

0279 [D/A/I/E] 建立 capability contract。

0280 [D/A/I/E] 建立 tool contract。

0281 [D/A/I/E] 建立最小权限。

0282 [D/A/I/E] 建立上下文隔离。

0283 [D/A/I/E] 建立冲突图。

0284 [D/A/I/E] 建立依赖图。

0285 [D/A/I/E] 建立失败传播图。

0286 [D/A/I/E] 建立 topology mutation。

0287 [D/A/I/E] 建立 topology rollback。

0288 [D/A/I/E] 限制最大并行度。

0289 [D/A/I/E] 限制最大交互轮。

0290 [D/A/I/E] 限制最大 token。

0291 [D/A/I/E] 限制最大工具调用。

0292 [D/A/I/E] 建立低置信度升级。

0293 [D/A/I/E] 建立重复观点裁剪。

0294 [D/A/I/E] 建立 observation pruning。

0295 [D/A/I/E] 建立 structural entropy。

0296 [D/A/I/E] 评测动态拓扑。

0297 [D/A/I/E] 对照固定六 Agent。

0298 [D/A/I/E] 对照单 Agent。

0299 [D/A/I/E] 保存拓扑 trace。

0300 [D/A/I/E] 冻结 Topology V1。
Workstream 07 — Agent 轨迹蒸馏与信用分配

0301 [D/A/I/E] 定义 Step-level MDP。

0302 [D/A/I/E] 定义 observation。

0303 [D/A/I/E] 定义 action。

0304 [D/A/I/E] 定义 tool response。

0305 [D/A/I/E] 定义 next observation。

0306 [D/A/I/E] 定义 terminal signal。

0307 [D/A/I/E] 定义 planner trajectory。

0308 [D/A/I/E] 定义 worker trajectory。

0309 [D/A/I/E] 定义 critic trajectory。

0310 [D/A/I/E] 定义 supervisor trajectory。

0311 [D/A/I/E] 采集成功轨迹。

0312 [D/A/I/E] 采集失败轨迹。

0313 [D/A/I/E] 采集回退轨迹。

0314 [D/A/I/E] 采集停止轨迹。

0315 [D/A/I/E] 采集人工升级轨迹。

0316 [D/A/I/E] 蒸馏任务分解。

0317 [D/A/I/E] 蒸馏工具选择。

0318 [D/A/I/E] 蒸馏参数填写。

0319 [D/A/I/E] 蒸馏观察压缩。

0320 [D/A/I/E] 蒸馏停止策略。

0321 [D/A/I/E] 蒸馏重试策略。

0322 [D/A/I/E] 蒸馏回退策略。

0323 [D/A/I/E] 蒸馏人工升级。

0324 [D/A/I/E] 建立 step reward。

0325 [D/A/I/E] 建立 trajectory reward。

0326 [D/A/I/E] 建立 planner credit。

0327 [D/A/I/E] 建立 worker credit。

0328 [D/A/I/E] 建立 critic credit。

0329 [D/A/I/E] 建立 supervisor credit。

0330 [D/A/I/E] 防止 final-only credit。

0331 [D/A/I/E] 防止错误向上游传播。

0332 [D/A/I/E] 建立 failure attribution。

0333 [D/A/I/E] 标注首个错误步骤。

0334 [D/A/I/E] 标注放大错误步骤。

0335 [D/A/I/E] 标注未发现错误步骤。

0336 [D/A/I/E] 标注错误修复步骤。

0337 [D/A/I/E] 建立时间课程。

0338 [D/A/I/E] 先蒸馏短轨迹。

0339 [D/A/I/E] 再蒸馏中轨迹。

0340 [D/A/I/E] 最后蒸馏长轨迹。

0341 [D/A/I/E] 监控 trajectory KL。

0342 [D/A/I/E] 监控 compounding error。

0343 [D/A/I/E] 监控工具噪声。

0344 [D/A/I/E] 监控无效循环。

0345 [D/A/I/E] 对照无轨迹蒸馏。

0346 [D/A/I/E] 对照 final-answer KD。

0347 [D/A/I/E] 评测归因准确率。

0348 [D/A/I/E] 评测任务成功率。

0349 [D/A/I/E] 导出 Trajectory Card。

0350 [D/A/I/E] 冻结 Trajectory KD V1。
Workstream 08 — Brand Genome 记忆蒸馏

0351 [D/A/I/E] 定义 MemoryAtom。

0352 [D/A/I/E] 定义 episodic memory。

0353 [D/A/I/E] 定义 semantic memory。

0354 [D/A/I/E] 定义 symbolic rules。

0355 [D/A/I/E] 定义产品实体。

0356 [D/A/I/E] 定义品牌实体。

0357 [D/A/I/E] 定义受众实体。

0358 [D/A/I/E] 定义 Claim 实体。

0359 [D/A/I/E] 定义渠道实体。

0360 [D/A/I/E] 定义资产实体。

0361 [D/A/I/E] 定义创意概念实体。

0362 [D/A/I/E] 建立 evidence edge。

0363 [D/A/I/E] 建立 conflict edge。

0364 [D/A/I/E] 建立 supersede edge。

0365 [D/A/I/E] 建立 applies-to edge。

0366 [D/A/I/E] 建立 prohibited edge。

0367 [D/A/I/E] 蒸馏 store policy。

0368 [D/A/I/E] 蒸馏 retrieve policy。

0369 [D/A/I/E] 蒸馏 update policy。

0370 [D/A/I/E] 蒸馏 merge policy。

0371 [D/A/I/E] 蒸馏 discard policy。

0372 [D/A/I/E] 蒸馏 summarize policy。

0373 [D/A/I/E] 蒸馏 what-to-remember。

0374 [D/A/I/E] 蒸馏 when-to-forget。

0375 [D/A/I/E] 建立事实 TTL。

0376 [D/A/I/E] 建立来源 revision。

0377 [D/A/I/E] 建立品牌规则永久层。

0378 [D/A/I/E] 建立过期事实屏蔽。

0379 [D/A/I/E] 建立矛盾仲裁。

0380 [D/A/I/E] 建立 memory confidence。

0381 [D/A/I/E] 建立 memory utility。

0382 [D/A/I/E] 建立 memory cost。

0383 [D/A/I/E] 建立 memory privacy。

0384 [D/A/I/E] 建立 memory provenance。

0385 [D/A/I/E] 建立 entity-centric retrieval。

0386 [D/A/I/E] 建立 symbolic retrieval。

0387 [D/A/I/E] 建立 neural retrieval。

0388 [D/A/I/E] 建立 hybrid retrieval。

0389 [D/A/I/E] 建立 memory-only benchmark。

0390 [D/A/I/E] 建立 streaming benchmark。

0391 [D/A/I/E] 评测 retrieval precision。

0392 [D/A/I/E] 评测 stale recall。

0393 [D/A/I/E] 评测 context saving。

0394 [D/A/I/E] 评测跨 Campaign 迁移。

0395 [D/A/I/E] 评测品牌污染。

0396 [D/A/I/E] 对照 vector-only memory。

0397 [D/A/I/E] 对照 no-memory。

0398 [D/A/I/E] 保存 Memory Card。

0399 [D/A/I/E] 建立 memory rollback。

0400 [D/A/I/E] 冻结 Brand Genome V1。
Workstream 09 — 数据权利与训练供应链

0401 [D/A/I/E] 定义 LicensedSource。

0402 [D/A/I/E] 定义允许许可证。

0403 [D/A/I/E] 定义研究隔离许可证。

0404 [D/A/I/E] 定义拒绝许可证。

0405 [D/A/I/E] 禁止公开即许可。

0406 [D/A/I/E] 保存原始 URI。

0407 [D/A/I/E] 保存 commit。

0408 [D/A/I/E] 保存 revision。

0409 [D/A/I/E] 保存 SHA-256。

0410 [D/A/I/E] 保存作者 attribution。

0411 [D/A/I/E] 保存训练用途。

0412 [D/A/I/E] 保存分发用途。

0413 [D/A/I/E] 保存商业限制。

0414 [D/A/I/E] 保存地域限制。

0415 [D/A/I/E] 保存终止条款。

0416 [D/A/I/E] 建立 GitHub SPDX 解析。

0417 [D/A/I/E] 建立模型许可解析。

0418 [D/A/I/E] 建立数据许可解析。

0419 [D/A/I/E] 建立字体许可解析。

0420 [D/A/I/E] 建立音乐许可解析。

0421 [D/A/I/E] 建立图片许可解析。

0422 [D/A/I/E] 建立视频许可解析。

0423 [D/A/I/E] 建立 README 注入扫描。

0424 [D/A/I/E] 建立 secret 扫描。

0425 [D/A/I/E] 建立 PII 扫描。

0426 [D/A/I/E] 建立肖像风险扫描。

0427 [D/A/I/E] 建立商标风险扫描。

0428 [D/A/I/E] 建立敏感行业扫描。

0429 [D/A/I/E] 建立版权长文本扫描。

0430 [D/A/I/E] 建立训练退出请求机制。

0431 [D/A/I/E] 建立数据隔离区。

0432 [D/A/I/E] 建立 research-only profile。

0433 [D/A/I/E] 建立 commercial profile。

0434 [D/A/I/E] 建立 competition profile。

0435 [D/A/I/E] 建立 Data BOM。

0436 [D/A/I/E] 建立 Model BOM。

0437 [D/A/I/E] 建立 Asset BOM。

0438 [D/A/I/E] 建立 Font BOM。

0439 [D/A/I/E] 建立 Audio BOM。

0440 [D/A/I/E] 许可证失败阻塞训练。

0441 [D/A/I/E] revision 漂移阻塞运行。

0442 [D/A/I/E] hash 漂移阻塞运行。

0443 [D/A/I/E] 建立离线快照。

0444 [D/A/I/E] 建立来源失效回退。

0445 [D/A/I/E] 建立来源删除记录。

0446 [D/A/I/E] 人工审查高风险来源。

0447 [D/A/I/E] 生成 Dataset Card。

0448 [D/A/I/E] 生成 Supply Chain Report。

0449 [D/A/I/E] 运行全量许可 gate。

0450 [D/A/I/E] 冻结 Supply Chain V3。
Workstream 10 — 4A Agency Genome Corpus

0451 [D/A/I/E] 定义语料 taxonomy。

0452 [D/A/I/E] 定义实体新品 corpus。

0453 [D/A/I/E] 定义 AI Agent corpus。

0454 [D/A/I/E] 定义 Evidence corpus。

0455 [D/A/I/E] 定义 Strategy corpus。

0456 [D/A/I/E] 定义 Creative corpus。

0457 [D/A/I/E] 定义 Copy corpus。

0458 [D/A/I/E] 定义 Art corpus。

0459 [D/A/I/E] 定义 Channel corpus。

0460 [D/A/I/E] 定义 Compliance corpus。

0461 [D/A/I/E] 定义 Audit corpus。

0462 [D/A/I/E] 定义 Repair corpus。

0463 [D/A/I/E] 收集开放硬件资料。

0464 [D/A/I/E] 收集开放软件资料。

0465 [D/A/I/E] 收集开放品牌资料。

0466 [D/A/I/E] 收集开放产品视觉。

0467 [D/A/I/E] 收集开放场景视觉。

0468 [D/A/I/E] 收集开放视频。

0469 [D/A/I/E] 收集开放字体。

0470 [D/A/I/E] 收集开放音频。

0471 [D/A/I/E] 构建 2,000 source bundle。

0472 [D/A/I/E] 提取产品事实。

0473 [D/A/I/E] 提取能力限制。

0474 [D/A/I/E] 提取 Claim 风险。

0475 [D/A/I/E] 生成 ICP。

0476 [D/A/I/E] 生成 JTBD。

0477 [D/A/I/E] 生成 market tension。

0478 [D/A/I/E] 生成 category convention。

0479 [D/A/I/E] 生成 SMP。

0480 [D/A/I/E] 生成 RTB。

0481 [D/A/I/E] 生成 Offer。

0482 [D/A/I/E] 生成 Big Idea。

0483 [D/A/I/E] 生成 Key Visual brief。

0484 [D/A/I/E] 生成 copy system。

0485 [D/A/I/E] 生成 channel system。

0486 [D/A/I/E] 生成 storyboard。

0487 [D/A/I/E] 生成 audit finding。

0488 [D/A/I/E] 生成 repair action。

0489 [D/A/I/E] 构建 15M CPT token。

0490 [D/A/I/E] 构建 15,000 SFT episode。

0491 [D/A/I/E] 构建 5,000 preference pair。

0492 [D/A/I/E] 构建 2,000 region preference。

0493 [D/A/I/E] 构建 1,000 trajectory。

0494 [D/A/I/E] 构建 500 repair episode。

0495 [D/A/I/E] 构建 300 gold brief。

0496 [D/A/I/E] 构建 150 gold campaign。

0497 [D/A/I/E] 五人审核 gold set。

0498 [D/A/I/E] gold 平均 ≥4.7。

0499 [D/A/I/E] 发布 Dataset Card。

0500 [D/A/I/E] 冻结 Agency Corpus V2。
Workstream 11 — 语料精选、去重与 JEST 式课程

0501 [D/A/I/E] 文本 Unicode 清洗。

0502 [D/A/I/E] 文本语言识别。

0503 [D/A/I/E] 文本模板识别。

0504 [D/A/I/E] 文本 MinHash 去重。

0505 [D/A/I/E] 图片 EXIF 清洗。

0506 [D/A/I/E] 图片色彩规范化。

0507 [D/A/I/E] 图片 pHash 去重。

0508 [D/A/I/E] 图片 embedding 去重。

0509 [D/A/I/E] 视频 FPS 规范化。

0510 [D/A/I/E] 视频关键帧去重。

0511 [D/A/I/E] 音频采样率规范化。

0512 [D/A/I/E] 音频内容去重。

0513 [D/A/I/E] 检查图文对齐。

0514 [D/A/I/E] 检查视频文案对齐。

0515 [D/A/I/E] 检查 Claim 证据对齐。

0516 [D/A/I/E] 计算单样本质量。

0517 [D/A/I/E] 计算单样本难度。

0518 [D/A/I/E] 计算单样本新颖性。

0519 [D/A/I/E] 计算单样本覆盖。

0520 [D/A/I/E] 计算 batch 多样性。

0521 [D/A/I/E] 计算 batch 难度。

0522 [D/A/I/E] 计算 batch 信息量。

0523 [D/A/I/E] 建立 curated reference。

0524 [D/A/I/E] 建立 reference-guided selection。

0525 [D/A/I/E] 建立 super-batch selection。

0526 [D/A/I/E] 限制同来源占比。

0527 [D/A/I/E] 限制同模板占比。

0528 [D/A/I/E] 限制合成数据占比。

0529 [D/A/I/E] 平衡实体与软件产品。

0530 [D/A/I/E] 平衡文本与视觉。

0531 [D/A/I/E] 平衡图片与视频。

0532 [D/A/I/E] 平衡策略与制作。

0533 [D/A/I/E] 平衡成功与失败。

0534 [D/A/I/E] 平衡短轨迹与长轨迹。

0535 [D/A/I/E] 按产品实体切分。

0536 [D/A/I/E] 按仓库实体切分。

0537 [D/A/I/E] 按时间切分。

0538 [D/A/I/E] 扫描 benchmark 污染。

0539 [D/A/I/E] 扫描 prompt 泄漏。

0540 [D/A/I/E] 抽检 1,500 样本。

0541 [D/A/I/E] 计算审核一致性。

0542 [D/A/I/E] 要求 Alpha≥0.85。

0543 [D/A/I/E] 正例平均 ≥4.7。

0544 [D/A/I/E] 低分正例移除。

0545 [D/A/I/E] 中等样本转 repair。

0546 [D/A/I/E] 困难样本进入 replay。

0547 [D/A/I/E] 输出数据分布。

0548 [D/A/I/E] 输出概念长尾。

0549 [D/A/I/E] 输出来源分布。

0550 [D/A/I/E] 冻结 Curated Corpus V2。
Workstream 12 — 自进化数据与验证器课程

0551 [D/A/I/E] 建立 Challenger。

0552 [D/A/I/E] 建立 Planner。

0553 [D/A/I/E] 建立 Producer。

0554 [D/A/I/E] 建立 Critic。

0555 [D/A/I/E] 建立 Verifier。

0556 [D/A/I/E] 生成事实冲突任务。

0557 [D/A/I/E] 生成证据缺失任务。

0558 [D/A/I/E] 生成长文档任务。

0559 [D/A/I/E] 生成多图冲突任务。

0560 [D/A/I/E] 生成产品身份任务。

0561 [D/A/I/E] 生成 Logo drift 任务。

0562 [D/A/I/E] 生成品牌色任务。

0563 [D/A/I/E] 生成 OCR 任务。

0564 [D/A/I/E] 生成安全区任务。

0565 [D/A/I/E] 生成暗示 Claim 任务。

0566 [D/A/I/E] 生成本地化任务。

0567 [D/A/I/E] 生成视频闪烁任务。

0568 [D/A/I/E] 生成 A/V 任务。

0569 [D/A/I/E] 生成工具超时任务。

0570 [D/A/I/E] 生成模型 OOM 任务。

0571 [D/A/I/E] 生成记忆过期任务。

0572 [D/A/I/E] 生成 Agent 冲突任务。

0573 [D/A/I/E] 生成无效循环任务。

0574 [D/A/I/E] 生成过度思考任务。

0575 [D/A/I/E] Planner 生成验证计划。

0576 [D/A/I/E] Producer 执行计划。

0577 [D/A/I/E] Critic 评价计划。

0578 [D/A/I/E] Critic 评价结果。

0579 [D/A/I/E] Verifier 执行机械检查。

0580 [D/A/I/E] 拒绝不可验证数据。

0581 [D/A/I/E] 计算任务难度。

0582 [D/A/I/E] 计算任务新颖性。

0583 [D/A/I/E] 计算覆盖增益。

0584 [D/A/I/E] 计算失败价值。

0585 [D/A/I/E] 防止课程漂移。

0586 [D/A/I/E] 防止 Critic 共谋。

0587 [D/A/I/E] 引入旧 checkpoint。

0588 [D/A/I/E] 引入不同 seed。

0589 [D/A/I/E] 引入反事实输入。

0590 [D/A/I/E] 标注首错步骤。

0591 [D/A/I/E] 标注传播步骤。

0592 [D/A/I/E] 标注修复步骤。

0593 [D/A/I/E] 标注停止步骤。

0594 [D/A/I/E] 高价值失败进入 replay。

0595 [D/A/I/E] 低价值重复样本丢弃。

0596 [D/A/I/E] 冻结每轮课程。

0597 [D/A/I/E] 评测课程有效性。

0598 [D/A/I/E] 对照静态数据。

0599 [D/A/I/E] 输出 Evolution Report。

0600 [D/A/I/E] 冻结 Curriculum Engine V1。
Workstream 13 — 统一多模态 CPT

0601 [D/A/I/E] 记录 Base revision。

0602 [D/A/I/E] 运行 Base 冻结评测。

0603 [D/A/I/E] 探测 Radeon 显存。

0604 [D/A/I/E] 选择 4B/2B profile。

0605 [D/A/I/E] 定义 text objective。

0606 [D/A/I/E] 定义 image-text objective。

0607 [D/A/I/E] 定义 layout objective。

0608 [D/A/I/E] 定义 video-state objective。

0609 [D/A/I/E] 定义 audio-text objective。

0610 [D/A/I/E] 定义 Campaign-state objective。

0611 [D/A/I/E] 定义 next-action objective。

0612 [D/A/I/E] 定义 failure objective。

0613 [D/A/I/E] 定义 repair objective。

0614 [D/A/I/E] 定义 cross-channel objective。

0615 [D/A/I/E] 定义 evidence objective。

0616 [D/A/I/E] 定义 uncertainty objective。

0617 [D/A/I/E] 设置模态混合比例。

0618 [D/A/I/E] 设置任务混合比例。

0619 [D/A/I/E] 设置 curriculum schedule。

0620 [D/A/I/E] 设置视觉塔 LR。

0621 [D/A/I/E] 设置 connector LR。

0622 [D/A/I/E] 设置 LLM LR。

0623 [D/A/I/E] 设置 adapter LR。

0624 [D/A/I/E] 开启 packing。

0625 [D/A/I/E] 开启 gradient checkpointing。

0626 [D/A/I/E] 开启 gradient accumulation。

0627 [D/A/I/E] 设置 BF16。

0628 [D/A/I/E] 设置 deterministic seed。

0629 [D/A/I/E] 设置六小时预算。

0630 [D/A/I/E] 设置 checkpoint 间隔。

0631 [D/A/I/E] 保存 optimizer。

0632 [D/A/I/E] 保存 scheduler。

0633 [D/A/I/E] 保存 RNG state。

0634 [D/A/I/E] 监测 train loss。

0635 [D/A/I/E] 监测 val loss。

0636 [D/A/I/E] 监测视觉遗忘。

0637 [D/A/I/E] 监测语言遗忘。

0638 [D/A/I/E] 监测 schema 能力。

0639 [D/A/I/E] 监测 Claim 能力。

0640 [D/A/I/E] 监测状态预测。

0641 [D/A/I/E] 每 checkpoint 小评测。

0642 [D/A/I/E] 比较最佳 checkpoint。

0643 [D/A/I/E] 禁止默认最后 checkpoint。

0644 [D/A/I/E] 输出 token throughput。

0645 [D/A/I/E] 输出峰值显存。

0646 [D/A/I/E] 输出训练能耗代理。

0647 [D/A/I/E] 输出数据 revision。

0648 [D/A/I/E] 输出学习曲线。

0649 [D/A/I/E] 输出 CPT Card。

0650 [D/A/I/E] 冻结 CPT Checkpoint。
Workstream 14 — 多模态 Curriculum SFT/DFT

0651 [D/A/I/E] 建立 Evidence stage。

0652 [D/A/I/E] 建立 Audience stage。

0653 [D/A/I/E] 建立 Strategy stage。

0654 [D/A/I/E] 建立 Creative stage。

0655 [D/A/I/E] 建立 Copy stage。

0656 [D/A/I/E] 建立 Art stage。

0657 [D/A/I/E] 建立 Channel stage。

0658 [D/A/I/E] 建立 Production stage。

0659 [D/A/I/E] 建立 Compliance stage。

0660 [D/A/I/E] 建立 Audit stage。

0661 [D/A/I/E] 建立 Repair stage。

0662 [D/A/I/E] 建立 Memory stage。

0663 [D/A/I/E] 建立 Planning stage。

0664 [D/A/I/E] 建立 Stop stage。

0665 [D/A/I/E] 从短文本开始。

0666 [D/A/I/E] 加入长文档。

0667 [D/A/I/E] 加入单图。

0668 [D/A/I/E] 加入多图。

0669 [D/A/I/E] 加入视频帧。

0670 [D/A/I/E] 加入音频。

0671 [D/A/I/E] 加入工具轨迹。

0672 [D/A/I/E] 加入状态轨迹。

0673 [D/A/I/E] 加入跨渠道任务。

0674 [D/A/I/E] 对 Claim 提高 loss。

0675 [D/A/I/E] 对 locator 提高 loss。

0676 [D/A/I/E] 对 SMP 提高 loss。

0677 [D/A/I/E] 对 RTB 提高 loss。

0678 [D/A/I/E] 对 Big Idea 提高 loss。

0679 [D/A/I/E] 对 JSON 提高 loss。

0680 [D/A/I/E] 对 Stop 提高 loss。

0681 [D/A/I/E] 对 unsafe action 降权。

0682 [D/A/I/E] 运行普通 SFT。

0683 [D/A/I/E] 运行 DFT。

0684 [D/A/I/E] 比较 token accuracy。

0685 [D/A/I/E] 比较视觉依赖。

0686 [D/A/I/E] 比较 4A 得分。

0687 [D/A/I/E] 比较状态预测。

0688 [D/A/I/E] 比较通用回归。

0689 [D/A/I/E] 只保留显著提升。

0690 [D/A/I/E] 保存 stage adapter。

0691 [D/A/I/E] 保存 stage data。

0692 [D/A/I/E] 保存 stage metrics。

0693 [D/A/I/E] 建立 stage rollback。

0694 [D/A/I/E] 建立多 stage replay。

0695 [D/A/I/E] 运行随机顺序对照。

0696 [D/A/I/E] 运行反向 curriculum 对照。

0697 [D/A/I/E] 评测 curriculum 收益。

0698 [D/A/I/E] 输出 SFT Report。

0699 [D/A/I/E] 输出 SFT Card。

0700 [D/A/I/E] 冻结 SFT Adapter。
Workstream 15 — On-Policy/自蒸馏

0701 [D/A/I/E] 建立 GKD baseline。

0702 [D/A/I/E] 建立 off-policy KD。

0703 [D/A/I/E] 建立 on-policy KD。

0704 [D/A/I/E] 建立 OPSD。

0705 [D/A/I/E] 建立 SDFT。

0706 [D/A/I/E] 建立 TCOD。

0707 [D/A/I/E] 建立 CaOPD。

0708 [D/A/I/E] 建立 no-KD。

0709 [D/A/I/E] 定义 privileged evidence。

0710 [D/A/I/E] 定义 privileged critique。

0711 [D/A/I/E] 定义 privileged repair。

0712 [D/A/I/E] 定义 deployment input。

0713 [D/A/I/E] 生成 student rollout。

0714 [D/A/I/E] 教师评学生 rollout。

0715 [D/A/I/E] 计算 forward KL。

0716 [D/A/I/E] 计算 reverse KL。

0717 [D/A/I/E] 计算 JSD。

0718 [D/A/I/E] 诊断 top-k overlap。

0719 [D/A/I/E] 诊断 token advantage。

0720 [D/A/I/E] 诊断 fork entropy。

0721 [D/A/I/E] 保护自纠正 token。

0722 [D/A/I/E] 保护验证 token。

0723 [D/A/I/E] 保护回溯 token。

0724 [D/A/I/E] 对 style token 裁剪。

0725 [D/A/I/E] 设置 point-wise KL clip。

0726 [D/A/I/E] 设置短轨迹课程。

0727 [D/A/I/E] 设置中轨迹课程。

0728 [D/A/I/E] 设置长轨迹课程。

0729 [D/A/I/E] 监测轨迹 KL 爆炸。

0730 [D/A/I/E] 监测 teacher mismatch。

0731 [D/A/I/E] 监测无新增知识。

0732 [D/A/I/E] 监测过度自信。

0733 [D/A/I/E] 监测验证行为减少。

0734 [D/A/I/E] 监测回溯行为减少。

0735 [D/A/I/E] 监测 diversity collapse。

0736 [D/A/I/E] 设置两小时实验预算。

0737 [D/A/I/E] 计算 token 效率。

0738 [D/A/I/E] 计算能力提升。

0739 [D/A/I/E] 计算能力保留。

0740 [D/A/I/E] 计算校准误差。

0741 [D/A/I/E] 计算长轨迹成功率。

0742 [D/A/I/E] 淘汰失败方法。

0743 [D/A/I/E] 保存教师 revision。

0744 [D/A/I/E] 保存学生 revision。

0745 [D/A/I/E] 保存 rollout。

0746 [D/A/I/E] 保存 KL diagnostics。

0747 [D/A/I/E] 保存负实验。

0748 [D/A/I/E] 输出 OPD Report。

0749 [D/A/I/E] 输出 Distilled Model Card。

0750 [D/A/I/E] 冻结最佳 KD Adapter。
Workstream 16 — 多目标 RL 与 Rich-Feedback Distillation

0751 [D/A/I/E] 定义 reward vector。

0752 [D/A/I/E] 定义 evidence reward。

0753 [D/A/I/E] 定义 strategy reward。

0754 [D/A/I/E] 定义 creative reward。

0755 [D/A/I/E] 定义 copy reward。

0756 [D/A/I/E] 定义 identity reward。

0757 [D/A/I/E] 定义 brand reward。

0758 [D/A/I/E] 定义 OCR reward。

0759 [D/A/I/E] 定义 temporal reward。

0760 [D/A/I/E] 定义 channel reward。

0761 [D/A/I/E] 定义 safety reward。

0762 [D/A/I/E] 定义 efficiency reward。

0763 [D/A/I/E] 定义 diversity reward。

0764 [D/A/I/E] 定义 stop reward。

0765 [D/A/I/E] 使用 lexicographic safety。

0766 [D/A/I/E] 禁止单标量压平。

0767 [D/A/I/E] 建立 Pareto selection。

0768 [D/A/I/E] 建立 reward normalization。

0769 [D/A/I/E] 建立 reward calibration。

0770 [D/A/I/E] 建立 rich textual feedback。

0771 [D/A/I/E] 将审计反馈 token 化。

0772 [D/A/I/E] 将工具错误 token 化。

0773 [D/A/I/E] 将人类 critique token 化。

0774 [D/A/I/E] 蒸馏高奖励轨迹。

0775 [D/A/I/E] 蒸馏修复成功轨迹。

0776 [D/A/I/E] 建立 ORPO baseline。

0777 [D/A/I/E] 建立 SimPO baseline。

0778 [D/A/I/E] 建立 MDPO-style baseline。

0779 [D/A/I/E] 建立 micro-GRPO。

0780 [D/A/I/E] 限制 RL 两小时。

0781 [D/A/I/E] 监测 reward hacking。

0782 [D/A/I/E] 监测 length hacking。

0783 [D/A/I/E] 监测 tool-call hacking。

0784 [D/A/I/E] 监测 judge gaming。

0785 [D/A/I/E] 监测 visual metric gaming。

0786 [D/A/I/E] 加入 adversarial verifier。

0787 [D/A/I/E] 加入 held-out verifier。

0788 [D/A/I/E] 加入 human spot-check。

0789 [D/A/I/E] 计算策略收益。

0790 [D/A/I/E] 计算轨迹收益。

0791 [D/A/I/E] 计算视觉收益。

0792 [D/A/I/E] 计算校准收益。

0793 [D/A/I/E] 计算推理成本。

0794 [D/A/I/E] 回归即淘汰 RL。

0795 [D/A/I/E] 保存 rollout evidence。

0796 [D/A/I/E] 保存 reward trace。

0797 [D/A/I/E] 保存 verifier trace。

0798 [D/A/I/E] 输出 RL Report。

0799 [D/A/I/E] 输出 RL Card。

0800 [D/A/I/E] 冻结最佳 Alignment Adapter。
Workstream 17 — Adapter pseudo-MoE、合并与压缩

0801 [D/A/I/E] 建立 Evidence adapter。

0802 [D/A/I/E] 建立 Strategy adapter。

0803 [D/A/I/E] 建立 Creative adapter。

0804 [D/A/I/E] 建立 Copy adapter。

0805 [D/A/I/E] 建立 Art adapter。

0806 [D/A/I/E] 建立 Channel adapter。

0807 [D/A/I/E] 建立 Compliance adapter。

0808 [D/A/I/E] 建立 Memory adapter。

0809 [D/A/I/E] 建立 Planner adapter。

0810 [D/A/I/E] 建立 Critic adapter。

0811 [D/A/I/E] 建立 capability metadata。

0812 [D/A/I/E] 建立 adapter router。

0813 [D/A/I/E] 按任务路由。

0814 [D/A/I/E] 按不确定度路由。

0815 [D/A/I/E] 按市场路由。

0816 [D/A/I/E] 按风险路由。

0817 [D/A/I/E] 实现 PEFT hotswap。

0818 [D/A/I/E] 测试 hotswap 延迟。

0819 [D/A/I/E] 测试 hotswap 内存。

0820 [D/A/I/E] 测试 adapter 串扰。

0821 [D/A/I/E] 测试 adapter 遗忘。

0822 [D/A/I/E] 建立 adapter cache。

0823 [D/A/I/E] 建立 adapter eviction。

0824 [D/A/I/E] 建立 adapter versioning。

0825 [D/A/I/E] 建立 adapter rollback。

0826 [D/A/I/E] 生成 teacher outputs。

0827 [D/A/I/E] 执行 offline GKD。

0828 [D/A/I/E] 评测 teacher/student ratio。

0829 [D/A/I/E] 执行 weighted merge。

0830 [D/A/I/E] 执行 TIES merge。

0831 [D/A/I/E] 执行 DARE merge。

0832 [D/A/I/E] 执行 no-merge 对照。

0833 [D/A/I/E] 检查能力干扰。

0834 [D/A/I/E] 检查安全回归。

0835 [D/A/I/E] 检查 Claim 回归。

0836 [D/A/I/E] 检查视觉回归。

0837 [D/A/I/E] 回归则保留独立 adapter。

0838 [D/A/I/E] 测试 BF16 export。

0839 [D/A/I/E] 测试 FP16 export。

0840 [D/A/I/E] 测试 INT8 辅助模型。

0841 [D/A/I/E] 禁止未验证量化主模型。

0842 [D/A/I/E] 建立模型热切换。

0843 [D/A/I/E] 建立单卡驻留计划。

0844 [D/A/I/E] 建立内存峰值计划。

0845 [D/A/I/E] 建立 adapter registry。

0846 [D/A/I/E] 输出 merge ablation。

0847 [D/A/I/E] 输出 compression report。

0848 [D/A/I/E] 输出 routing report。

0849 [D/A/I/E] 输出 pseudo-MoE Card。

0850 [D/A/I/E] 冻结 Adapter Stack V1。
Workstream 18 — 4A GTM 员工专业蒸馏

0851 [D/A/I/E] 蒸馏 Category Entry Point。

0852 [D/A/I/E] 蒸馏 ICP。

0853 [D/A/I/E] 蒸馏 JTBD。

0854 [D/A/I/E] 蒸馏 buying committee。

0855 [D/A/I/E] 蒸馏 pain/gain。

0856 [D/A/I/E] 蒸馏 market tension。

0857 [D/A/I/E] 蒸馏 category convention。

0858 [D/A/I/E] 蒸馏 convention break。

0859 [D/A/I/E] 蒸馏 positioning。

0860 [D/A/I/E] 蒸馏 SMP。

0861 [D/A/I/E] 蒸馏 RTB。

0862 [D/A/I/E] 蒸馏 Offer。

0863 [D/A/I/E] 蒸馏 objection handling。

0864 [D/A/I/E] 蒸馏 Big Idea。

0865 [D/A/I/E] 蒸馏 idea extensibility。

0866 [D/A/I/E] 蒸馏 campaign mnemonic。

0867 [D/A/I/E] 蒸馏 message hierarchy。

0868 [D/A/I/E] 蒸馏 headline system。

0869 [D/A/I/E] 蒸馏 body copy。

0870 [D/A/I/E] 蒸馏 CTA。

0871 [D/A/I/E] 蒸馏 landing narrative。

0872 [D/A/I/E] 蒸馏 email journey。

0873 [D/A/I/E] 蒸馏 Amazon 适配。

0874 [D/A/I/E] 蒸馏 Shopify 适配。

0875 [D/A/I/E] 蒸馏 Meta 适配。

0876 [D/A/I/E] 蒸馏 TikTok 适配。

0877 [D/A/I/E] 蒸馏 LinkedIn 适配。

0878 [D/A/I/E] 蒸馏 YouTube 适配。

0879 [D/A/I/E] 蒸馏 Performance Max 适配。

0880 [D/A/I/E] 蒸馏北美语调。

0881 [D/A/I/E] 蒸馏中文本地化。

0882 [D/A/I/E] 蒸馏 comparative claim。

0883 [D/A/I/E] 蒸馏 disclosure。

0884 [D/A/I/E] 蒸馏 net impression。

0885 [D/A/I/E] 蒸馏 4A critique。

0886 [D/A/I/E] 蒸馏 art critique。

0887 [D/A/I/E] 蒸馏 copy critique。

0888 [D/A/I/E] 蒸馏 production critique。

0889 [D/A/I/E] 蒸馏 channel critique。

0890 [D/A/I/E] 建立跨渠道一致。

0891 [D/A/I/E] 建立跨渠道非重复。

0892 [D/A/I/E] 建立 performance hypothesis。

0893 [D/A/I/E] 建立 A/B plan。

0894 [D/A/I/E] 建立 creative fatigue plan。

0895 [D/A/I/E] 建立 audience learning plan。

0896 [D/A/I/E] 五人评测 GTM 输出。

0897 [D/A/I/E] 平均必须 ≥4.7。

0898 [D/A/I/E] publishable ≥95%。

0899 [D/A/I/E] 输出 GTM Skill Card。

0900 [D/A/I/E] 冻结 4A Employee V1。
Workstream 19 — 4K 图像轮子蒸馏与原创组合

0901 [D/A/I/E] 验证 FLUX.2 Klein。

0902 [D/A/I/E] 验证 FLUX.2 Base。

0903 [D/A/I/E] 验证 SDXL fallback。

0904 [D/A/I/E] 复用多参考编辑。

0905 [D/A/I/E] 复用 prompt upsampling 思路。

0906 [D/A/I/E] 复用 Grounding DINO。

0907 [D/A/I/E] 复用 SAM2.1。

0908 [D/A/I/E] 复用 Real-ESRGAN。

0909 [D/A/I/E] 复用 SwinIR。

0910 [D/A/I/E] 复用 SeedVR2 图片修复。

0911 [D/A/I/E] 建立产品保护蒙版。

0912 [D/A/I/E] 建立 Logo 保护蒙版。

0913 [D/A/I/E] 建立文字保护区。

0914 [D/A/I/E] 建立品牌色约束。

0915 [D/A/I/E] 建立字体约束。

0916 [D/A/I/E] 建立构图约束。

0917 [D/A/I/E] 建立灯光约束。

0918 [D/A/I/E] 建立材质约束。

0919 [D/A/I/E] 建立负空间约束。

0920 [D/A/I/E] 训练 lighting LoRA。

0921 [D/A/I/E] 训练 layout LoRA。

0922 [D/A/I/E] 避免品牌记忆 LoRA。

0923 [D/A/I/E] 生成三套方向。

0924 [D/A/I/E] 生成 concept board。

0925 [D/A/I/E] 建立 Best-of-N。

0926 [D/A/I/E] 建立 region reward。

0927 [D/A/I/E] 建立 product reward。

0928 [D/A/I/E] 建立 Logo reward。

0929 [D/A/I/E] 建立 typography reward。

0930 [D/A/I/E] 建立 safe-zone reward。

0931 [D/A/I/E] 冻结 Key Visual。

0932 [D/A/I/E] 生成四张 1:1。

0933 [D/A/I/E] 生成四张 4:5。

0934 [D/A/I/E] 生成四张 9:16。

0935 [D/A/I/E] 分块超分。

0936 [D/A/I/E] 重合成原产品层。

0937 [D/A/I/E] 原生 4K 渲染 Logo。

0938 [D/A/I/E] 原生 4K 渲染文字。

0939 [D/A/I/E] 生成 Google 无字版。

0940 [D/A/I/E] 生成社交安全区版。

0941 [D/A/I/E] OCR ≥99.9%。

0942 [D/A/I/E] 品牌色 ΔE≤1.5。

0943 [D/A/I/E] 产品身份 ≥99%。

0944 [D/A/I/E] Logo 身份 ≥99%。

0945 [D/A/I/E] Claim 覆盖 100%。

0946 [D/A/I/E] 只允许局部修复。

0947 [D/A/I/E] 对照直接 FLUX。

0948 [D/A/I/E] 对照成熟 Comfy workflow。

0949 [D/A/I/E] 输出 Image Evidence。

0950 [D/A/I/E] 冻结 4K Image Pack。
Workstream 20 — 4K 视频、一步修复与少步蒸馏

0951 [D/A/I/E] 验证 Wan2.2 5B。

0952 [D/A/I/E] 验证 Wan I2V。

0953 [D/A/I/E] 验证 LTX fallback。

0954 [D/A/I/E] 验证 SeedVR2。

0955 [D/A/I/E] 验证 rCM checkpoint。

0956 [D/A/I/E] 验证 Causal Forcing checkpoint。

0957 [D/A/I/E] 禁止单卡重训 10B teacher。

0958 [D/A/I/E] 复用少步蒸馏权重。

0959 [D/A/I/E] 复用 cache optimization。

0960 [D/A/I/E] 复用 trajectory optimization。

0961 [D/A/I/E] 定义视频一角色。

0962 [D/A/I/E] 定义视频二角色。

0963 [D/A/I/E] 定义视频三角色。

0964 [D/A/I/E] 建立 storyboard。

0965 [D/A/I/E] 建立 shot graph。

0966 [D/A/I/E] 建立首关键帧。

0967 [D/A/I/E] 建立尾关键帧。

0968 [D/A/I/E] 建立产品约束。

0969 [D/A/I/E] 建立 Logo 约束。

0970 [D/A/I/E] 建立运动约束。

0971 [D/A/I/E] 建立镜头约束。

0972 [D/A/I/E] 建立 temporal region reward。

0973 [D/A/I/E] 生成 720p 基础片。

0974 [D/A/I/E] SeedVR2 一步修复。

0975 [D/A/I/E] 建立逐帧 fallback。

0976 [D/A/I/E] 建立光流修复。

0977 [D/A/I/E] 建立 chunk overlap。

0978 [D/A/I/E] 建立 VAE tiling。

0979 [D/A/I/E] 输出 3840×2160。

0980 [D/A/I/E] 输出 2160×3840。

0981 [D/A/I/E] 输出 3840×3840。

0982 [D/A/I/E] 固定 8 秒。

0983 [D/A/I/E] 固定 24 FPS。

0984 [D/A/I/E] 生成北美旁白。

0985 [D/A/I/E] 校验品牌发音。

0986 [D/A/I/E] 生成 4K supers。

0987 [D/A/I/E] 标准化 -16 LUFS。

0988 [D/A/I/E] 限制 -1 dBTP。

0989 [D/A/I/E] 检查安全区。

0990 [D/A/I/E] 检查逐帧身份。

0991 [D/A/I/E] 检查闪烁。

0992 [D/A/I/E] 检查运动连续。

0993 [D/A/I/E] 检查 A/V。

0994 [D/A/I/E] 检查跨媒体 Claim。

0995 [D/A/I/E] 对照原始 Wan。

0996 [D/A/I/E] 对照逐帧超分。

0997 [D/A/I/E] 对照成熟 Comfy workflow。

0998 [D/A/I/E] 输出 Video Evidence。

0999 [D/A/I/E] 输出 Distillation Evidence。

1000 [D/A/I/E] 冻结 4K Video Pack。
Workstream 21 — 多模态奖励与全球 Top-3 科学评测

1001 [D/A/I/E] 冻结 GTM Bench。

1002 [D/A/I/E] 冻结实体测试集。

1003 [D/A/I/E] 冻结 Agent 产品测试集。

1004 [D/A/I/E] 冻结长文档集。

1005 [D/A/I/E] 冻结多图集。

1006 [D/A/I/E] 冻结视频集。

1007 [D/A/I/E] 冻结音频集。

1008 [D/A/I/E] 冻结工具轨迹集。

1009 [D/A/I/E] 冻结记忆集。

1010 [D/A/I/E] 冻结 4A Campaign 集。

1011 [D/A/I/E] 选择图像 Top 基线。

1012 [D/A/I/E] 选择视频 Top 基线。

1013 [D/A/I/E] 选择 GTM Agent Top 基线。

1014 [D/A/I/E] 运行 V7.4 基线。

1015 [D/A/I/E] 运行 Base 模型。

1016 [D/A/I/E] 运行无 KD 消融。

1017 [D/A/I/E] 运行无 CPT 消融。

1018 [D/A/I/E] 运行无 SFT 消融。

1019 [D/A/I/E] 运行无 RL 消融。

1020 [D/A/I/E] 运行无 Memory 消融。

1021 [D/A/I/E] 运行无 World Model 消融。

1022 [D/A/I/E] 运行单 Agent 消融。

1023 [D/A/I/E] 运行固定拓扑消融。

1024 [D/A/I/E] 运行无审计消融。

1025 [D/A/I/E] 运行无修复消融。

1026 [D/A/I/E] 计算 Claim precision。

1027 [D/A/I/E] 计算 Claim recall。

1028 [D/A/I/E] 计算 schema validity。

1029 [D/A/I/E] 计算 agent success。

1030 [D/A/I/E] 计算 tool error。

1031 [D/A/I/E] 计算 trajectory accuracy。

1032 [D/A/I/E] 计算 failure attribution。

1033 [D/A/I/E] 计算 memory precision。

1034 [D/A/I/E] 计算 stale recall。

1035 [D/A/I/E] 计算 image identity。

1036 [D/A/I/E] 计算 video identity。

1037 [D/A/I/E] 计算 temporal consistency。

1038 [D/A/I/E] 计算 A/V alignment。

1039 [D/A/I/E] 校准五名评审。

1040 [D/A/I/E] 收集 ≥1,500 评分。

1041 [D/A/I/E] Alpha≥0.85。

1042 [D/A/I/E] 计算 4A 平均分。

1043 [D/A/I/E] 计算 publishable rate。

1044 [D/A/I/E] 计算偏好胜率。

1045 [D/A/I/E] 计算 Wilson 区间。

1046 [D/A/I/E] 校准 Agency Critic。

1047 [D/A/I/E] Critic TPR/TNR≥90%。

1048 [D/A/I/E] 输出完整消融。

1049 [D/A/I/E] 输出 Top-3 Evidence。

1050 [D/A/I/E] 冻结 Scientific Report。
Workstream 22 — FTC、品牌、安全与抗失控

1051 [D/A/I/E] 建立明示 Claim gate。

1052 [D/A/I/E] 建立暗示 Claim gate。

1053 [D/A/I/E] 建立 net-impression gate。

1054 [D/A/I/E] 建立 prior-substantiation gate。

1055 [D/A/I/E] 建立 comparative gate。

1056 [D/A/I/E] 建立 testimonial gate。

1057 [D/A/I/E] 建立 disclosure gate。

1058 [D/A/I/E] 建立 Made-in-USA gate。

1059 [D/A/I/E] 建立医疗 gate。

1060 [D/A/I/E] 建立金融 gate。

1061 [D/A/I/E] 建立隐私 gate。

1062 [D/A/I/E] 建立 AI label gate。

1063 [D/A/I/E] 建立 Google policy。

1064 [D/A/I/E] 建立 TikTok policy。

1065 [D/A/I/E] 建立 YouTube policy。

1066 [D/A/I/E] 建立 Meta policy。

1067 [D/A/I/E] 建立 Amazon policy。

1068 [D/A/I/E] 建立 prompt injection。

1069 [D/A/I/E] 建立 indirect injection。

1070 [D/A/I/E] 建立 tool permission。

1071 [D/A/I/E] 建立路径隔离。

1072 [D/A/I/E] 建立网络白名单。

1073 [D/A/I/E] 建立命令白名单。

1074 [D/A/I/E] 禁止自动发布。

1075 [D/A/I/E] 禁止删除证据。

1076 [D/A/I/E] 禁止跳过审计。

1077 [D/A/I/E] 禁止提高修复预算。

1078 [D/A/I/E] 禁止伪造 GPU trace。

1079 [D/A/I/E] 禁止伪造训练 trace。

1080 [D/A/I/E] 建立 ledger hash chain。

1081 [D/A/I/E] 建立 ledger verify。

1082 [D/A/I/E] 建立 model drift gate。

1083 [D/A/I/E] 建立 data drift gate。

1084 [D/A/I/E] 建立 adapter drift gate。

1085 [D/A/I/E] 建立 memory poisoning test。

1086 [D/A/I/E] 建立 agent collusion test。

1087 [D/A/I/E] 建立 reward hacking test。

1088 [D/A/I/E] 建立 unsafe tool test。

1089 [D/A/I/E] 建立 cross-agent propagation test。

1090 [D/A/I/E] 建立 hallucinated-source test。

1091 [D/A/I/E] 建立 logo misuse test。

1092 [D/A/I/E] 建立 cultural harm test。

1093 [D/A/I/E] 建立 false comparison test。

1094 [D/A/I/E] Critical 强制阻塞。

1095 [D/A/I/E] 人工 Release Gate。

1096 [D/A/I/E] 记录风险接受人。

1097 [D/A/I/E] 记录风险接受理由。

1098 [D/A/I/E] 输出 Safety Case。

1099 [D/A/I/E] 红队复验。

1100 [D/A/I/E] 冻结 Safety Case V2。
Workstream 23 — Radeon/ROCm 极致优化与复现

1101 [D/A/I/E] 打开官方 Notebook。

1102 [D/A/I/E] 记录 GPU 型号。

1103 [D/A/I/E] 记录总显存。

1104 [D/A/I/E] 记录可用显存。

1105 [D/A/I/E] 记录 ROCm。

1106 [D/A/I/E] 记录 HIP。

1107 [D/A/I/E] 记录 PyTorch。

1108 [D/A/I/E] 验证 BF16。

1109 [D/A/I/E] 验证 FP16。

1110 [D/A/I/E] 验证 backward。

1111 [D/A/I/E] 验证 attention。

1112 [D/A/I/E] 验证 VAE。

1113 [D/A/I/E] 验证 FLUX。

1114 [D/A/I/E] 验证 Wan。

1115 [D/A/I/E] 验证 LTX。

1116 [D/A/I/E] 验证 SeedVR2。

1117 [D/A/I/E] 验证 Real-ESRGAN。

1118 [D/A/I/E] 验证 Qwen3-VL。

1119 [D/A/I/E] 验证 Gemma4 critic。

1120 [D/A/I/E] 验证 adapter hotswap。

1121 [D/A/I/E] 建立模型串行驻留。

1122 [D/A/I/E] 建立显存回收。

1123 [D/A/I/E] 建立 CPU offload。

1124 [D/A/I/E] 建立 VAE tiling。

1125 [D/A/I/E] 建立 attention slicing。

1126 [D/A/I/E] 建立 prompt cache。

1127 [D/A/I/E] 建立 embedding cache。

1128 [D/A/I/E] 建立 KV cache。

1129 [D/A/I/E] 建立 workflow cache。

1130 [D/A/I/E] 建立 checkpoint resume。

1131 [D/A/I/E] 记录 p50 延迟。

1132 [D/A/I/E] 记录 p95 延迟。

1133 [D/A/I/E] 记录峰值显存。

1134 [D/A/I/E] 记录 GPU 利用率。

1135 [D/A/I/E] 记录 CPU 利用率。

1136 [D/A/I/E] 记录磁盘 I/O。

1137 [D/A/I/E] 记录模型加载时间。

1138 [D/A/I/E] 对照未优化路径。

1139 [D/A/I/E] 对照成熟 workflow。

1140 [D/A/I/E] 优化不降低质量。

1141 [D/A/I/E] 建立 OOM 恢复。

1142 [D/A/I/E] 建立 kernel 恢复。

1143 [D/A/I/E] 建立下载恢复。

1144 [D/A/I/E] 建立离线运行。

1145 [D/A/I/E] 建立干净实例脚本。

1146 [D/A/I/E] 运行干净实例。

1147 [D/A/I/E] 运行归档复现。

1148 [D/A/I/E] 输出 Radeon Report。

1149 [D/A/I/E] 输出性能证据。

1150 [D/A/I/E] 冻结 Radeon Evidence。
Workstream 24 — 下一代产品、演示与正式提交

1151 [D/A/I/E] 定义 AgencyLaunchRequest。

1152 [D/A/I/E] 定义 CampaignWorldState。

1153 [D/A/I/E] 定义 DistillationEpisode。

1154 [D/A/I/E] 定义 MemoryAtom。

1155 [D/A/I/E] 定义 RewardVector。

1156 [D/A/I/E] 定义 ModelCard。

1157 [D/A/I/E] 定义 AgencyEvalRecord。

1158 [D/A/I/E] 实现单端口 API。

1159 [D/A/I/E] 实现 POST /v1/runs。

1160 [D/A/I/E] 实现 run status。

1161 [D/A/I/E] 实现 SSE events。

1162 [D/A/I/E] 实现 approval。

1163 [D/A/I/E] 实现 bundle download。

1164 [D/A/I/E] 实现 model cards。

1165 [D/A/I/E] 实现 eval leaderboard。

1166 [D/A/I/E] 实现 World State UI。

1167 [D/A/I/E] 实现 future trajectory UI。

1168 [D/A/I/E] 实现 Agent topology UI。

1169 [D/A/I/E] 实现 Memory UI。

1170 [D/A/I/E] 实现 Distillation UI。

1171 [D/A/I/E] 实现 Training UI。

1172 [D/A/I/E] 实现 Audit UI。

1173 [D/A/I/E] 实现 Repair UI。

1174 [D/A/I/E] 实现 Human Gate UI。

1175 [D/A/I/E] 实现 12 图浏览。

1176 [D/A/I/E] 实现三视频预览。

1177 [D/A/I/E] 实现落地页预览。

1178 [D/A/I/E] 实现邮件预览。

1179 [D/A/I/E] 实现 Evidence Ledger。

1180 [D/A/I/E] 实现性能面板。

1181 [D/A/I/E] 完成实体产品全流程。

1182 [D/A/I/E] 完成 AI Agent 全流程。

1183 [D/A/I/E] 完成快速实时流程。

1184 [D/A/I/E] 完成完整质量流程。

1185 [D/A/I/E] 完成全部自动测试。

1186 [D/A/I/E] 完成全部真实模型测试。

1187 [D/A/I/E] 完成干净实例测试。

1188 [D/A/I/E] 冻结源码。

1189 [D/A/I/E] 冻结模型锁。

1190 [D/A/I/E] 冻结数据锁。

1191 [D/A/I/E] 更新英文 README。

1192 [D/A/I/E] 更新架构图。

1193 [D/A/I/E] 更新项目 PDF。

1194 [D/A/I/E] 更新海报/PPT。

1195 [D/A/I/E] 录制真实 Radeon 视频。

1196 [D/A/I/E] 生成提交归档。

1197 [D/A/I/E] 复验归档哈希。

1198 [D/A/I/E] Fork 官方仓库。

1199 [D/A/I/E] 创建合规 PR。

1200 [D/A/I/E] 完成 Final Evidence Seal。
四、六天作战编排
Day 1：赛制、复用目录、学术假设、蒸馏总架构、World State、Radeon preflight。
Day 2：数据供应链、4A Corpus、JEST 式筛选、自进化课程、金标审核。
Day 3：CPT、Curriculum SFT、OPSD/GKD/TCOD、RL、Adapter pseudo-MoE。
Day 4：动态 Agent、轨迹蒸馏、Brand Genome、4A GTM 员工能力、Web/API。
Day 5：FLUX/Wan/SeedVR2/rCM 成熟轮子组合、12 图、3 视频、全量审计、Top-3 盲评。
Day 6：消融、干净实例、Radeon 优化、PDF/README/海报/真实演示、官方 PR。
1200 项是原子验收单元，不等于 1200 个新功能；大量任务通过自动化 manifest、测试、基准、蒸馏数据生成和证据编译并行关闭。研究假设被证伪也属于有效完成，但不得进入最终产品。
五、最终边界
六天、单 Radeon、公开许可数据无法诚实保证一个未经外部验证的“全球官方前三”；能够交付的是以全球前三为硬目标、与三个最强开放基线做真实盲评和科学证据封存的系统。
真正的弯道超车点不是重新训练更大的基础模型，而是：把成熟开源模型和 workflow 蒸馏成统一 Campaign World Model，再通过 Agent 轨迹、4A 专家判断、区域级视觉奖励、任务型记忆和失败归因形成其他开源产品没有的闭环。
任何缺少 D/A/I/E 证据的“创新”、未经 Radeon 实跑的性能、未经盲评的 4A 或 Top-3 声明，均不得进入正式提交。

---

ProofLaunch Cortex‑X V10：1500 项“突破验证版”计划
一、总纲
规范基线为 Cortex‑X V9 的 0001–1200 项计划，全部继续生效；本计划新增 1201–1500，形成完整 1500 项。

新增 300 项不是继续堆 Agent、模型和功能，而是形成 12 个可证伪突破赌注，每个赌注恰好 25 项，并同时验证：

[T] 技术突破：与冻结开源基线对照，能被复现、消融和淘汰。
[P] 产品突破：改变 4A 人员完成 GTM 工作的方式，而非增加一个页面。
[X] 效果突破：使用盲评、时间留出、因果实验或真实业务指标验证。
所有新增项继续执行 V9 的 [D/A/I/E]：蒸馏/复用、学术假设、创新差异、证据封存。
研究失败允许结项，但必须提交负结果、失败原因和回滚证据；禁止用主观描述代替突破。
核心方向是把系统从“生成 Campaign 的多 Agent”升级为：

具有市场数字孪生、行动条件世界模型、Campaign Genome、证明携带型媒体、自进化组织、结构化视觉奖励、因果实验闭环和空间化协作界面的 4A GTM 数字员工。

二、20 位代表人物的公开思想坐标
以下仅提炼其公开研究或产品原则，不模拟私人观点、不宣称本人背书，也不构成人物排名。

模型研究坐标：10 位
Demis Hassabis：世界模型、搜索、规划、工具协同和“Move 37”式可验证创新。Google DeepMind 公开总结
David Silver：自博弈、策略价值联合学习、树搜索和从结果反向改进。AlphaGo Zero
Yann LeCun：在抽象表征空间预测、分层 JEPA 世界模型、忽略无关像素细节。Meta AI
Fei‑Fei Li：空间智能，将生成器、模拟器和规划器统一为可交互世界模型。World Labs
梁文锋／DeepSeek 团队：稀疏专家、辅助损失自由路由、MTP、算法—框架—硬件协同和高效蒸馏。DeepSeek‑V3
杨植麟／Moonshot 团队：原生视觉—语言持续预训练、交错工具调用和自组织 Agent Swarm。Kimi K2.5
林俊旸／Qwen 团队：开放原生多模态模型、工具调用和可部署 Agent 体系。Qwen
Chelsea Finn：元学习、从丰富文本反馈学习，而非把全部反馈压缩成单一奖励。Text Gradient
Sergey Levine：从离线经验、交互数据和强化学习获得持续适应能力。Berkeley AI Research
Percy Liang：多维度、透明、可复现的模型与多模态评测，拒绝单排行榜结论。HELM
AI 产品与 Agent 技术坐标：10 位
Andrew Ng：Reflection、Planning、Tool Use、Multi-Agent 必须落到可评测工作流。DeepLearning.AI
Harrison Chase：持久状态、可恢复执行、人机审批和可观测 Agent 控制流。LangGraph
Jerry Liu：事件驱动、可循环、可调试的复合 AI 工作流，而非僵硬 DAG。LlamaIndex Workflows
Bret Taylor：从一次对话转向跨天目标、关系记忆、持续学习和按结果交付。Sierra Horizon
Aravind Srinivas：不同模型协同、互联网行动能力以及“AI 即计算机”的统一工作面。Perplexity
Dylan Field：快速反馈、多人协作、提高创作上限，并让作品真正走到完成态。Figma
Guillermo Rauch／Vercel 团队：流式生成 UI、持久 Agent、审批、沙箱、超时和跨模型路由。AI SDK 7
Sam Altman／OpenAI 团队：从聊天转向可委派的长周期工作、共享上下文和数字同事。OpenAI Frontier
Thomas Dohmke／GitHub 团队：统一 Mission Control、并行 Agent、身份、权限、计划和治理。GitHub Agent HQ
Yamini Rangan／HubSpot 团队：以 Growth Context 连接全漏斗动作，区分漂亮输出与真实业务结果。HubSpot
三、新增核心接口与硬门槛
新增统一类型：

BreakthroughBetSpec：假设、基线、成功阈值、GPU 预算、淘汰规则、证据地址。
CampaignTwinState：受众、产品、品牌、渠道、竞争、资产、实验和结果状态。
CampaignGenome：Big Idea、SMP、RTB、品牌、视觉、运动、声音、渠道和约束的统一表示。
ProofManifest：Claim→Source→Asset Region/Frame→Transform→Approval 的可验证图。
AgencyTopology：Supervisor、角色、权限、状态所有者、预算、依赖和停止条件。
OutcomeEvent：干预、暴露、结果、时间、分群、随机化单元和数据质量。
BreakthroughEvidenceBundle：代码、配置、权重、数据权利、日志、消融、负结果、Radeon trace。
统一数据流：

Brief/Evidence → Market Twin → Campaign Genome → World-Model Planning → Agency Topology → Media Compiler → Proof Manifest → Human Approval → Experiment → Outcome Learning

新门槛覆盖 V9 中较低的同类指标：

4A 盲评平均分 ≥4.8/5，任何维度不得低于 4.6，直接可发布率 ≥97%。
对 5 个同硬件、同输入、同工具冻结基线的盲选偏好率 ≥80%，95% Wilson 下界 >70%。
GTM 冻结测试相对当前 Base 提升 ≥45%，相对未启用新增突破的 V9 提升 ≥20%。
通用多模态能力回归 ≤0.5%；Agent 端到端成功率 ≥99%，工具错误率 <0.2%。
关键无依据 Claim 为 0；Claim locator、素材来源和批准者覆盖率 100%。
图像 OCR ≥99.95%，品牌色 ΔE≤1.0，产品身份保持 ≥99.5%。
视频时序指标相对基础生成提升 ≥30%，音画对齐 ≥0.96。
任何转化率、收入或增长结论必须来自观察结果或合格实验；模拟结果统一标为 predicted。
12 个赌注全部产生证据；至少 3 个通过突破门，未通过者不得进入最终产品主路径。
核心证据必须来自官方支持的单张 Radeon/ROCm 环境。ROCm 7.2 支持矩阵
四、新增 300 TODO：12 个突破赌注
Breakthrough 25 — 因果市场数字孪生
1201 [D/A/I/E][T] 定义 Audience×Offer×Creative×Channel×Context→Outcome 因果本体。
1202 [D/A/I/E][T] 建立 observed、interventional、synthetic 三类数据隔离契约。
1203 [D/A/I/E][T] 为实体商品和 AI Agent 产品建立公开授权时间序列语料。
1204 [D/A/I/E][T] 显式建模季节、价格、渠道、品牌势能和选择偏差混杂项。
1205 [D/A/I/E][T] 实现相关性预测、倾向评分和 doubly robust 三组对照。
1206 [D/A/I/E][T] 建立适用于冷启动产品的分层先验和相似市场迁移。
1207 [D/A/I/E][T] 为所有孪生预测输出 conformal 区间和不确定性来源。
1208 [D/A/I/E][T] 冻结 TwinQuery/TwinPrediction 接口及可复现模拟种子。
1209 [D/A/I/E][P] 建立可直接操纵受众、渠道、创意和预算的 Twin Canvas。
1210 [D/A/I/E][P] 支持用户拖动一个变量并即时查看全漏斗后果变化。
1211 [D/A/I/E][P] 显示每个预测的主要驱动、反事实变化和置信区间。
1212 [D/A/I/E][P] 将已观察结果、模型推断和纯假设使用不同视觉编码。
1213 [D/A/I/E][P] 支持并排比较至少四个完整 Campaign 世界。
1214 [D/A/I/E][P] 为高混杂场景显示“无法可靠判断”并触发实验建议。
1215 [D/A/I/E][P] 一键把孪生差异编译成可执行 Campaign hypothesis。
1216 [D/A/I/E][P] 禁止将模拟 uplift 展示为真实收入或真实转化。
1217 [D/A/I/E][X] 使用严格时间留出测试孪生的未来结果排序能力。
1218 [D/A/I/E][X] 使用 Qini、AUUC 和 top-k uplift precision 评估干预排序。
1219 [D/A/I/E][X] 将 outcome ECE 压至 0.03 以下或封存失败结果。
1220 [D/A/I/E][X] 验证前 20% 推荐创意覆盖至少 60% 可获得 uplift。
1221 [D/A/I/E][X] 检查两垂直、渠道、受众和价格分群的稳定性。
1222 [D/A/I/E][X] 运行 placebo outcome、伪处理和时间倒置负控制。
1223 [D/A/I/E][X] 证明因果版本显著优于相关性预测，或淘汰该版本。
1224 [D/A/I/E][X] 盲测孪生辅助 Planner 与无孪生 Planner 的策略质量。
1225 [D/A/I/E][X] 仅在排序、校准和负控制同时过门时晋级。
Breakthrough 26 — 行动条件 Campaign World Model 2.0
1226 [D/A/I/E][T] 将 Campaign 状态定义为可观测、潜变量、动作和结果四层。
1227 [D/A/I/E][T] 训练 action-conditioned latent transition model。
1228 [D/A/I/E][T] 将文本、图片、视频、音频、渠道反馈映射到统一状态。
1229 [D/A/I/E][T] 建立价格、定位、素材、渠道和发布动作的类型化动作库。
1230 [D/A/I/E][T] 支持同一状态下至少八个反事实分支并行预测。
1231 [D/A/I/E][T] 用策略—价值网络引导束搜索或小型树搜索。
1232 [D/A/I/E][T] 在模型分歧过大时停止规划并请求证据或实验。
1233 [D/A/I/E][T] 将成功搜索轨迹蒸馏回单卡可运行 Planner。
1234 [D/A/I/E][P] 建立 Campaign 时间轴和未来状态预演界面。
1235 [D/A/I/E][P] 允许用户在任何节点 fork、比较、合并和回滚。
1236 [D/A/I/E][P] 在修改主张时自动标出受影响的资产和渠道。
1237 [D/A/I/E][P] 用结果卡解释动作的预期收益、风险和未知项。
1238 [D/A/I/E][P] 对失败预演生成精确到步骤的预防性修复。
1239 [D/A/I/E][P] 将高风险未来状态提升为人类批准节点。
1240 [D/A/I/E][P] 为每条路线生成决策依据，不输出隐藏思维链。
1241 [D/A/I/E][P] 世界模型不可用时无缝退回确定性 V9 主干。
1242 [D/A/I/E][X] 一步状态预测 top-1 准确率达到 95%。
1243 [D/A/I/E][X] 三步状态预测准确率达到 90% 且保持校准。
1244 [D/A/I/E][X] 失败归因 top-1 准确率达到 92%。
1245 [D/A/I/E][X] 与无搜索、固定深度搜索和纯 LLM Planner 对照。
1246 [D/A/I/E][X] 盲评策略质量相对最佳对照提升至少 15%。
1247 [D/A/I/E][X] 验证模型不会把不存在的渠道反馈写成事实。
1248 [D/A/I/E][X] 运行竞争降价、平台拒审和素材失效压力测试。
1249 [D/A/I/E][X] 将中位规划延迟控制在 30 秒、硬上限 120 秒。
1250 [D/A/I/E][X] 未同时通过预测、策略和成本门则停止晋级。
Breakthrough 27 — 原生多模态 Campaign Genome
1251 [D/A/I/E][T] 定义覆盖 SMP、RTB、Big Idea、品牌、视觉、声音和运动的 Genome。
1252 [D/A/I/E][T] 分离 brand、product、campaign 和 channel 四类潜变量。
1253 [D/A/I/E][T] 使用图文音视频正样本和硬负样本训练跨模态对齐。
1254 [D/A/I/E][T] 约束品牌身份稳定，同时允许 Campaign 创意变化。
1255 [D/A/I/E][T] 建立从战略概念到画面、文案、音频和镜头的传播器。
1256 [D/A/I/E][T] 将调性、张力、奢华度和证据密度变成可编辑轴。
1257 [D/A/I/E][T] 构造“画面漂亮但战略错误”等对抗负样本。
1258 [D/A/I/E][T] 实现 Genome 的组合、解耦、变异和确定性解码。
1259 [D/A/I/E][P] 建立 Campaign Genome Inspector。
1260 [D/A/I/E][P] 支持锁定产品、Logo、Claim 或 Big Idea 后局部探索。
1261 [D/A/I/E][P] 一次 Genome 编辑同步更新全渠道候选资产。
1262 [D/A/I/E][P] 同屏预览 landing、email、social、image 和 video 表现。
1263 [D/A/I/E][P] 显示每个资产继承了哪些 Genome 基因。
1264 [D/A/I/E][P] 支持 clone、mutate、cross 与 lineage 比较。
1265 [D/A/I/E][P] 支持从任意资产反向恢复其 Campaign Genome。
1266 [D/A/I/E][P] 在变异破坏主张或品牌时提供即时警告。
1267 [D/A/I/E][X] 跨模态 Campaign coherence 达到 95% 以上。
1268 [D/A/I/E][X] 单轴编辑的非目标属性漂移低于 2%。
1269 [D/A/I/E][X] 跨渠道产品身份保持率达到 99.5%。
1270 [D/A/I/E][X] 4A 盲评者跨模态 Big Idea 识别率达到 95%。
1271 [D/A/I/E][X] 新颖性提升时品牌分数下降不得超过 0.1/5。
1272 [D/A/I/E][X] 同一 Genome 生成候选的有效多样性提升至少 30%。
1273 [D/A/I/E][X] 对照 prompt-only、模板和普通 embedding 方案。
1274 [D/A/I/E][X] 在两个目标垂直分别执行跨渠道盲测。
1275 [D/A/I/E][X] 未证明一致性与可控性同时提升则不晋级。
Breakthrough 28 — Proof-Carrying Creative Compiler
1276 [D/A/I/E][T] 为证据、Claim、资产区域和变换建立内容寻址图。
1277 [D/A/I/E][T] 将每个显式及隐式 Claim 映射到事前支撑材料。
1278 [D/A/I/E][T] 将 Claim 映射到图像区域、视频帧段和音频时间段。
1279 [D/A/I/E][T] 为每次生成、编辑、放大和转码保留可重放构建记录。
1280 [D/A/I/E][T] 按当前 C2PA 规范写入 AI 来源和编辑动作凭证。C2PA 2.4
1281 [D/A/I/E][T] 编译 FTC 事前支撑、品牌规则和渠道规格硬约束。
1282 [D/A/I/E][T] 实现能定位最小失败区域的约束求解和修复器。
1283 [D/A/I/E][T] 冻结 ProofManifest/ProofVerificationResult 接口。
1284 [D/A/I/E][P] 建立覆盖图像、视频和页面的 Proof Lens。
1285 [D/A/I/E][P] 点击像素、文案或镜头即可查看来源和批准状态。
1286 [D/A/I/E][P] 在视频时间轴上显示 Claim 和编辑证据。
1287 [D/A/I/E][P] 修改 Claim 前预览全部下游影响。
1288 [D/A/I/E][P] 将缺证据和证据较弱使用不同严重度呈现。
1289 [D/A/I/E][P] 导出机器可读、客户可读和评委可读三种证明包。
1290 [D/A/I/E][P] 只有验证完整的资产才能获得 Release Badge。
1291 [D/A/I/E][P] 对外部篡改、丢失凭证和过期证据即时报警。
1292 [D/A/I/E][X] 关键无依据 Claim 保持为 0。
1293 [D/A/I/E][X] Claim→Source→Locator 覆盖率达到 100%。
1294 [D/A/I/E][X] 对受控篡改测试的检出率达到 100%。
1295 [D/A/I/E][X] 失败区域定位 IoU 达到 0.95。
1296 [D/A/I/E][X] 合法素材的错误阻断率低于 1%。
1297 [D/A/I/E][X] 验证凭证经缩放、转码和渠道封装后仍可验证。
1298 [D/A/I/E][X] 运行伪来源、过期批准和提示注入负测试。
1299 [D/A/I/E][X] 4A 合规审核时间相对 V9 降低至少 60%。
1300 [D/A/I/E][X] 只有零关键错误且审核提速时晋级。
Breakthrough 29 — 自进化 Agency Organization
1301 [D/A/I/E][T] 定义角色、权限、状态所有权、预算和终止条件。
1302 [D/A/I/E][T] 保持唯一 Supervisor 为权威状态所有者。
1303 [D/A/I/E][T] 将动态专家创建限制在可验证的 bounded L3 区域。
1304 [D/A/I/E][T] 训练 value-of-parallelism 预测器决定是否并行。
1305 [D/A/I/E][T] 从高质量轨迹学习任务分解和团队拓扑。
1306 [D/A/I/E][T] 建立冲突检测、证据仲裁和确定性合并协议。
1307 [D/A/I/E][T] 在时间、VRAM 和 token 预算下优化组织策略。
1308 [D/A/I/E][T] 将组织级成功、失败和协作模式写入独立记忆。
1309 [D/A/I/E][P] 建立可观察但不过载用户的 Agency Map。
1310 [D/A/I/E][P] 实时显示各角色目标、状态、依赖和剩余预算。
1311 [D/A/I/E][P] 允许用户合并、终止或重新授权专家。
1312 [D/A/I/E][P] 高风险权限必须由用户显式授予。
1313 [D/A/I/E][P] 为每个角色提供能力、限制和成功率卡片。
1314 [D/A/I/E][P] 将无法解决的角色冲突升级为单一审批请求。
1315 [D/A/I/E][P] 支持组织运行的 replay、fork 和失败回溯。
1316 [D/A/I/E][P] 提供快速、4A 和研究三种冻结组织配置。
1317 [D/A/I/E][X] 与固定拓扑对照端到端成功率。
1318 [D/A/I/E][X] 与无约束 swarm 对照成本、延迟和质量。
1319 [D/A/I/E][X] 协调开销不得超过总推理成本的 15%。
1320 [D/A/I/E][X] 重复执行率控制在 2% 以下。
1321 [D/A/I/E][X] 死锁、无限循环和孤儿任务发生率必须为 0。
1322 [D/A/I/E][X] 运行角色冲突、恶意专家和错误委派测试。
1323 [D/A/I/E][X] 消融动态创建、动态终止和组织记忆。
1324 [D/A/I/E][X] 用户认知负担不得高于单 Agent 主界面。
1325 [D/A/I/E][X] 只有质量提升覆盖协调成本时晋级。
Breakthrough 30 — 单模型多角色与 Sparse Adapter Experts
1326 [D/A/I/E][T] 定义可监督的角色、阶段和权限 token。
1327 [D/A/I/E][T] 构建 Evidence、Strategy、Creative、Art、Compliance 专家 Adapter。
1328 [D/A/I/E][T] 训练输入与状态条件 Adapter Router。
1329 [D/A/I/E][T] 实现无辅助损失或低干扰的专家负载平衡对照。
1330 [D/A/I/E][T] 将最终 Campaign 奖励分配回角色和关键步骤。
1331 [D/A/I/E][T] 训练 step-value 和 role-value 双层信用模型。
1332 [D/A/I/E][T] 比较热切换、加权合并和离线融合三种方式。
1333 [D/A/I/E][T] 冻结可在单 Radeon 热加载的压缩专家包。
1334 [D/A/I/E][P] 显示当前激活角色及其任务，不暴露隐藏思维链。
1335 [D/A/I/E][P] 显示路由置信度和可审计选择依据。
1336 [D/A/I/E][P] 允许比较两个专家组合的候选结果。
1337 [D/A/I/E][P] 允许高级用户固定或排除某一专家。
1338 [D/A/I/E][P] 路由异常时自动退回通用 Adapter。
1339 [D/A/I/E][P] 将全部晋级专家打包为单机可部署资产。
1340 [D/A/I/E][P] 支持只更新单一角色而不重训全系统。
1341 [D/A/I/E][P] 支持 Adapter 级版本对比和一键回滚。
1342 [D/A/I/E][X] 每个专家在目标任务上优于通用 Adapter。
1343 [D/A/I/E][X] 通用多模态回归不得超过 0.5%。
1344 [D/A/I/E][X] Router 的正确专家 top-1 选择率达到 95%。
1345 [D/A/I/E][X] 任一专家长期负载不得超过总负载的 40%。
1346 [D/A/I/E][X] 峰值显存不超过实测可用显存的 90%。
1347 [D/A/I/E][X] 信用分配与人类标注相关系数达到 0.8。
1348 [D/A/I/E][X] 对照单体模型、固定 Adapter 和多进程 Agent。
1349 [D/A/I/E][X] 证明质量—成本 Pareto 前沿发生外移。
1350 [D/A/I/E][X] 未获得专家增益或出现路由坍塌则淘汰。
Breakthrough 31 — 4A Creative Taste Foundation Model
1351 [D/A/I/E][T] 定义策略、创意、工艺、品牌、渠道和文化相关性评价本体。
1352 [D/A/I/E][T] 建立授权的成对偏好、批注、修复和拒绝语料。
1353 [D/A/I/E][T] 训练同时理解策略、文案、图像、视频和音频的 Critic。
1354 [D/A/I/E][T] 将 rich feedback 转换成可执行 text gradient。
1355 [D/A/I/E][T] 同时训练 pairwise preference 和局部错误定位。
1356 [D/A/I/E][T] 建立确定性检查、校准 Judge 和人类复核三级体系。
1357 [D/A/I/E][T] 建模不同 4A 评审者之间的合理分歧。
1358 [D/A/I/E][T] 分离“画面好看”“符合品牌”和“能解决业务问题”。
1359 [D/A/I/E][P] 建立精确到资产区域的 Creative Review Cards。
1360 [D/A/I/E][P] 每条 critique 必须包含规则、证据和可执行修复。
1361 [D/A/I/E][P] 支持从 critique 一键生成局部候选修复。
1362 [D/A/I/E][P] 提供受约束的创意张力和工艺标准控制。
1363 [D/A/I/E][P] 提供品牌型、效果型、文化型等通用评审模式。
1364 [D/A/I/E][P] 支持候选资产的相对评审而非孤立打分。
1365 [D/A/I/E][P] 将人类改判记录为 Judge 校准数据。
1366 [D/A/I/E][P] 只从明确批准的创意决策进入持续学习。
1367 [D/A/I/E][X] 使用至少 100 个人类标签校准，TPR/TNR 均 >80%。
1368 [D/A/I/E][X] 冻结盲评平均达到 4.8/5、各维度 ≥4.6。
1369 [D/A/I/E][X] 相对五基线的盲选偏好率达到 80%。
1370 [D/A/I/E][X] 至少 90% critique 被评为明确且可执行。
1371 [D/A/I/E][X] 一次针对性修复平均提升至少 0.4/5。
1372 [D/A/I/E][X] 运行 Judge gaming、长度偏差和风格偏差测试。
1373 [D/A/I/E][X] 验证两个垂直和不同渠道的泛化。
1374 [D/A/I/E][X] 对照单标量奖励、无反馈 Critic 和 rich feedback。
1375 [D/A/I/E][X] Judge 未校准或无法带来修复收益则不晋级。
Breakthrough 32 — Region-Time Structured Generative RL
1376 [D/A/I/E][T] 建立图像区域与视频时间段统一奖励张量。
1377 [D/A/I/E][T] 将全局奖励分解为对象、区域、帧和音频优势。
1378 [D/A/I/E][T] 接入产品、Logo、OCR、Claim 和品牌色保护掩码。
1379 [D/A/I/E][T] 接入运动、时序、镜头和音画对齐奖励段。
1380 [D/A/I/E][T] 训练选择最小成本修复算子的 Repair Policy。
1381 [D/A/I/E][T] 组合分块生成、Real‑ESRGAN/SwinIR 与视频修复。
1382 [D/A/I/E][T] 在放大、补帧和转码过程中持续锁定身份特征。
1383 [D/A/I/E][T] 每次局部修复均支持确定性回滚和消融。
1384 [D/A/I/E][P] 在资产上显示可交互的空间—时间质量热图。
1385 [D/A/I/E][P] 在视频时间轴显示问题段、奖励和修复状态。
1386 [D/A/I/E][P] 用户可接受、拒绝或保护某一修复区域。
1387 [D/A/I/E][P] 支持产品、Logo、人物和 Claim 的永久保护区。
1388 [D/A/I/E][P] 同屏显示修复前后和指标变化。
1389 [D/A/I/E][P] 支持整套 Campaign 的批量结构化审核。
1390 [D/A/I/E][P] 输出 3840×2160 或 2160×3840 的正式母版。
1391 [D/A/I/E][P] 在母版中保留模型、修复、放大和转码来源。
1392 [D/A/I/E][X] 图像与关键视频帧 OCR 达到 99.95%。
1393 [D/A/I/E][X] 品牌色 ΔE 控制在 1.0 以内。
1394 [D/A/I/E][X] 产品和 Logo 身份保持达到 99.5%。
1395 [D/A/I/E][X] 时序指标相对未修复基础提升至少 30%。
1396 [D/A/I/E][X] 音画对齐分数达到 0.96。
1397 [D/A/I/E][X] 首轮局部修复成功率达到 95%。
1398 [D/A/I/E][X] 运行小字、快速运动、粒子和复杂材质压力测试。
1399 [D/A/I/E][X] 对照全局标量奖励和全图重生成。
1400 [D/A/I/E][X] 未同时提升工艺质量和修复效率则不晋级。
Breakthrough 33 — Task-Focused Continual Brand Memory
1401 [D/A/I/E][T] 建立 entity、episodic、semantic、rule 四类记忆。
1402 [D/A/I/E][T] 训练 TaskMem 风格“应该记住什么”的选择器。
1403 [D/A/I/E][T] 学习 read、write、merge、forget 和 abstain 动作。
1404 [D/A/I/E][T] 为事实、偏好、批准和实验结果设置独立 freshness。
1405 [D/A/I/E][T] 建立品牌规则与新证据之间的矛盾图。
1406 [D/A/I/E][T] 将授权范围、删除权和数据来源绑定到记忆条目。
1407 [D/A/I/E][T] 训练保留决策信息的记忆压缩器。
1408 [D/A/I/E][T] 使用隔离 Adapter 进行可回滚持续学习。
1409 [D/A/I/E][P] 建立可审计 Brand Memory Inspector。
1410 [D/A/I/E][P] 显示每条记忆的来源、时效、置信度和影响范围。
1411 [D/A/I/E][P] 重要品牌记忆写入前必须获得批准。
1412 [D/A/I/E][P] 支持单条删除、时间点回滚和完整遗忘。
1413 [D/A/I/E][P] 建立品牌演进时间线和 Campaign 决策历史。
1414 [D/A/I/E][P] 明确解释本轮输出因哪些记忆发生变化。
1415 [D/A/I/E][P] 支持已验证学习跨 Campaign 迁移。
1416 [D/A/I/E][P] 对陈旧、矛盾或低置信记忆主动警告。
1417 [D/A/I/E][X] 记忆 precision 达到 99%。
1418 [D/A/I/E][X] 已标记陈旧事实的错误召回保持为 0。
1419 [D/A/I/E][X] 跨 Campaign 首轮通过率提升至少 20%。
1420 [D/A/I/E][X] 持续学习后的通用能力遗忘不超过 0.5%。
1421 [D/A/I/E][X] 运行记忆投毒、伪批准和权限绕过测试。
1422 [D/A/I/E][X] 运行品牌重定位和相互冲突规则测试。
1423 [D/A/I/E][X] 分别消融四类记忆和学习型选择器。
1424 [D/A/I/E][X] 使用连续 30 个模拟 Campaign 验证长期稳定性。
1425 [D/A/I/E][X] 未实现正迁移或出现污染则停止持续写入。
Breakthrough 34 — Outcome-Aware Test-Time Intelligence
1426 [D/A/I/E][T] 训练任务难度、不确定性和失败风险预测器。
1427 [D/A/I/E][T] 将任务映射为 direct、retrieve、search、simulate、team、human。
1428 [D/A/I/E][T] 定义质量、延迟、成本和风险多目标 Pareto 控制器。
1429 [D/A/I/E][T] 学习不同任务的推理深度、分支数和工具预算。
1430 [D/A/I/E][T] 建立基于边际收益的 learned stopping policy。
1431 [D/A/I/E][T] 对搜索树执行价值引导剪枝和失败分支早停。
1432 [D/A/I/E][T] 缓存可复用证据、模拟和已验证子轨迹。
1433 [D/A/I/E][T] 为模型、工具、搜索和显存失败定义降级路径。
1434 [D/A/I/E][P] 提供 Instant、Balanced、4A、Research 四档工作模式。
1435 [D/A/I/E][P] 在执行前显示时间、显存和质量预算。
1436 [D/A/I/E][P] 持续更新剩余时间和可交付资产。
1437 [D/A/I/E][P] 支持长任务暂停、恢复、迁移和安全取消。
1438 [D/A/I/E][P] 预算不足时优先保住证明、身份和可发布性。
1439 [D/A/I/E][P] 在完整包未完成时先交付已验证部分。
1440 [D/A/I/E][P] 超预算继续执行必须获得明确批准。
1441 [D/A/I/E][P] 提供控制器决策和成本的可重放记录。
1442 [D/A/I/E][X] 单位 GPU 时间的质量提升至少 30%。
1443 [D/A/I/E][X] 记录各模式 p50、p95 延迟和峰值显存。
1444 [D/A/I/E][X] 简单任务加速时质量不得发生显著回归。
1445 [D/A/I/E][X] 困难任务相对固定预算质量提升至少 20%。
1446 [D/A/I/E][X] 未经批准的硬预算突破次数为 0。
1447 [D/A/I/E][X] 停止置信度 ECE 控制在 0.05 以下。
1448 [D/A/I/E][X] 运行伪简单任务、工具挂起和不确定性压力测试。
1449 [D/A/I/E][X] 对照固定深度、固定 Agent 数和纯规则路由。
1450 [D/A/I/E][X] 只有质量—成本 Pareto 前沿外移时晋级。
Breakthrough 35 — Causal Experiment Autopilot
1451 [D/A/I/E][T] 定义 hypothesis、treatment、unit、metric、guardrail 实验 DSL。
1452 [D/A/I/E][T] 支持用户级、账户级、地区级和时间级随机化。
1453 [D/A/I/E][T] 自动计算 MDE、功效、样本量和预计周期。
1454 [D/A/I/E][T] 检查污染、重复暴露、网络效应和选择偏差。
1455 [D/A/I/E][T] 冻结带时间和数据质量标记的 OutcomeEvent。
1456 [D/A/I/E][T] 实现固定周期与顺序监测两类统计路径。
1457 [D/A/I/E][T] 接入 CUPED、分层估计和 doubly robust 分析。
1458 [D/A/I/E][T] 只允许从通过质量门的结果更新策略与孪生。
1459 [D/A/I/E][P] 从 Campaign hypothesis 一键生成实验方案。
1460 [D/A/I/E][P] 生成只改变目标变量的受控创意变体。
1461 [D/A/I/E][P] 为品牌、安全、成本和用户体验设置护栏。
1462 [D/A/I/E][P] 建立实时实验状态、风险和置信区间界面。
1463 [D/A/I/E][P] 展示总体与关键分群结果，禁止只挑有利分群。
1464 [D/A/I/E][P] 只有统计与业务阈值同时满足才推荐赢家。
1465 [D/A/I/E][P] 支持逐步放量、自动暂停和一键回滚。
1466 [D/A/I/E][P] 将验证结果写回 Twin、Genome 和 Memory。
1467 [D/A/I/E][X] 运行 A/A 测试并验证置信区间覆盖率。
1468 [D/A/I/E][X] 在已知真值的合成实验中恢复正确处理效应。
1469 [D/A/I/E][X] 自动检测 sample-ratio mismatch。
1470 [D/A/I/E][X] 无效实验的整体假阳性率控制在 5%。
1471 [D/A/I/E][X] 检查不同 uplift 区间的结果校准。
1472 [D/A/I/E][X] 使用历史 Campaign replay 验证推荐策略。
1473 [D/A/I/E][X] 有真实流量和授权时执行最小风险在线试验。
1474 [D/A/I/E][X] 强制区分 offline、predicted、observed、causal 四类效果。
1475 [D/A/I/E][X] 没有合格观察结果时禁止声称收入或转化突破。
Breakthrough 36 — 2027 Campaign Operating Space
1476 [D/A/I/E][T] 将主界面定义为空间化 Campaign Canvas，而非聊天窗口。
1477 [D/A/I/E][T] 统一 Brief、Evidence、Twin、Genome、Asset、Proof、Experiment 对象。
1478 [D/A/I/E][T] 建立多人、Agent 和自动化共享的实时状态协议。
1479 [D/A/I/E][T] 为每个数字同事建立身份、权限和审计边界。
1480 [D/A/I/E][T] 支持文字、语音、图片、视频和拖拽对象输入。
1481 [D/A/I/E][T] 支持任意状态的 time travel、fork、compare 和 merge。
1482 [D/A/I/E][T] 使用持久、幂等、可恢复的长任务执行层。
1483 [D/A/I/E][T] 将 Agent 输出渲染成可编辑生成式 UI 对象。
1484 [D/A/I/E][P] 用户可从 URL、产品图片或 Brief 在五分钟内建立项目。
1485 [D/A/I/E][P] 建立容纳策略、创作、证据和结果的 Campaign Room。
1486 [D/A/I/E][P] 允许像管理同事一样委派目标、期限和授权范围。
1487 [D/A/I/E][P] 建立实时生成、批注和局部修改的多模态 Storyboard。
1488 [D/A/I/E][P] 用 Proof Lens 取代独立、割裂的合规页面。
1489 [D/A/I/E][P] 建立 Strategy、Creative、Brand、Legal 联合 Review Room。
1490 [D/A/I/E][P] 将 simulate→approve→produce→ship 编译为单一可审计流程。
1491 [D/A/I/E][P] 建立发布后的 Outcome War Room 和持续学习循环。
1492 [D/A/I/E][X] 12 个核心用户任务的完成率达到 95%。
1493 [D/A/I/E][X] 首个可审创意概念在 12 分钟内交付。
1494 [D/A/I/E][X] 完整 12 图、3 视频、landing、email 包在 90 分钟内完成。
1495 [D/A/I/E][X] 每个 Campaign 最多需要一次主要批准和两次次要选择。
1496 [D/A/I/E][X] SUS 达到 90，NASA‑TLX 相对 V9 降低 30%。
1497 [D/A/I/E][X] 多人协作版的交付时间相对文件传递降低 50%。
1498 [D/A/I/E][X] 任意进程或工具失败后可从最近检查点恢复。
1499 [D/A/I/E][X] 4A 专业用户“愿意替代现有工作流”比例达到 80%。
1500 [D/A/I/E][X] 封存完整 V10 提交包、演示、负结果和 1500 项证据索引。
五、测试、作战编排与晋级机制
冻结对照
统一模型与工具条件下冻结五条系统基线：

当前 Cortex‑X V9。
确定性 LangGraph 工作流。
Qwen‑Agent 工具调用工作流。
Agent‑R1 风格步骤级 Agent。
无学习型世界模型的固定 4A Agency pipeline。
六日结构
Day 1：冻结数据、基线、接口和 12 个突破假设；完成小样本 smoke。
Day 2：完成 25–28 的最小实现、测试和第一次淘汰。
Day 3：完成 29–32 的最小实现、测试和第一次淘汰。
Day 4：完成 33–36 的最小实现、测试和第一次淘汰。
Day 5：按突破分数选择前三名进行训练、蒸馏、集成、全链路盲评。
Day 6：仅允许复现、失败修复、4K 母版、证据封存和正式提交，不新增功能。
突破分数固定为：

0.40×技术提升 + 0.30×4A产品提升 + 0.20×效果证据 + 0.10×单卡效率

存在安全、权利、证据、通用回归或 Radeon 复现硬失败的赌注直接淘汰，不参与分数排序。

必测场景
实体电商新品：产品图、证据文档、定价、受众和渠道约束完整输入。
AI Agent 新品：产品界面、能力证据、竞争资料和 B2B 决策链输入。
缺失证据、冲突品牌规则、竞争降价、渠道拒审、工具中断、显存不足。
Logo、小字、复杂材质、快速运动、人物身份和多渠道裁切。
记忆污染、过期事实、恶意专家、提示注入、伪批准和伪业务结果。
每次有意义变更至少回放 20–50 条真实轨迹；活评测集维持 100–500 个案例。
六、默认假设与不可伪造边界
“1500 项完成”指每项具有代码、测试、指标或明确负结果，不代表 12 项研究赌注都成功。
五天完成研究与产品主体，第六天仅作为赛制提交和证据保险日。
单 Radeon 无法进行前沿基础模型的全量预训练；采用公开授权数据上的定向 CPT、LoRA、Adapter、蒸馏、on-policy 小训练和系统—模型协同。
Kimi K2.5、DeepSeek、Qwen 等超出单卡运行能力的模型只提供公开架构思想、教师数据或离线基线，不伪装成本地完成大模型预训练。
核心提交路径只依赖许可允许、可在官方 Radeon 环境复现的组件；非商业权重必须独立标记并排除商业演示。
4K 视频指经过身份锁定、时序修复和质量验证的 4K mastered deliverable，不虚称基础生成模型原生逐像素 4K。
广告客观主张必须在发布前具有合理依据，遵守 FTC Advertising Substantiation。
“全球 Top‑3”“北美前十”只能表示冻结产品/赛题基准上的结果，不能表述为未经第三方验证的通用模型排行榜名次。
