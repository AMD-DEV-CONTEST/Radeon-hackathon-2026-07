# 2026-07 Archive — 创意 Agent 离线 Shadow Pipeline

> [TODO 入口](../../TODO.md) · [任务目录](../README.md)
>
> 归档日期：2026-07-30。以下任务已完成实现、自动化回归与证据固化。

- [x] **CG-AGENT-012 — 接入可替换的多模态模型 runtime**
  - 建立 provider-neutral `CreativeModelProvider`，分别声明 Director、Strategist、Critic 所需的图像输入、结构化输出、上下文长度和批量能力；角色可使用不同模型，不能假设同一模型自评可靠。
  - 在 feature flag 后至少接入一个支持图像输入和严格 schema 输出的真实 provider；本地模型、云端模型和 OpenAI-compatible endpoint 分别报告真实能力，不把“接口兼容”表述为“结果等价”。
  - 配置 timeout、有限重试、取消、并发、速率、token/费用预算和 circuit breaker；保存 provider、model/revision、请求摘要、延迟、用量、失败类型和结构化响应，不记录密钥。
  - 云端上传代表帧/音频前显示明确的数据边界与同意；支持完全关闭网络。provider 不可用、预算耗尽或 schema 连续失败时，保留当前 CLIP + 规则 planner 作为可解释 fallback。
  - 缓存键包含角色、prompt/schema/model 版本与输入资产摘要；模型升级先 shadow 重放冻结输入，不能静默改变既有项目。
  - 依赖：CG-AGENT-010、CG-AGENT-011。
  - 完成标准：fake provider 契约测试覆盖成功、超时、429、取消、坏 JSON、拒答和预算中止；至少一个真实 provider 完成单 scene shadow run，且关闭网络后核心分析、规则命令和渲染仍可用。
  - 2026-07-30 完成：
    - `colorgraph.creative-model-provider/v4` 支持 Director、Strategist、Critic 独立路由、严格结构化契约、timeout/有限重试/取消、并发/速率/token/费用预算、circuit breaker、把输出上限绑定进内容寻址缓存，以及无密钥 JSONL 审计；OpenAI、OpenAI-compatible 与本地 boundary 分开报告。
    - 新增 feature-gated `ollama-generate-structural-local` 真实 provider：仅允许 loopback endpoint，使用 native Ollama Generate structured-output API；每次非缓存生成前后核对 Ollama runtime 版本、精确模型名、模型 SHA-256、`completion + vision` 与上下文能力，任一漂移均 fail closed。HTTP 层不再用隐式 5 秒超时覆盖受审计 runtime timeout。
    - 本机 Ollama `0.20.6` 的固定别名 `colorgraph-qwen3.5:9b@sha256:a2845456…3634` 对冻结 DJI 雪景 contact sheet 完成真实、非缓存结构化 shadow；实际加载上下文 `32768`，回执 `ollama_local_f60ba1a6f97aaded0984f6a2`、264/217 input/output tokens、`4.555 s`、请求/图片/运行配置摘要和 `project_state_mutated=false` 均已固化，见 [`provider-shadow-report-generate-qwen-v4.json`](../../../output/evidence/creative-provider-ollama-v1/provider-shadow-report-generate-qwen-v4.json)。
    - 同一固定 runtime 的 `run-qwen-v8-20260730T112152Z` 又完成 Director、3/3 Strategist、真实候选 compile/render/hard QC 与强制换位 Critic：8/8 provider 调用成功、3 个方向均 hard-pass、当前 graph 未改变，见 [`provider-pipeline-report-qwen-v8.json`](../../../output/evidence/creative-provider-ollama-v1/provider-pipeline-report-qwen-v8.json)。该回归证明本任务所需的 provider 角色链可运行；其原始结果明确跳过 Reflection，所以正式评测另将它内容绑定为 `no_reflection` 技术种子，绝不冒充 `full_pipeline`。这不影响已完成的 runtime 验收，也不替代剩余任务的人类门禁。
    - 图片全程留在 loopback，本次无需云端上传同意；云端 provider 仍要求网络 feature flag、本次运行确认与代表帧上传同意。所有 provider 默认关闭，默认环境复核仍为完全离线 fail-closed，规则 planner/renderer fallback 未改变。
    - 真实报告通过统一 readiness 的全部 12 项 runtime 门禁，`CG-AGENT-012.eligible_to_archive=true`；其余四项未因本任务放宽，见 [`creative-agent-readiness-current-v1.json`](../../../output/evidence/creative-agent-readiness-current-v1.json)。
    - Ruff 全仓通过，后端当前全量 `545 passed`（84 个测试文件），前端 TypeScript 与 Vite production build 通过。

- [x] **CG-STRATEGY-010 — 用 Color Strategist 转译视觉命题**
  - 输入不可变的闭卷 brief、`RetrievalBundle`、物理证据和 ColorGraph 能力目录，输出 typed `ColorStrategy`，不直接输出 Grade Graph。
  - `TechnicalBaseline` 只读且与创意层分离：基础曝光/WB、输入解释和 shot matching 不得被伪装成风格操作；创意 strategy 只能声明保留、轻微调整或有理由的例外，不能改写测量事实。
  - strategy 显式描述整片共同语言、scene/shot role、明暗结构、色彩关系、视觉重心、局部区域操作、节点类别、参数方向/范围、保护属性、候选例外和失败检测。
  - 每项操作引用它服务的命题和画面证据；一个情绪允许多种策略，一个策略必须说明未选择替代方案的理由，禁止从 scene label 直接查固定参数。
  - 同片 scene 可以有不同唤醒度和局部对比，但必须通过 project thesis 的 palette、雪/肤色中性、暖色额度或其他共享属性保持连续性。
  - 参数使用物理单位、归一化意图或经版本化 operation card 约束的范围；模型不能发明 renderer 不支持的参数、mask target、LUT 或作用域。
  - 依赖：CG-RAG-010、CG-AGENT-013。
  - 完成标准：三个 brief 可编译为结构明显不同但内部一致的 strategies；所有 action 均有证据、目的、范围和保护条件，未知能力在进入 compiler 前失败。
  - 2026-07-30 完成：
    - `colorgraph.color-strategy/v1` 只接受冻结 brief、签名 retrieval bundle、
      `TechnicalBaseline`、物理证据和 renderer capability catalog；creative action
      与基础曝光/WB、输入解释和 shot matching 分层，所有 action 均绑定命题、
      支持证据、目的、scope、参数范围、保护属性、替代方案和失败检测。
    - 策略审计逐 scene 比较 `faithful/amplified/counterpoint` 的结构差异，允许
      不同 scene 共享项目语言但拒绝同一 scene 的同义改写；未知 capability、
      参数、色彩域、mask、无证据 action、baseline 改写和 scene→recipe 捷径均在
      compiler 前 fail closed。
    - 离线真实链路在无获许可语料时使用显式 empty/OOD retrieval，3-scene 浏览器
      运行仍生成 9 个 typed strategy 并经正式 compiler/render/QC 完成 27 帧，
      当前图在确认前保持不变。Agent 专项 `148 passed`、后端全量 `422 passed`；
      证据见
      [`output/evidence/offline-creative-agent-pipeline-v1.json`](../../../output/evidence/offline-creative-agent-pipeline-v1.json)。

- [x] **CG-PLAN-010 — 将 ColorStrategy 确定性编译为 ColorGraph 候选**
  - 建立版本化 operation cards，将策略动作映射到已有 Balance、Tone、Look、Masked Grade、关键帧和组合 Mask Graph；cards 规定工具无关的物理/归一化参数语义、合法色彩空间、作用域、`reversibility/information_loss`、`requires_linear_light`、`must_precede/must_follow`、`conflicts_with`、`may_cause`、验证、修复和失效范围。
  - compiler 只接受 typed `ColorStrategy`，验证节点/作用域、参数边界、冲突、保护目标、mask 可用性、intentional exception 和 project/scene 连续性；不得调用 LLM 补字段。
  - 保持 Input/Working/Output Transform 和已经验证的 `TechnicalBaseline`，明确区分基础校正、shot matching、创意 Look 与局部语义节点；节点精确顺序由 operation card 依赖图确定，不能让模型用 LUT 修白平衡或声称恢复已剪切信息。
  - 对参数范围生成可复现的 nominal 方案及受预算的小幅变体；每个候选从同一基准图复制，保存 graph diff、父摘要、所用 card 版本和精确 undo graph，不直接写入当前项目。
  - 无效、越权或部分可编译 strategy 整体失败，不能静默丢弃不认识的 action；只有用户或选择器确认后才通过现有事务接口应用。
  - 保留 `landscape-grade-grammar/v2` 作为离线命令 fallback；规则 planner 和 creative pipeline 共享 compiler 校验，但前者不冒充 Creative Director。
  - 依赖：CG-AGENT-001、CG-STRATEGY-010。
  - 完成标准：合法 strategy 可稳定得到同摘要图；未知参数、错误空间、缺 mask、作用域外修改、保护冲突、过期输入和不可豁免 QC 绕过均被拒绝，原图保持逐位不变。
  - 2026-07-30 完成：`colorgraph.deterministic-strategy-compiler/v1` 只接受
    typed `ColorStrategy` 与版本化 `OperationCardRegistry`，先聚合校验 source /
    baseline 摘要、参数、工作空间、scope、mask、保护项、依赖图、例外绑定和
    mandatory QC，再按 card DAG 确定原生 Grade Graph 节点顺序；任何 violation
    都整批失败，不产生部分候选。
  - Balance、Tone、Look、Masked Grade、关键帧和组合 Mask Graph 均落到已有
    renderer 语义；Input/Working/Output Transform 与既有节点保持不变。nominal
    及有界变体从独立深拷贝生成，保存 source/strategy/card/compiled/undo 摘要、
    graph diff、card 版本与 mandatory QC；只有 `user` 或 `selector` 确认且
    source 摘要仍匹配时才能应用。
  - 同一 fixture 两次编译得到完全相同的 3 个候选摘要，原图逐字段不变且所有
    undo 摘要等于 source；未知参数、错误空间、缺 mask/组合 operand、越权 scope、
    冲突/环、保护冲突、过期输入、失配例外和 QC 绕过均有 fail-closed 回归。
    正式 renderer catalog 与 compiler 专项 `14 passed`、后端全量 `422 passed`；证据见
    [`output/evidence/plan-010-compiler-validation.json`](../../../output/evidence/plan-010-compiler-validation.json)。

- [x] **CG-SEARCH-010 — 实现有预算的“发散—渲染—收敛”候选运行器**
  - 默认每个 scene 编译 `faithful/amplified/counterpoint` 三个方向，每方向选择 1–3 张代表帧和必要的首/尾上下文；先渲染低分辨率真实关键帧，不渲染生成式替代图。
  - 候选必须走与正式输出相同的 ColorGraph renderer、色彩管理和 mask 语义；缓存键包含 context/brief/strategy/graph/renderer 摘要，预览与最终应用参数一致。
  - 记录基准帧、当前 grade 和每个候选，先执行不可豁免 QC，再把存活候选交给 Visual Critic；失败候选保留可定位证据而不是被静默删除。
  - 第一版预算固定为三方向、每方向一个 nominal 方案、最多一次自动 refinement，并限制模型调用、渲染张数、墙钟时间和费用；达到预算立即返回当前 Pareto 集。
  - 保留首选和第二名的完整资产，使用户“一键换方向”无需重新理解素材；在本域数据证明收益前不实现 MCTS/无界 ToT。
  - 依赖：CG-PLAN-010、CG-LOOK-UI-001。
  - 完成标准：多 scene 项目可中断、恢复和幂等重跑；候选之间不共享可变图，过期缓存不复用，预算在成功、失败和取消路径均不超限。
  - 2026-07-30 完成：`colorgraph.budgeted-candidate-search/v2` 强制每个 scene
    恰有 `faithful/amplified/counterpoint` 三个 nominal 候选，全项目最多一次
    refinement；从 context frame 与各 shot 首/中/尾确定性选择 1–3 帧，以正式
    ColorGraph engine、色彩管理和完整 mask storage 校验渲染 source/current/
    candidate，不生成替代图。
  - plan/cache 摘要绑定 context、brief、strategy、current/compiled graph、
    renderer 版本、source SHA-256/mask storage 输入摘要、采样计划和预算。完成态
    重跑会复核 graph/undo/contract/manifest 与全部图片的路径边界和内容摘要；
    损坏缓存不会复用，有剩余预算时只重渲染损坏候选。取消/恢复与多 scene
    幂等回归为 2 个 scene、6 个候选、取消时 2 个已完成，恢复后总 renderer
    call 仍为 6，第三次运行状态逐字段相同。
  - 不可豁免 QC 在 Critic 前执行，失败候选连同逐帧证据保留且不能被 ranker
    补偿；本地 renderer 额外记录未钳位 finite/gamut 观测，避免 PNG 钳位掩盖
    越界。model call、帧数、墙钟、费用和 refinement 在成功、渲染失败、取消及
    单次不可分割渲染超时路径均停止后续工作；首选、第二名及所有 survivor 完整
    资产持久化。专项 `10 passed`、后端全量 `422 passed`；证据见
    [`output/evidence/search-010-runner-validation.json`](../../../output/evidence/search-010-runner-validation.json)。

- [x] **CG-RANK-001 — 候选改为多帧硬约束/Pareto 筛选**
  - 候选覆盖多个 shot/关键帧，不再只看单张 JPEG。
  - clipping、gamut、结构、mask 完整性和不可豁免交付约束先做硬筛选。
  - 消费 Visual Critic 的独立维度和确定性 QC；意图、场景支持、视觉层级、独特性、自然度和过调风险不先压成固定 50/30/20 总分。
  - 选择轨迹显式经过四道门：交付/技术准入 → 意图与保护属性 → 镜内及镜间时序 → 可选人类偏好；前一道失败不能靠后一道高分抵消，声明的有意例外只作用于允许的默认保护项。
  - 对 Pareto 集执行可复现的盲化成对比较，并保留第二名；被淘汰候选必须有可定位证据。
  - 依赖：CG-SEARCH-010、CG-CRITIC-010。
  - 完成标准：同一输入和冻结模型响应得到相同 Pareto 集与选择轨迹；不存在单一“更艳/更亮”维度支配全部结果。
  - 2026-07-29 进度：
    - 已实现 `colorgraph.candidate-ranking/v2`：在当前 scene 内从 requested time、各 shot 四分位/中点和参数关键帧确定性抽取最多 7 帧，同一 recipe 批量渲染全部样本，不再用单张缩略图代表候选。
    - clipping、oversaturation、未钳位输出 gamut、Sobel 结构损失、mask 完整性和 NaN/Inf 先执行逐帧硬门禁；每个失败持久化 check、帧号、时间、观测值和阈值。意图、规则匹配、审美代理、保守度与技术余量保留为独立目标，已删除 50/30/20 选择逻辑；兼容字段 `combined_score` 只镜像 technical score，不参与排序。
    - maximize-only Pareto fronts、maximin/词典序稳定 tie-break 和 recipe ID 末级顺序已有确定性回归。真实 CUDA/CLIP 640×360、150 帧素材覆盖 3 个 shot；暗部硬门禁准确定位到帧 12/25，并返回 `unsafe-fallback-no-hard-pass`，没有伪装为安全推荐。专项 `8 passed`；报告见 `output/evidence/candidate-ranking-v2-evaluation.json`。
    - 2026-07-30 完成 `colorgraph.creative-candidate-ranking/v1` 集成：选择轨迹
      固定为 technical/delivery → intent/protection → within/between-shot temporal
      与 mask continuity → optional human preference 四门；每门完整分割输入、
      pass/rejection 和 frame/region 证据，后门不能复活前门失败。
    - technical gate 重算 compiled graph、undo、contract 与 source/current/candidate
      文件摘要；Critic 的 QC/render 摘要、换位一致性和区域证据重新绑定。八个
      Critic 维度保持独立 Pareto objective，overgrading risk 只反向归一化，不做
      固定加权总分；Pareto 集执行完整盲化 pairwise，自动选择还必须通过专家校准
      gate，同时保留第二名。
    - human preference 只能重排前三门保留且属于同 project 的候选；有意例外最多
      放宽 naturalness/overgrading 默认保护，不能越过 delivery hard gate。相同
      冻结输入两次得到同一 selection digest；摘要篡改、硬失败、意图/时序失败、
      不完整/位置偏差盲评与跨项目偏好均 fail closed。专项 `10 passed`、后端全量
      `422 passed`；证据见
      [`output/evidence/rank-001-four-gate-validation.json`](../../../output/evidence/rank-001-four-gate-validation.json)。

- [x] **CG-REFLECT-010 — 实现 state-aware 创意反思与最小修改**
  - 将 Critic 反证、QC 结果或用户反馈编译为 typed `ReflectionPatch`，只修改被点名的策略目标、节点、时间和区域；其他参数、保护属性及已确认 project thesis 显式锁定。
  - 每轮保存修改假设、预期改善维度、允许退化预算、graph diff 和回滚点；重新渲染同一证据帧并与父候选成对比较。
  - 自动首版最多细化一次；无 Pareto 改善、硬指标退化、意图漂移、重复 patch、低置信或预算耗尽时停止并回退父候选。
  - 用户后续“更壮阔/更克制/更孤寂/更梦幻”等反馈优先调整现有 thesis/strategy，不重新分析全片；确需改写命题时创建显式新分支。
  - 与 `CG-REPAIR-001` 分工：Reflection 优化创意表达，technical repair 只定位并修复技术责任节点，两者均不能越过对方的锁。
  - 被拒绝的候选或 patch 生成项目级 `FailureCase`，记录上下文、操作、实际损害、责任节点、修复与证据；只有通过人工审核、去除私有信息并版本化后才能晋升为通用 failure card 或回归 fixture。
  - 依赖：CG-RANK-001、CG-AGENT-013。
  - 完成标准：目标参数发生最小变化、未点名节点和 mask 摘要保持不变；接受、拒绝、停止、回滚和用户新分支均有事务与缓存回归。
  - 2026-07-30 完成：
    - `colorgraph.state-aware-creative-reflection/v2` 将 Critic 反证或项目内用户
      反馈编译为 typed patch；project/scene/shot/time/mask scope 必须与被点名
      的 creative-compiler 节点完全一致，除声明参数外的节点字段、保护属性、
      mask 摘要和 project thesis 绑定均不可变化。technical/color-management
      节点及非 compiler-owned 节点不能由 Reflection 修改，QC 技术失败只会
      回退并交给 Repair。
    - 编译资产原子保存 patch、refined graph、精确 rollback graph 和 contract；
      准备、缓存恢复与最终裁决均复核父/子真实文件摘要及同帧配对。本地 renderer
      开启 mask storage 校验并记录钳位前 finite/gamut 观测；cache key 绑定完整
      compilation、预算、renderer runtime、父证据内容及 mask storage，损坏
      manifest 会重建，越界路径/输出 fail closed。
    - 首版最多一次 refinement，换位盲评需要两次模型调用；无目标 Pareto 改善、
      非目标退化、意图漂移、硬门退化、父候选胜出、低置信、重复 patch 或预算
      不足均选择不可变父图。四类中文/英文反馈在既有 strategy 内调整，命题改写
      只能建立显式新分支且不重扫全片。
    - 所有拒绝均生成 project-bound private `FailureCase`；只有 source digest
      匹配且包含人工 reviewer、去私有确认和语义版本的 typed review 才能生成
      reviewed/redacted reuse artifact。专项 `14 passed`，Critic + Ranking +
      Reflection `42 passed`，后端全量 `422 passed`；证据见
      [`output/evidence/reflect-010-state-aware-validation.json`](../../../output/evidence/reflect-010-state-aware-validation.json)。

- [x] **CG-AGENT-UI-010 — 在工作台呈现可审计的 Agent 运行**
  - 展示整片视觉命题、scene role、三个方向、支持/反对证据、当前候选、第二名、保护属性、有意例外、QC 状态和 refinement diff；不展示或声称模型隐藏思维链。
  - 自动首版可只默认打开首选，但用户可无重算切换保留方向，并用结构化反馈或自然语言继续；应用前明确显示会修改的 scene/shot/range 和可撤销快照。
  - 显示 `analyzing/interpreting/retrieving/compiling/rendering/criticizing/refining` 状态、真实进度、取消、失败、预算和 provider；云端数据上传在首次调用前确认。
  - Agent 在 shadow mode 时不得自动覆盖当前 Grade Graph；旧规则命令、手动节点编辑、undo/redo 和离线模式保持可用。
  - 用户 A/B 选择只进入可删除、可导出的 project/user-scoped preference memory，不回写通用知识或他人项目；第一版只用于候选 tie-break 和默认强度偏好，不把历史选择当成新的审美真理。
  - 依赖：CG-REFLECT-010。
  - 完成标准：真实多 scene 项目的生成、取消、恢复、切换第二名、应用、撤销和离线 fallback 有 Playwright 回归，界面不出现伪候选、伪进度或静默云端上传。
  - 2026-07-30 完成：
    - 工作台接入真实后台 run：idle 可启动完全离线 Shadow，逐阶段快照展示真实
      `analyzing/interpreting/retrieving/compiling/rendering` 进度、预算和本地 provider；
      未运行时不生成占位候选。离线结果显式标记 Critic/Reflection 为跳过，不伪造
      critique、Pareto 或模型调用。
    - 每 scene 展示三个方向、支持/反对证据、保护属性、QC、候选缩略图和应用
      scope；首选与第二名无需重算即可切换。应用使用内嵌确认面板和 source digest
      乐观锁，保存精确撤销点；旧 snapshot 只有在其旧字段集 SHA-256 正确时才迁移。
      project/user preference memory 可删除、可导出且不跨项目写回。
    - 真实 3-scene/3-shot Playwright 运行完成 9 个候选、27/27 帧，切换第二名后
      显式确认应用并用全局撤销恢复原摘要
      `63cedbb34ec63f62a02bfc5f339e3d8047cf6e5a60efe74aef3517dd4b457a40`；
      最终快照回到 Shadow、`current_graph_unchanged=true`。
    - 另一个真实 3-scene 浏览器运行暴露并修复了启动快照与后台推进之间的
      optimistic-revision 竞态：控制前读取最新落盘快照，并只对精确 stale 冲突
      做有界重试，其他 409 继续 fail closed。Playwright 随后在 revision 2 请求
      取消、revision 3 于 22% 安全停止，revision 4 请求恢复、revision 5 继续，
      最终 revision 21 完成 9/9 候选；全程图摘要
      `9b5123c7e57585ef732e1b69d79bf2e0102b3e2ccbd8e50bda15107a6fd5b996`
      不变，浏览器 console 0 errors / 0 warnings，资源 host 仅为两个 loopback
      服务。截图见
      [`creative-agent-offline-multiscene-applied.png`](../../../output/playwright/creative-agent-offline-multiscene-applied.png)，
      [`creative-agent-cancelled.png`](../../../output/playwright/agent-ui-cancel-resume/creative-agent-cancelled.png)
      和
      [`creative-agent-resumed-complete.png`](../../../output/playwright/agent-ui-cancel-resume/creative-agent-resumed-complete.png)；
      完整证据见
      [`agent-ui-010-browser-validation.json`](../../../output/evidence/agent-ui-010-browser-validation.json)。
