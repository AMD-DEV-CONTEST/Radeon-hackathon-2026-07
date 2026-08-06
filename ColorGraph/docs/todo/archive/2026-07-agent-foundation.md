# 2026-07 Archive — 创意 Agent 契约与证据基础

> [TODO 入口](../../TODO.md) · [任务目录](../README.md)
> 本文件归档已完成的创意 Agent 基础设施及其验收证据。

- [x] **CG-AGENT-010 — 冻结创意 Agent 的 typed 契约和状态机**
  - 定义版本化、`extra=forbid` 的 `TechnicalBaseline`、`ProjectContextPack`、`ProjectVisualThesis`、`CreativeBrief`、`RetrievalBundle`、`ColorStrategy`、`CompiledCandidate`、`VisualCritique`、`ReflectionPatch`、`FailureCase` 和 `AgentRunManifest`。
  - `CreativeBrief` 至少包含 `interpretation`、`evidence_for`、`evidence_against`、`emotional_target`、`visual_hierarchy`、`possible_color_language`、`cliche_risks`、`confidence` 和不确定项；只保存面向审计的简洁理由，不索取或持久化模型隐藏思维链。
  - 状态机固定为 `evidence_ready → interpreted → retrieved → strategized → compiled → rendered → criticized → selected → refined/ready`；每一步只读取已签名上游资产并生成新资产，不原地覆写上一步。
  - 每个资产保存 project/scene/shot ID、输入摘要、schema/prompt/model/tool 版本、创建时间、父资产 ID 和 SHA-256；重试必须幂等，过期图或上下文不能继续编译。
  - 将测量事实、技术诊断、艺术诠释和执行参数拆成不同 schema；下游可引用但不能改写上游事实或 `TechnicalBaseline`，自由文本、未知 enum、越权作用域和缺失证据不能进入 compiler。
  - 完成标准：合法 fixture 可完整 round-trip；缺字段、额外字段、旧摘要、跨项目引用、跳阶段、重复提交和越权 action 均有拒绝测试。
  - 验收证据（2026-07-29）：
    - 已实现 `colorgraph.creative-agent-contracts/v1`；要求的 11 类核心 payload 及 rendered/selection/ready 阶段 payload 均使用 strict、frozen、`extra=forbid` schema。`CreativeBrief` 强制保存支持/反对证据、情绪目标、视觉层级、可能色彩语言、俗套风险、置信度、不确定项和失败条件，不包含隐藏思维链字段。
    - `AgentRunLedger` 固定并验证完整状态路径；每项资产带 project/scene/shot、输入摘要、prompt/model/tool 版本、时间、父 ID/SHA 和自身 canonical SHA-256，content-derived asset ID 与 idempotency key 共同保证重试幂等。
    - `CreativeAssetStore` 原子、append-only 落盘 baseline、逐阶段资产、failure case 和带摘要 manifest；读取时复验签名、父链、项目身份和 manifest 清单。旧图/旧输入摘要、跨项目、跳阶段、重复提交、错误父资产、未知证据、越权 scene/shot/action、Critic 覆盖技术事实及 shadow 图被修改均拒绝。
    - 完整合法 fixture 的 9 阶段资产和 manifest JSON round-trip 通过，篡改落盘资产会在读取时失败；专项 `7 passed`，报告见 `output/evidence/creative-agent-contracts-v1.json`。

- [x] **CG-AGENT-011 — 构建整片/scene/shot 多模态证据包**
  - VLM 只接收经当前 Input/Display Transform 正确显示的预览，同时把 Log/scene-linear 物理统计作为独立数值证据；不得因直接观看扁平 Log 画面而把素材误判为雾、低对比或欠曝。
  - 由确定性工具先生成只读 `TechnicalBaseline`：输入/工作/输出空间、曝光/WB 测量、基础校正、shot matching 状态、信息已经剪切/丢失的证据和不确定性；Creative Director 不能用创意 Look 覆盖或伪装修复这些事实。
  - 复用多帧代表帧、前后镜头 contact sheet、scene grouping、曝光/WB 及不确定性、语义/深度资产、参考图相似度；新增可审计的构图、主体尺度、镜头/物体运动摘要。
  - 增加最小音频证据链：逐 shot/scene 的响度、动态、节奏/变化点和可选音频 embedding；转写、语义识别或云端上传必须单独声明能力、许可和用户同意，缺失音轨明确标记 `unknown`。
  - 先形成 shot evidence，再聚合 scene synopsis 和 project synopsis，避免把整片所有帧无界塞入单次请求；保留支持和反对聚合结论的 frame IDs。
  - 为图片数、分辨率、音频时长、token 和上下文长度设硬预算；超预算采用确定性采样并记录遗漏，不允许静默截断。
  - 依赖：CG-REP-001、CG-SCENE-001、CG-ANALYSIS-001。
  - 完成标准：雪景 Log、静态湖泊、快速瀑布、无音轨和跨 scene 项目均生成可复现证据包；任何描述性结论都能回溯到帧、时间段或测量值。
  - 验收证据（2026-07-29）：
    - 已实现 `colorgraph.agent-evidence-bundle/v1`：先按 shot 构建正确 Input/Display Transform 的 baseline preview、物理信号统计、构图 saliency proxy、camera/object motion residual、曝光/WB 事实与不确定性，再聚合 scene/project synopsis；模型只允许读取 display artifact，扁平 Log 编码值不会冒充视觉低对比。
    - 音频链显式探测轨道并分离记录响度 dBFS proxy、动态范围、节奏变化点和 embedding 状态；无音轨为 `no_track`，转写固定 `not_requested`，`cloud_uploaded=false`。
    - 图片数、最大边、音频时长、token 和 context bytes 使用 typed 硬预算；所有 omitted candidate ID 与原因落盘。每条 shot/scene/project 支持与反对结论都引用存在的 frame/time-range/measurement/audio evidence ID，contact sheet 也保存摘要与显示变换标记。
    - S-Log 雪景、静态湖面、快速局部运动、无音轨、跨 scene 和超预算 fixture 共 `3 passed`；同输入两次 bundle 摘要完全一致。真实 CUDA 150 帧/3 shot/2 scene 运行生成 5 个模型输入、2 张 contact sheet、17 条上下文证据且 traceability 全通过；报告见 `output/evidence/creative-context-real-evaluation.json`，完整资产见 `output/evidence/creative-context-real/`。
    - 上游感知模型输出继续标记为 observation/shadow 并保留不确定性；本项完成不代表 CG-ANALYSIS-001、CG-REP-001 或 CG-SCENE-001 的人工 Gold 门禁已通过。
