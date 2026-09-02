# P2 Open — Demo 创意差异与后置 Agent 验收

> [TODO 入口](../TODO.md) · [任务目录](README.md)
> 本文件只包含未归档的创意 Agent 主链任务；是否在提交前投入以每项的 `提交决策` 为准。模型与通用 QA 任务见 [active-p2-models-quality.md](active-p2-models-quality.md)。

## 设计边界

> 固定决策链：`Project/Scene Evidence → 闭卷 Creative Briefs → 扩展式 RAG → Color Strategy → 确定性 ColorGraph Compiler → 真实候选渲染 → Visual Critic + QC → 选择/反思`。
> LLM/VLM 只负责诠释、发散、策略转译和视觉批评；不能直接改 Grade Graph、写像素、调用任意工具或绕过确定性校验。
> 第一版固定为每个 scene 三个方向、每方向 1–3 张代表帧、最多一次自动细化；在证据证明有必要前不引入 MCTS、强化学习或无界 Tree of Thoughts。
> 旧版“诊断卡—操作卡—参数—验证”只作为下游执行/安全基础设施：不得注入闭卷 Creative Director，不得建立 scene→emotion/look/parameter 的唯一映射，也不预设图数据库、知识卡数量或固定风格向量。

设计依据：

- [Video Color Grading via Look-Up Table Generation](https://arxiv.org/abs/2508.00548) 区分颜色分布匹配与 look、mood、emotion 等高层调色目标，并支持以显式 LUT 保持结构及时序。
- [AceTone](https://arxiv.org/abs/2604.00530) 证明语言/参考图到结构化颜色变换可行，同时报告含混、文化相关概念和仅使用全局 LUT 的局限；不能把一次语言映射当作唯一创意答案。
- [PhotoAgent](https://arxiv.org/abs/2602.22809) 支持多路径、低分辨率模拟和视觉反馈闭环；其通用审美奖励容易偏向鲜艳/高对比的风险必须通过本域评审和多维评价约束。
- [LumiVideo](https://arxiv.org/abs/2604.02409) 支持“感知—推理—参数执行—反思”的可解释路线；ColorGraph 应保留其参数化优点，但采用“先闭卷诠释、后检索”，并利用现有时空节点而不是退化为单一全局 LUT。

## 创意与检索

- [ ] **CG-CREATIVE-010 — 实现闭卷 Creative Director**
  - 提交决策：**`DEMO-GATE`，缩小验收后继续。** 至少冻结一个演示场景，使 `faithful`、`amplified`、`counterpoint` 在视频压缩后仍能一眼区分；正式三专家审计与生产级闭卷验收后置。
  - 提交前门槛：
    1. `faithful` 自然克制并保留原始气质，`amplified` 明显增强层次、色彩关系与情绪强度，`counterpoint` 给出合理且显著不同的反向表达；
    2. 三个方向都必须由真实候选渲染和 hard QC 支撑，不能只有文案或参数不同；
    3. 冻结场景、provider/model/revision、Grade Graph、候选输出、差异摘要和回放资产；
    4. 最终方案只由用户手动确认，保持 `auto_selection_allowed=false`。
  - 稳定性策略：实时 Agent 若仍不稳定，预缓存该冻结场景的三个真实候选；`Natural / Cool / Warm / Foggy` 四 Look A/B 只作为现场兜底，不替代主演示中的一次 Agent 创意命题生成。
  - 第一阶段不注入 Look recipe、参数卡或 RAG 结果，只使用 `ProjectContextPack` 和可选用户意图，先生成整片 `ProjectVisualThesis`、统一 palette/contrast character、scene/shot 叙事角色及允许偏离范围。
  - 每个 scene 固定生成三个真正不同的方向：`faithful` 保留素材原有气质、`amplified` 放大最有证据的情绪潜力、`counterpoint` 提出合理但不直观的反向诠释。
  - 每个方向必须引用支持与反对证据，说明视觉重心、情绪强度、与整片命题的关系、俗套风险和失败条件；“雪山=冷色”“夕阳=暖色”等无上下文捷径进入专门反模式测试。
  - 方向差异必须体现在叙事、视觉层级或色彩关系上，不能只替换形容词；证据不足时输出 `unknown/needs_user_intent`，不得伪造天气、主体、声音或作者意图。
  - Creative Director 不输出节点、LUT 名称或数值参数，且闭卷 briefs 落盘后不可被后续检索无痕改写。
  - 依赖：CG-AGENT-010、CG-AGENT-011、CG-AGENT-012。
  - 完成标准：雪山瀑布、阴天冬湖、晴朗镜面湖和同片互补 scene 的冻结案例都能产生三条有证据且互异的 briefs；专家审计无固定 scene→style 映射和无证据幻觉。
  - 2026-07-30 进度：
    - 已实现 `colorgraph.closed-book-creative-director/v1`：请求只接受签名 `ProjectContextPack`、可选签名用户意图和与 context 摘要一致的代表帧/联系表；prompt 明确隔离 RAG、知识卡、Grade Graph、LUT、节点和渲染参数。
    - 确定性审计覆盖逐 scene 三方向、结构差异、情绪差异、支持/反对证据、scene/shot scope、叙事角色、允许偏离、证据不足降置信、实现术语/数值参数和 scene→style 俗套捷径；模型输出审计不通过时 fail closed。
    - 雪山瀑布、阴天冬湖、晴朗镜面湖和同片互补 scene 冻结 fixture 专项 `11 passed`，连同 contracts/evidence/provider 为 `39 passed`；证据见 `output/evidence/closed-book-creative-director-v1.json`。
    - 真实 provider 模式现可在同一不可变请求链上运行 Director → Strategist → Critic，并保留每阶段 provider/model/revision 与结构化输出审计；后续 RAG 仍不能回写已经签名的闭卷 thesis/brief。
    - 已新增内容绑定的专家 review freeze/assemble 流程：真实 scene、全部候选、Gold 注释、许可证据、专家资格和原始提交均按 SHA-256 冻结，每名专家使用独立随机盲序；公开 assignment 不暴露 `full_pipeline` 或候选身份。
    - 早期真实 DJI `scene_001` intake 已取得本地 provider 闭卷 Director 回执，并把 3 个真实渲染、hard-QC pass 的 fallback 候选连同 41 项内容寻址资产冻结为 [`creative-review-dji-intake-v1`](../../output/evidence/creative-review-dji-intake-v1/README.md)；该历史包继续保留 Strategist/Critic fail-closed 诊断。
    - 后续 Qwen v8 已对同一冻结 scene 完成 provider 驱动的 Director、3/3 结构互异 Strategist、确定性 compile/render/hard QC 和换位 Critic，8/8 provider 调用成功且当前 graph 未改变，见 [`provider-pipeline-report-qwen-v8.json`](../../output/evidence/creative-provider-ollama-v1/provider-pipeline-report-qwen-v8.json)。原始结果明确 `reflection_stage: skipped-shadow-v1`，v2 内容绑定审计因此只把它归类为真实 `no_reflection` 技术种子，见 [`creative-ablation-dji-qwen-v8-v1`](../../output/evidence/creative-ablation-dji-qwen-v8-v1/README.md)；它补齐 provider 角色链证明，但不是正式 `full_pipeline`。报告仍明确 `formal_review_freeze=false` / `formal_release_eligible=false`；缺少至少 3 名合格独立专家对冻结生产案例的正式审计，因此本项保持未勾选。

- [ ] **CG-RAG-010 — 将调色知识改造成创意可能性空间**
  - 提交决策：**`DEFERRED`，完整后置。** 不在提交前建设完整授权语料库、双 reviewer 与 production owner 签核；Demo 只允许来源明确的少量内置卡或显式 `empty/OOD retrieval`，不得暗示生产知识库已经验收。
  - 知识发布边界分成三类：`CreativePossibilityCard` 保存 `concept / possible_visual_cues / possible_grade_strategies / alternatives / cliche_risks / counterexamples`；`OperationCard` 保存色彩域、依赖、参数语义和副作用；`FailureCard` 保存失败证据、检测与修复。三者均带 source/rights/version，但只有第一类进入本任务的创意检索。
  - Creative Director 看不到任何卡；Color Strategist 只读取检索后的 possibility cards，compiler 才读取 operation cards，QC/Reflection 才读取 failure cards，禁止把全部知识一次性塞给模型造成术语堆砌和创意锚定。
  - 对每个闭卷 brief 并行检索三路：同场景不同情绪、同情绪不同场景、反例/失败案例；使用元数据过滤与多样性约束，不能只返回最相似场景或同一风格近邻。
  - 闭卷 brief 冻结后，先按媒体、色彩域、作用域、能力、许可和保护属性做硬过滤，再做语义/图像相似检索；硬过滤负责准入，不能反向决定这个 scene 应表达哪种情绪。
  - 检索结果只扩展和质疑原 brief，不直接给出最终参数；保存 query、候选、分数、被选/被排除原因以及检索前后差异，检测 RAG 是否把不同方向重新锚定成同一种模板。
  - 首版只摄取来源、许可和用途明确的文本知识及可分发参考资产；未授权影视帧不得进入可发布索引，引用内容可删除并触发派生 embedding 失效。
  - 增加反检索和 OOD：没有可靠案例时返回空 bundle，而不是用低相关卡强行补齐。
  - 依赖：CG-CREATIVE-010。
  - 完成标准：冻结 query 的三路覆盖率、来源多样性、反例命中率和低相关拒绝率达到预设门槛；人工抽查不存在“一个场景唯一绑定一个情绪/配方”。
  - 2026-07-30 进度：
    - 已实现 `colorgraph.creative-possibility-retrieval/v1` 与三类严格卡契约；Creative Director 不读卡，创意索引只暴露 `CreativePossibilityCard`，`OperationCard` 和 `FailureCard` 分别保留给 compiler 与 QC/Reflection。
    - possibility 发布强制 source/version/rights/permitted-use/redistributable provenance；未授权参考资产和不可发布来源被拒绝，删除 source 会删除卡并失效其内容寻址 embedding。
    - 每个冻结 brief 保存三路 query、硬过滤、候选、相关分、选择/排除原因、检索扩展与质疑；媒体、色彩域、scope、能力、许可和保护属性先做不读取情绪的硬过滤，OOD 低相关结果返回显式空 bundle，来源/模板 MMR 与跨方向 convergence probe 防止重新锚定。
    - 冻结 fixture 的 9/9 路覆盖率、来源多样性、反例命中率与低相关拒绝率均为 `1.0`，模板收敛风险率 `0.0`，专项 `8 passed`；证据见 `output/evidence/creative-possibility-retrieval-v1.json`。
    - 新增 `colorgraph.creative-knowledge-corpus/v1` 生产摄取门禁：source snapshot、rights evidence、独立内容复核、独立权利复核和内容绑定 authorization 缺一即不建立索引；内容/权利 reviewer 必须分离，手改 authorizer 或任一 artifact 会失效。
    - 已冻结 ACES Documentation commit `773f9779…` 与 OpenColorIO v2.5.2 commit `c52966a…` 两个官方文本来源，形成覆盖三条检索路线、六个不同模板家族的真实 intake 草案；来源和许可文件已哈希，但 `authorized: false`，机器审计按预期只因两项未签核来源而失败并且不建立索引，见 [`creative-corpus-intake-v1`](../../output/evidence/creative-corpus-intake-v1/README.md)。
    - Qwen v8 `no_reflection` 技术种子继续使用显式 empty/OOD retrieval，没有绕过上述授权门禁，也不构成生产语料相关性结论。
    - 仍需独立内容 reviewer、独立 rights reviewer 和 production owner 对精确摘要/许可/授权摘要签核，并在真实冻结 scene query 上人工抽查；在此之前本项保持未勾选。

## 候选批评

- [ ] **CG-CRITIC-010 — 实现意图导向、维度化的 Visual Critic**
  - 提交决策：**`DEFERRED`，完整后置。** 不补至少 3 名专家的相关性、偏差与自动选择门禁；Critic 在 Demo 中最多作为建议和解释展示，最终必须人工选择并保持 `auto_selection_allowed=false`。
  - Critic 盲看原始/当前/候选帧、相邻镜头、声明的 brief 和允许例外，不接收配方名、候选作者或排序位置；A/B 顺序随机化并做位置交换一致性检查。
  - 输出独立维度：`concept_alignment`、`scene_support`、`visual_hierarchy`、`expressive_strength`、`naturalness`、`distinctiveness`、`overgrading_risk`、`context_consistency`；每项附 frame/region 证据、置信度和反证。
  - `technical_integrity` 只读取确定性 QC，不由 Critic 猜测或覆盖；先淘汰不可豁免失败，再保留多维 Pareto 集，禁止先压成单一 aesthetic score。
  - 成对比较必须回答哪个候选更连贯地表达其自身命题，而不是哪个更亮、更艳或更锐；增加通用“风景大片”、过度 HDR、青色雪、高饱和和压黑前景的偏置探针。
  - Director 与 Critic 的模型、prompt 和资产相互标识；评测同模型自评、独立模型和专家结果的相关性，相关性不足时不得让 Critic 自动选最终方案。
  - 依赖：CG-SEARCH-010、CG-QA-002、CG-AGENT-012。
  - 完成标准：冻结候选的结构化维度、证据和盲测顺序可复现；位置偏差、饱和/对比捷径和无证据评分低于预设门槛。
  - 2026-07-30 工程实现完成：`colorgraph.blind-visual-critic/v1` 对通过硬
    QC 的候选生成随机 A/B 与强制换位两次请求；prompt/asset manifest 不暴露
    candidate/strategy/card/作者/排序，八个维度各自必须引用本候选 frame-region
    证据和 source/current/neighbor 反证。technical integrity 只绑定确定性 QC
    摘要，模型不能重评或覆盖。
  - 输出审计拒绝未知/跨标签/缺候选/缺反证引用，并对位置偏好、换位分数漂移、
    “更亮/更艳/更高对比即更好”、通用 blockbuster landscape、蓝青雪、过度 HDR
    和压黑前景捷径 fail closed；provider/model/revision/prompt 与 Director 身份
    分开持久化。
  - 自动选择不再接受裸布尔开关。`colorgraph.critic-calibration-gate/v1`
    同时报告独立 Critic 和 Director 同模型自评相对专家偏好的覆盖率、accuracy
    Wilson 区间、MCC 相关性、位置不一致、捷径和无证据率，并绑定部署 Critic /
    Director 的精确身份；同模型自评、身份失配、相关性或任一门槛不足均只保留
    人工选择。程序化 fixture 为独立组 24/24、accuracy `1.0`
    `[0.8620, 1.0]`、MCC `1.0`，同模型基线 accuracy `0.6667`、MCC
    `0.3333`；专项 `18 passed`。证据见
    [`output/evidence/critic-010-engineering-validation.json`](../../output/evidence/critic-010-engineering-validation.json)。
  - 新增 `colorgraph.creative-critic-calibration-source/v1`：从内容绑定的 production
    expert bundle 和冻结的逐对 Critic 报告重新推导专家共识、独立/同模型关系、
    accuracy/Wilson、MCC、换位、捷径和无证据率；重复 report digest、身份失配、
    reviewer/authorizer 不独立或手写 gate 均不能放行。运行时只接受该审计器重算后
    的 gate，并将 gate digest 绑定到不可变 Agent 请求。
  - 程序化端到端 fixture 已验证 3 名独立 reviewer、10 份独立/同模型报告可通过，
    篡改任一原始专家提交或 Critic report 后立即回到 `shadow_only`。该 fixture
    不是专家 Gold 或真实 provider 结果；任务保持未完成，待生产模型 revision 与
    专家冻结偏好完成正式相关性/偏差门禁。
  - 本地 `colorgraph-gemma3:4b` 已在同一冻结 DJI 候选对上执行随机盲序与强制换位；16 维结构化输出分别触发 schema-invalid/容量截断并按设计 fail closed，原始 provider audit 已冻结进 [`creative-review-dji-intake-v1/run`](../../output/evidence/creative-review-dji-intake-v1/run/)。该失败证据不替代生产 Critic、专家相关性或偏差门禁。
  - 后续 `colorgraph-qwen3.5:9b` v8 已在真实冻结候选对上完成随机盲序与强制换位，两次结构化 Critic 均通过、位置选择一致、最大换位分差 `0.09`。它偏好 faithful、保留 amplified 为第二名，但因 `self_evaluation_model=true` 且未提供冻结专家校准，`calibration_authorized=false`、`auto_selection_allowed=false`；证据见 [`provider-pipeline-report-qwen-v8.json`](../../output/evidence/creative-provider-ollama-v1/provider-pipeline-report-qwen-v8.json)。仍需生产专家 bundle 上独立 Critic 与同 Director 模型的正式相关性、位置偏差、捷径和无证据率门禁，本项保持未勾选。

## 上线门禁

- [ ] **CG-AGENT-EVAL-010 — 建立创意 Agent 的本域评测与上线门禁**
  - 提交决策：**`DEFERRED`，完整后置。** 不做正式 10×8 消融矩阵、不补其余 79 次内容绑定运行，也不组织至少 3 名独立专家；当前工程 shadow 只保留为技术证据，不用于生产级优越性或上线声明。
  - 扩展 Gold Set/专家流程，标注画面证据、可接受的多个视觉命题、scene/shot 叙事角色、俗套/过调风险和跨镜头一致性；不为同一素材伪造唯一“正确风格”。
  - 主指标采用专家盲化 pairwise/多维评分：命题支持、表达连贯、视觉层级、独特性、自然度、过调率、技术失败率、跨 scene 连续性和方向多样性；LLM judge 只能作为经校准的辅助指标。
  - 对比当前固定四 Look/规则排序、单次 LLM、RAG-first、闭卷无 RAG、单方向、无 Critic、无 Reflection 和完整 pipeline；报告置信区间、评审一致性、位置偏差和模型自评偏差。
  - 增加同场景不同上下文、同情绪跨场景、含混/文化相关词、OOD、错误音频提示、Log 误读和 prompt injection/red-team 集；外部检索文本不能获得工具权限或改变系统约束。
  - 报告每分钟视频的调用数、token/费用、关键帧渲染数、端到端 P50/P95、失败/重试、缓存命中、VRAM 和人工接管率。
  - 依赖：CG-EVAL-001、CG-EVAL-004、CG-AGENT-UI-010。
  - 完成标准：冻结 test 和至少 3 名合格评审者证明完整 pipeline 相对规则基线有显著偏好提升，且不提高不可豁免失败率；此前只能 feature-flag/shadow，不能成为默认首版。
  - 2026-07-30 进度：
    - 已实现 `colorgraph.creative-agent-evaluation/v3` 及
      `creative-agent-eval` CLI：Gold 条目必须保留多条可接受视觉命题、frame-region
      证据、scene role、俗套/过调风险、连续性准则、冻结 split 和独立签核。
      每个候选还必须内容绑定 source media/graph、原始 run request/pipeline result、
      output、准确执行/禁用 stage、逐阶段独立证据、provider/model receipt 和方向
      差异；变体改标签、阶段证据复用、graph 变异或把跳过 Reflection 的运行冒充
      完整 pipeline 都会 fail closed。
    - 评测器覆盖规则、single LLM、RAG-first、闭卷无 RAG、单方向、无 Critic、
      无 Reflection 与完整 pipeline；报告八维专家评分、Wilson 95% CI、Fleiss κ、
      位置偏差、自评偏差、硬失败非劣、方向多样性以及每分钟调用/token/费用/
      渲染帧、P50/P95、重试、缓存、VRAM 和人工接管。
    - 七类上下文/OOD/错误音频/Log/prompt-injection 门禁已 typed 化，外部文本
      获得工具权限、改变系统约束或触发未授权调用会 fail closed；LLM judge 永远
      只作校准辅助。程序化专项通过，当前后端全量 `545 passed`（84 个测试文件），见
      [`agent-eval-010-engineering-validation.json`](../../output/evidence/agent-eval-010-engineering-validation.json)。
    - 新增 `creative-review-freeze` / `creative-review-assemble`：分别冻结真实
      test/候选/专家资格并生成独立盲序 assignment，再核验每份原始提交和归一化
      response 后组装 production manifest；qualification、raw submission 和
      normalized response 都有独立内容摘要。
    - 新增 `colorgraph.creative-agent-readiness/v1` 与
      `creative-agent-readiness`，统一审计本轮原 5 个任务的真实 provider、
      授权 corpus、production expert bundle、Critic calibration 和默认离线状态；
      它只写报告且 `configuration_changed=false`。当前 `CG-AGENT-012=true`
      并已归档，其余四项仍为 `eligible_to_archive=false`，见
      [`creative-agent-readiness-current-v1.json`](../../output/evidence/creative-agent-readiness-current-v1.json)。
    - 已形成真实 DJI scene/三候选的内容寻址 intake，并把 8/8 provider 调用成功的 Qwen v8 运行内容绑定为 `no_reflection` 技术种子；含原始 run request/result 的 13 项资产审计通过，但三方向平均像素距离 `0.0052276220` 低于完整链路门槛 `0.15`。新的 `creative-ablation-matrix-audit` 复核 seed 完整性后明确显示该 item 仍缺 7 个变体，整个 production test 还缺 9 个 item。pipeline 已支持显式 opt-in 的一次 bounded Reflection：无校准时只生成供人工评审候选且自动选择固定关闭，避免首次评审与校准互相等待。仍缺其余 79 个真实运行、媒体 owner/rights、accepted Gold、至少 3 名合格独立专家原始盲评、内容绑定 Critic 校准和正式相关性/偏差/上线门禁；当前 readiness 强制 `shadow_only`，本项保持未勾选且 Agent 不得成为默认首版。
