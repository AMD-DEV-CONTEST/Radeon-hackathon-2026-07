# ColorGraph 项目现状与新对话接手指南

> 最后核对：2026-08-02（Asia/Shanghai）
> 工作区：`C:\pb\programs\color`  
> 用途：新对话或新开发者接手时优先阅读的单文件上下文。  
> 详细产品愿景见 [PROJECT_SPEC.md](PROJECT_SPEC.md)，逐项审查见 [IMPLEMENTATION_AUDIT.md](IMPLEMENTATION_AUDIT.md)，算法调研见 [ALGORITHM_RESEARCH.md](ALGORITHM_RESEARCH.md)，执行清单见 [TODO.md](TODO.md)，AMD 迁移见 [ROCM_BACKEND.md](ROCM_BACKEND.md)。

## 1. 一句话状态

ColorGraph 已从静态界面 Demo 推进为可运行的本地风景视频 AI 调色 MVP：

```text
视频 + 可选参考图 + 自然语言
→ 媒体/镜头/色彩/场景分析
→ Typed Grade Graph
→ 语义与深度时序蒙版
→ GPU 确定性调色、关键帧和组合 Mask Graph
→ 候选 A/B、质量验证与定向修复
→ MP4 + LUT + JSON + 蒙版 + 质量报告
```

日常开发机仍使用 NVIDIA GPU + CUDA；比赛目标链路已经在 Radeon Cloud 的 AMD Radeon `gfx1100`/48 GB 实机上通过统一 ROCm 门禁。设备、推理、渲染和编码层均保持隔离，AMD 结论只引用实机报告，不从 CUDA 结果外推。

> **2026-08-02 当前修复状态：** Sony/显式色彩变换、输入元数据、CFR/VFR 高位深 PTS、逐场景 LUT、自然语言 project scope、mask 资产完整性、完整 OCIO 2.5.2 / ACES 2 v3 运行时、v3 标准调色算子和离线创意 Agent Shadow Pipeline 均已落地；统一评测、严格 Gold Set 审计和可移植精度门禁也已完成。CUDA 与 Radeon Cloud ROCm 门禁均已实测通过，真实素材摄取队列已有 6 个授权来源并补齐明确相机夜景与项目声明的 DJI D-Log；私有 Log 片段只获准用于项目内评测。本地真实多模态创意 provider 已完成正式 shadow 验收；仍未完成的是达到配额并独立签核的人工 Gold Set、获授权检索语料和专家上线评测，因此仍不应宣称完整达到母版交付或默认 Agent 上线标准。

## 2. 当前目标边界

上一阶段已经完成的目标是：

> 在不制作比赛提交材料、暂不进行 AMD 实机专项的前提下，完成真实可运行的本地视频调色 MVP，并用 NVIDIA CUDA 建立开发和性能基线。

目前明确不包含：

- 比赛项目简介 PDF；
- PPT、海报和 3–5 分钟演示视频；

这些内容只是当前阶段排除项，不代表以后不能继续。

## 3. 2026-08-02 实测基线

### 3.1 开发环境

| 项目 | 实测值 |
| --- | --- |
| 操作系统 | Windows |
| GPU | NVIDIA GeForce RTX 5060 Ti |
| 显存 | 16,311 MB |
| PyTorch | 2.12.1+cu130 |
| CUDA runtime | 13.0 |
| GPU capability | 12.0 |
| FFmpeg / FFprobe | 8.1 |
| Python | 3.12（由 uv 管理） |

本地 CUDA 开发环境的 `colorgraph doctor` 返回 `migration_compatible: true`，只表示代码路径没有绑定 CUDA 专属扩展；Radeon Cloud 则另以真实 `runtime=rocm`、HIP、机器探测驱动和统一 `passed` 报告完成实机验收。

### 3.2 最新回归结果

以下命令于 2026-07-30 重新执行：

```powershell
uv run --project backend ruff check backend\colorgraph backend\tests
uv run --project backend pytest -q
npm run typecheck
npm run build
uv run --project backend colorgraph doctor
```

结果：

- Ruff：全仓通过；
- Pytest：602 passed（90 个测试文件，2026-08-02 全量回归）；
- TypeScript：通过；
- Vite production build：通过；
- CUDA、FFmpeg、FFprobe 与固定 OCIO/ACES config/cache 自检：通过。
- CUDA `precision-gate`：母版像素误差、ΔE2000、preview 和三次确定性均通过；报告见 `output/evidence/cuda-precision-gate.json`。
- Gold source intake：6/6 来源已就绪，6/6 许可可商用，5 个明确相机，19 个机器镜头草稿；6,078 帧的精确 PTS 工作包已冻结，状态仍仅为待人工标注。
- Gold 验收 runner 已补齐内容感知曝光/WB、代表帧、scene 基线比较、领域排序与约束修复指标，并强制重算不低于 P0 的审计、v2 规范哈希、完整冻结 test 覆盖、source 隔离及带实际 observation 文件哈希的 calibration-only gate policy；工程公式门槛已通过但报告明确为 `engineering_only` / `release_eligible=false`，真实人工 Gold 仍是唯一外部缺口，见 `output/evidence/gold-acceptance-engineering-validation.json`。`CG-COLOR-003` 与缩小后的 `CG-BENCH-001` 已完成归档；人工 Gold、`FROZEN` 和全部 `DEFERRED` 项仍不在提交前推进范围。
- 内容感知色彩分析的雪景、夜景、日落、混合光、天空中性地面、孤立闪烁和快速曝光合成门禁通过；报告见 `output/evidence/content-aware-color-analysis.json`。该报告不是专家或 Gold Set 验收。
- 多帧代表帧的真实本地 CLIP medoid/鲁棒 shot embedding 链路通过；报告见 `output/evidence/representative-frame-evaluation.json`。冻结 Gold Set 的可用率和 scene 指标仍待人工真值。
- Scene grouping v2 的连续多模态边界分数、calibration-only 阈值搜索和全局解码已进入 shadow；报告见 `output/evidence/scene-grouping-shadow-evaluation.json`。默认仍使用旧贪心 groups，等待冻结 test 授权切换。
- SegFormer-B0 固定 revision 的逐类映射、互斥 alias 和置信度语义审计通过；报告见 `output/evidence/semantic-mapping-audit.json`。
- DA-V2 Small fallback 的 shot 尺度/不确定性修复及 VDA-S Apache-only shadow
  适配器已实现。官方 VDA-S exact repo/checkpoint 已安装并严格哈希；150 帧真实
  CUDA shadow 为 `0.380 FPS`、峰值 GPU `8039.08 MiB`，float depth 与时序残差
  保持在内容寻址 NPZ 中。它仍不接管默认 mask，见
  `output/evidence/depth-001-vda-small-shadow-report.json`。
- Creative provider runtime 已实现角色独立路由、显式能力、严格结构化契约、预算/重试/取消/circuit、离线 fallback、内容寻址缓存与不含密钥的审计；真实 provider 路径贯通闭卷 Director → Strategist → 盲化 Critic。仅限 loopback 的 native Ollama Generate adapter 会在每次生成前后核对 runtime/version/model SHA/vision/实际加载 context；本机 Ollama `0.20.6` 的 `colorgraph-qwen3.5:9b@a2845456…3634` 已在 `colorgraph.creative-model-provider/v4` 下完成非缓存结构化 shadow，回执 `ollama_local_f60ba1a6f97aaded0984f6a2`，实际上下文 `32768`，见 `output/evidence/creative-provider-ollama-v1/provider-shadow-report-generate-qwen-v4.json`。默认 provider/网络仍关闭，统一 readiness 已放行并归档 `CG-AGENT-012`。
- 批量 renderer 已加入向量化轨道执行计划、自适应 active-graph 分组与恒等操作消除；1080p FP32 静态/PCHIP 图提升 `1.095×/1.107×`，误差保持在 master 预算内，见 `output/evidence/batch-rendering-perf-002.json`。
- CLIP/SegFormer/Depth Anything 使用租约保护的共享 LRU、内容摘要 embedding 缓存和阶段释放；两项目真实 CUDA shadow 峰值 `1394.31 MiB` 且释放后模型条目归零，见 `output/evidence/model-lifecycle-cache-benchmark.json`。
- mask asset 升级为 v3 `gray16le` FFV1 主资产与持久 FFmpeg batch decoder；默认删除临时 PNG。640×360 五 target 预计 `0.63 GiB/min`、串行折算 `66.03 FPS`，软边界量化误差较 8-bit 降低 `256×`，见 `output/evidence/mask-precision-benchmark.json`。
- 质量报告升级为 `colorgraph.quality-report/v2`，技术硬失败、感知风险和校准后的辅助审美偏好已分离；新增版本化 CAMBI 等价 banding 指标，并在真实 Main10 与旧成片上复验，见 `output/evidence/quality-report-v2-evaluation.json`。
- 时序质检升级为源视频运动补偿的 `colorgraph.motion-compensated-temporal/v1`：逐转场区分相机/物体运动、云水运动、真实亮度变化、源曝光跳变和调色闪烁，并输出区域与蒙版边界证据。固定种子回归中 flicker 与 mask 的旧指标误报率分别从 `60%/54.55%` 降至 `0%/0%`，局部闪烁召回同步改善，见 `output/evidence/qa-001-motion-compensation-benchmark.json`。
- Verifier 已升级为预算化责任节点消融与多轮局部修复：候选必须同时满足目标改善、硬指标不退化、非目标质量不降级和意图漂移上限，否则原 graph/成片保持不变。8 个固定工程 fixture 为 4/4 安全接受、其中 3/4 完全转 PASS，4/4 应回滚案例均回滚且 unsafe acceptance 为 0；这不是人工 Gold Set 结论，正式任务仍等待签核集，见 `output/evidence/repair-search-engineering-benchmark.json`。
- 领域偏好排序新增 `colorgraph.domain-bradley-terry/v1`：source 级 train/calibration/test 隔离、train-only reviewer reliability、calibration-only 温度和 test source-cluster bootstrap 均已进入统一 evaluation runner。60-source/2400-rating 固定工程 shadow 显著优于规则胜场、CLIP、SigLIP2，但它不是专家 Gold Set，`CG-RANK-002` 仍等待独立冻结集签核，见 `output/evidence/rank-002-engineering-shadow.json`。
- `CG-PLAN-010` 的 `colorgraph.deterministic-strategy-compiler/v1` 已完成：typed strategy 经版本化 operation cards 编译为原生 ColorGraph 候选，同输入摘要稳定，nominal/有界变体互不共享状态并携带精确 undo graph；未知字段、错误空间、缺 mask、越权 scope、依赖冲突、过期输入、例外失配和 mandatory QC 绕过均整批拒绝，见 `output/evidence/plan-010-compiler-validation.json`。
- `CG-SEARCH-010` 的 `colorgraph.budgeted-candidate-search/v2` 已完成：每 scene 三方向使用真实关键帧和正式 renderer，在 Critic 前执行未钳位硬门禁；多 scene 可取消/恢复并幂等重跑，plan/cache 绑定输入摘要和预算，完成态会重验全部资产且损坏缓存不复用，见 `output/evidence/search-010-runner-validation.json`。
- Visual Critic 已完成盲化 A/B、强制换位、八维 frame-region 证据/反证和审美捷径审计；裸 `calibration_authorized` 已删除，自动选择必须通过绑定 Critic/Director 精确身份的专家相关性 gate，同模型自评永不自动放行。Qwen v8 已在真实冻结候选对上完成两次换位 Critic，位置一致且最大换位分差 `0.09`；因为它是 Director 同模型自评且没有内容绑定专家校准，`calibration_authorized=false`、`auto_selection_allowed=false`。`CG-CRITIC-010` 仍等待至少 3 名独立专家与正式相关性/偏差门禁，见 `output/evidence/creative-provider-ollama-v1/provider-pipeline-report-qwen-v8.json` 和 `output/evidence/critic-010-engineering-validation.json`。
- Critic calibration 已升级为内容绑定的 production source：从专家 bundle 与逐对冻结 Critic reports 重算专家共识、独立/同模型关系、相关性、位置/捷径/无证据率；重复报告、身份不符、原始专家提交篡改或手写 gate 均不能放行。运行时只接受重算通过并绑定请求 digest 的 gate。
- `CG-RANK-001` 已完成四门选择轨迹：delivery hard gate → intent/protection → within/between-shot 与 mask temporal → optional project-scoped human preference；八个 Critic 维度保持 Pareto objective，完整盲评与专家校准 gate 决定是否可自动选择，所有 graph/render 摘要在准入时复核且保留第二名，见 `output/evidence/rank-001-four-gate-validation.json`。
- `CG-REFLECT-010` 已完成 state-aware 最小反思闭环：typed patch 只能修改点名的 creative 参数及完全匹配的 project/scene/shot/time/mask scope；完整 compilation、预算、renderer 输入、父子证据和 mask storage 均进入缓存/裁决复核，非法输出、证据篡改、无 Pareto 改善、技术/意图退化、重复/低置信/预算不足均回退不可变父图。被拒绝结果只生成 project-private FailureCase，通用晋升必须经过绑定 source digest 的人工审核、去私有和语义版本门禁，见 `output/evidence/reflect-010-state-aware-validation.json`。
- 离线创意 Agent 已贯通 Project/Scene Evidence → 闭卷三方向 brief → empty/OOD retrieval → typed ColorStrategy → deterministic compiler → 正式 renderer/QC → 可审计 UI；后台运行支持取消、持久恢复和幂等重跑，Critic/Reflection 未配置时显式标为跳过，不伪造模型输出。3-scene/3-shot 实跑生成 9 个方向候选并完成 27/27 帧，确认前保持当前图不变，见 `output/evidence/offline-creative-agent-pipeline-v1.json`。
- `colorgraph.creative-agent-evaluation/v3` 与 `creative-agent-eval` CLI 已实现规则基线、single LLM、RAG-first、闭卷无 RAG、单方向、无 Critic、无 Reflection 和完整 pipeline 的冻结评测；每个 observation 必须内容绑定 source media/graph、原始 run request/pipeline result、output、实际执行与禁用 stage、逐阶段独立证据、provider/model receipt 和方向差异，改标签、复用阶段证据或把跳过 Reflection 的运行冒充完整 pipeline 都会 fail closed。报告八维专家评分、Wilson 95% CI、Fleiss κ、位置/自评偏差、硬失败非劣、red-team 与运行成本。工程 fixture 只验证 evaluator 并强制 `shadow_only`；缺少冻结生产集和至少 3 名合格专家时不能成为默认首版，见 `output/evidence/agent-eval-010-engineering-validation.json`。
- pipeline 新增显式 opt-in 的 bounded Reflection Shadow：确定性 planner 只改一个 compiler-owned 数值参数并受 operation-card 域约束，随后重新渲染、hard QC 和换位盲评；未校准运行只可形成待人工评审候选，`automatic_selection_allowed=false`，当前图始终不变。工程 fixture 同时覆盖独立校准和无校准 bootstrap，不制造发布授权。
- 创意正式证据链新增 `creative-review-freeze` / `creative-review-assemble`：真实 Gold/候选/许可、专家资格、每人独立随机盲序、原始提交和归一化 response 全部内容绑定；3-expert 端到端 fixture 可到 `eligible_default`，篡改任一提交立即退回 `shadow_only`，但 fixture 不冒充真实专家。
- 已把真实 DJI `scene_001`、3 个 hard-QC pass 候选、闭卷 Director 回执、编译/渲染/失败审计和源 proxy 冻结为 41 项内容寻址 intake，清单 SHA-256 `8c0585fd…923f4` 且独立复核 0 项不一致，见 `output/evidence/creative-review-dji-intake-v1/`。该包同时记录候选来自 Strategist fail-closed 后的确定性 fallback、Critic schema/容量失败及方向收敛风险，明确 `formal_review_freeze=false`，不冒充 owner 授权、Gold 或专家结论。
- 后续 `run-qwen-v8-20260730T112152Z` 已对同一冻结 scene 完成 provider 驱动的 Director、3/3 结构互异 Strategist、3 个真实渲染 hard-pass 候选和换位 Critic：8/8 provider 调用成功、当前 graph 未改变。原始 `pipeline-result.json` 明确为 `reflection_stage: skipped-shadow-v1`，因此 v3 执行审计准确归类为 `no_reflection`，不能冒充 `full_pipeline`。内容寻址种子见 `output/evidence/creative-ablation-dji-qwen-v8-v1/`；含原始 run request/result 的 13 项绑定审计通过，但三方向平均像素距离仅 `0.0052276220`，低于正式完整链路门槛 `0.15`，且 `formal_review_freeze=false` / `formal_release_eligible=false`。聚合矩阵 `output/evidence/creative-ablation-matrix-preflight-audit-v1.json` 复核该 seed 完整性后，准确报告仍缺 7 个变体和 9 个 test item。原 provider 报告见 `output/evidence/creative-provider-ollama-v1/provider-pipeline-report-qwen-v8.json`（SHA-256 `8b07e196…2983`）；它不替代 owner/rights、accepted Gold、3+ 专家或正式校准。
- RAG 生产摄取新增独立内容复核、独立权利复核和结构化授权门禁。已冻结 ACES Documentation `773f9779…` 与 OpenColorIO v2.5.2 `c52966a…` 的两份官方文本、许可记录和 6 张三路 possibility cards；当前故意保留 `authorized: false`，审计只报告两项待签核来源且不建索引，见 `output/evidence/creative-corpus-intake-v1/`。
- `colorgraph.creative-agent-readiness/v1` 统一汇总 5 个 Agent 任务的 provider、corpus、production expert、Critic calibration 与默认离线门禁，且不会修改 rollout。当前 `CG-AGENT-012=true`，其余四项为 `false`；报告准确保留两项语料独立签核、冻结 production bundle/3+ 专家和正式 Critic gate 的外部阻断，见 `output/evidence/creative-agent-readiness-current-v1.json`。
- 创意约束固定为交付不可豁免、默认保护 allowlist 例外、创意空间独立信号三层；预声明例外绑定证据、graph/candidate、scope、预算和批准来源，同一 clipping 指标的局部 bloom/全局扩散/非法输出分流回归通过，见 `output/evidence/creative-constraint-policy-v1.json`。
- Playwright：输入色彩空间重分析与 v2 图回读通过；另完成真实 3-scene 离线 Agent 运行、scene/counterpoint 切换、第二名显式应用和全局撤销，最终恢复原图摘要并回到 Shadow。启动后取消的 stale-revision 竞态已修复为“控制前读取最新快照 + 精确 stale 有界重试”；真实浏览器运行在 22% 安全取消、持久恢复并完成 9/9 候选。2026-07-30 又在 1440×900 / 1024×768 验证真实 provider opt-in：默认关闭、双同意前按钮禁用、双同意后才可启动；全程未执行 provider run，console 0 errors / 0 warnings，截图见 `output/playwright/creative-agent-*.png`。
- 正式性能基准 `colorgraph.production-video-benchmark/v1` 仍保留完整 20 行
  real-media 生产矩阵协议。提交冻结前已完成 10/20 行、0 失败，其中包含
  no-mask、Farneback 与 VDA 的 1080p cold/warm 及 no-mask/Farneback 4K
  cold/warm；输出 SHA 均由逐行 checkpoint 保存。按最新 TODO，123.84 秒全片、
  其余 10 行和完整 4K 复核全部后置；后台进程已在下一条 VDA 4K 的 0% 起点停止，
  可恢复报告 SHA-256 为
  `f60e903591fbb348cde5050308e9af40851708025d9d41f45ada983e3a54db3c`，见
  `output/evidence/bench-001-production-matrix.json`。
- `CG-BENCH-001` 的提交门槛缩小为：在受支持 AMD Radeon/ROCm 上，对
  12–25 秒、1080p、可再分发素材只跑 `no_mask` 与 `current_combined`，至少
  一次 warm，并冻结 FPS、P95、峰值显存、codec、硬质检、设备/驱动/runtime
  和报告哈希。该门槛已于 2026-08-02 在 Radeon Cloud 的 `gfx1100`、96 CU、
  49136 MiB 实机上通过；本地 Ryzen iGPU/CUDA 前置审计仅保留为“为什么不能
  在开发机伪验证”的历史证据，见
  `output/evidence/bench-001-amd-demo-prerequisite-audit.json`。
- AMD 短基准素材已冻结为 Wikimedia Commons CC BY-SA 4.0 的
  `Snowdonia by drone` 12.5 秒衍生片：1920×1080、30 FPS、375 帧，两个
  清晰硬切形成 3 个镜头；全解码、PTS、许可、分辨率、时长和人工 contact
  sheet 复核均通过。clip SHA-256 `04ca4701…aca5e`，manifest SHA-256
  `4e291b30…a0a1`，见 `output/evidence/bench-001-amd-demo-source/manifest.json`。
- 同一短片项目的 5 个 OneFormer/Depth Anything V2 冻结蒙版已完成全帧解码
  复核；NVIDIA/CUDA 工程预检的 `no_mask` 与 `current_combined` warm 两行
  均完成、0 failed，组合行硬技术检查 100、总分 96，但感知风险仍标记
  `mask_jitter`。该报告明确保持 `partial` /
  `production_claim_allowed=false`，仅证明短片、图、蒙版、输出哈希和硬质检
  链路可执行，不能替代 AMD 门槛；就绪审计 SHA-256
  `1723bcd1…2028`，见 `output/evidence/bench-001-amd-demo-readiness.json`。
- AMD Demo 使用独立的 fail-closed runner/audit：正式命令在渲染前拒绝非
  ROCm、非 AMD、非官方支持 Radeon、缺 HIP 或缺实机驱动版本的环境，并强制
  两行 fresh render，禁止跨设备 checkpoint 复用。早期 NVIDIA 报告准确归类为
  `engineering_preflight_only`，没有被改写成 AMD 数字；最终实机 audit SHA-256
  为 `4cdf0b78…21502`。Windows AMF 与 Linux VAAPI 均为显式硬件 encoder
  policy；运行说明见 [AMD_DEMO_BENCHMARK.md](AMD_DEMO_BENCHMARK.md)。
- 新增 `amd-full-pipeline` 统一实机门禁：先绑定同设备三次 ROCm FP32 报告，
  再真实运行 CLIP、SegFormer-B0、Depth Anything V2 Small，并为每次模型
  inference 冻结 model/input/output tensor device、HIP 与峰值显存；三者还
  强制精确 revision 和实际 state-dict SHA-256，目标机缓存漂移会 fail-closed。
  成功环境固定 Python 3.12、PyTorch `2.9.1+gitff65f5b`、torchvision
  `0.24.1+d801a34`、HIP `7.2.53211-e1a6bc5663` 和其余直接依赖版本。模型按阶段
  释放后，固定的 Ollama `colorgraph-qwen3.5:9b`（digest
  `a2845456…3634`、`Q4_K_M`）必须同时通过 `/api/ps` 的至少 99% GPU
  offload、请求后 VRAM 释放和 fresh `server.log` 区间中的
  `library=ROCm`。随后两行 AMD Demo 强制逐 batch ROCm 证据和对应 OS 的 AMD
  硬件编码（Windows AMF / Linux VAAPI），另导出 HEVC Main10 完整成片并运行
  硬质检。Radeon Cloud 实跑中 `no_mask/current_combined` warm 分别为
  `19.3799/15.1638 FPS`，P95 为 `43.9026/77.2078 ms`；最终 12.5 秒 Main10
  成片为 `13.0158 FPS`。QA 实际解码 940 个蒙版采样帧，取得 915 个转场、
  300 个时序、12 个天空蒙版、8 个天空边界和 8 个天空色带观察。统一报告 8/8
  检查通过，SHA-256 `c7a7e15c…35c195`，见
  `output/evidence/amd-full-rocm-linux-radeon-cloud-20260802-v6/`。
  v3 可传输执行包含 184 个 payload 文件，独立 ZIP 流式校验 0 missing /
  0 mismatched；包 SHA-256 `d1a86198…ef271`，manifest SHA-256
  `d53f3a5a…8d4a8`。
- 研究观察项已改为 `colorgraph.research-watch-gate/v1` 机器门禁：官方来源新鲜度、代码/权重独立许可、不可变 revision/SHA-256、可复现报告、16 GB 峰值、Windows/ROCm 和 Gold Set 缺一即保持 `watch`；提前填写正式 CG 编号会让审计失败。当前 7 个候选全部留在观察态，0 个可转正，见 `docs/research-watchlist-v1.json` 与 `output/evidence/watch-001-research-gate-audit.json`。
- 镜头模型新增 `colorgraph.shot-model-shadow-evaluation/v1`：当前 detector、
  PySceneDetect Adaptive、TransNetV2、AutoShot 四行固定对测，分别报告 hard
  cut/fade/dissolve/flash/short-shot、速度和峰值内存，并强制代码/权重许可与
  不可变哈希。两套官方模型 checkpoint 已安装、严格加载并完成真实推理；320 帧
  无损工程转场矩阵中 TransNetV2 是唯一通过工程候选门的行（F1 `1.0`，
  `506.29 FPS`），AutoShot F1 `0.769`、`41.75 FPS`。矩阵不是人工 Gold，
  默认仍不切换，见 `output/evidence/shot-010-transition-matrix-report.json`。
- SigLIP2 新增 `colorgraph.siglip2-scene-shadow/v1` 工程影子路径：图像与全部
  文本分别单批编码并内容寻址缓存，使用独立 sigmoid 多标签语义而非 CLIP 候选
  集合 softmax，保存 raw cosine/logit，并以 calibration-only 产物冻结温度、
  逐标签与 OOD 阈值。exact checkpoint 已安装并在许可/哈希冻结的 Sony
  DSC-RX10 III 真实帧上完成 shadow：`0.170 FPS`、峰值 GPU
  `1807.23 MiB`，模型状态、输入、输出与缓存身份均已冻结。仍缺人工 Gold 和
  同矩阵 CLIP 质量对照，见
  `output/evidence/vlm-010-siglip2-local-runtime-observation.json`。
- 语义模型新增 `colorgraph.semantic-model-shadow-evaluation/v1`：固定当前
  SegFormer-B0、SegFormer-B5、OneFormer 三行，以 water/vegetation/mountain
  逐类指标决定候选。三者 exact checkpoint 均已安装并完成真实 Sony 帧推理；
  cold throughput/峰值 GPU 分别为 `0.2298/213.94`、
  `0.2291/1001.64`、`0.1233 FPS/1288.68 MiB`。OneFormer 的 MIT
  来源、安装与 runtime 门全部 ready；B0/B5 的 NVIDIA 上游非商业条款原样
  保留。没有人工 Gold 时不做质量默认选择，见
  `output/evidence/sem-010-*-local-runtime-observation.json`。
- 正式生产资产生成器 `tracked-mask-assets` 已在同一 123.84 秒、7423 帧 DJI
  原片上完成：OneFormer exact revision/state 生成 sky/vegetation/water/mountain
  四个 16-bit FFV1，frame Depth Anything V2 Small exact revision/state 生成
  `depth_far`；共 37,115 帧全部解码复核并在成功后清理临时 PNG。五个视频、
  源片、模型身份和 Grade Graph 摘要见
  `output/evidence/bench-001-formal-tracked-mask-assets.json`。
- 视频对象蒙版新增 `colorgraph.video-object-mask-shadow-evaluation/v1`：
  Farneback、SAM 2.1/3.1、Cutie、SEA-RAFT 同一冻结矩阵覆盖遮挡/显露、
  长漂移、anchor 跳变和消失重现。SAM 2.1、Cutie、SEA-RAFT 已在同一相机源
  派生的真实 30 帧 clip 上完成 CUDA 运行，分别记录 `5.848` propagation
  FPS、`19.438` propagation FPS 和 `15.415` pair FPS，逐帧 masks/
  flow/uncertainty/occlusion 及 checkpoint/state 哈希齐全。五类人工 Gold
  仍缺，工程矩阵继续 `shadow_only`。
- SAM 3.1 官方代码 revision `6dbb02bd…84f6` 和固定 SAM License 已安装/
  审阅，项目许可接受已获用户授权。官方 checkpoint revision
  `daa63191…4460` 已冻结，但本机无 HF token，gated access 返回 401；
  3.5 GB checkpoint 未开始传输，见
  `output/evidence/vos-011-sam31-access-audit.json`。
- `colorgraph.vos-platform-prerequisite-audit/v1` 将主机先决条件与模型运行兼容
  分离：Windows CUDA 上 SAM 2.1/Cutie/SEA-RAFT 的真实推理已经完成；WSL2
  虽可见 RTX 5060 Ti 与 Python 3.10，仍缺 pip/torch，native Linux/ROCm 与
  SAM 3.1 Linux 路径尚未完成。
- 正式模型来源 `colorgraph.formal-model-source-registry/v1` 现同时绑定用户
  项目授权、不可变官方 revision、上游许可、安装内容 SHA 与真实 runtime report。
  VDA-S、frame Depth Anything V2 Small、SAM 2.1、SEA-RAFT、OneFormer 共
  5 个候选为 runtime-ready；其中两个深度候选仍缺人工 Gold 对照，不接管默认
  深度。SAM 3.1 来源/许可通过但 gated 权重与 runtime 缺失；Cutie 权重公共
  分发许可仍不明确；SegFormer-B0/B5 已实跑但上游非商业限制不变。见
  `docs/formal-model-source-registry-v1.json` 与
  `output/evidence/formal-model-source-audit.json`。
- SegFormer、Depth Anything 和本地 VLM 的加载缓存现在绑定显式模型 revision，并对实际加载的 PyTorch `state_dict` 生成规范 SHA-256；该身份会进入 prediction、mask 资产和 VLM 校准门禁。同名权重被替换时缓存/校准 fail-closed，旧 mask 未记录的 revision/hash 不追溯补写，因而仍在生产矩阵中显式阻断 provenance gate。

最近一次本地验证使用：

- Web UI：`http://127.0.0.1:4173`
- FastAPI：`http://127.0.0.1:8010`
- OpenAPI：`http://127.0.0.1:8010/docs`

端口状态是临时运行状态；新会话仍应先执行健康检查，不要假设服务一直在线。

### 3.3 已记录的回归性能

回归素材为 640×360、25 FPS、6 秒、150 帧、3 个硬切镜头的合成风景视频：

| 链路 | 已记录结果 |
| --- | ---: |
| CUDA 无蒙版渲染 | 约 140.8 FPS |
| CUDA + FFV1 时序蒙版 | 冷启动约 60.8 FPS，预热约 69.2 FPS |
| CPU 无蒙版渲染 | 约 87.8 FPS |
| 质量闭环 | 初始 46 分，定向修复后 94 分通过 |

这些数字只用于当前工程基线，不代表 AMD、1080p、4K 或真实长视频性能。

## 4. 已完成的主要能力

### 4.1 媒体与时间结构

- FastAPI 视频上传和隔离项目目录；
- FFprobe 基础媒体信息与完整输入色彩元数据：range、primaries、transfer、matrix、bit depth、chroma、HDR mastering/CLL；
- 色彩元数据来源、置信度、缺失值、stream/container 冲突和用户 profile override 证据持久化；
- 自动镜头检测；每 shot 自适应 3/5/7 个避转场候选、质量过滤、cosine medoid UI/标签帧和鲁棒均值 scene embedding；
- 内容感知曝光/WB：排除天空、雪地、霓虹和单一主色，联合估计有效样本比例与不确定性；无可信样本时保守收缩；
- shot 级不确定性加权 Huber + L1 robust trend filter、持续变化点与自适应 Exposure / Temperature 关键帧；实现已通过确定性场景回归，仍待专家 Gold Set 完成验收；
- 显式 sRGB、BT.709 OETF、Rec.1886、Linear Rec.709、ACES2065-1、ACEScg 和 ACEScct；
- Sony S-Log3 / S-Gamut3.Cine 与 DJI D-Log / D-Gamut 通过固定 OCIO 2.5.2 ACES 2 Studio Config 的官方 camera input transform 进入 ACES2065-1；
- 可选参考图上传、CLIP Look 排名和镜头相似度；
- Scene grouping v2 shadow：融合鲁棒 shot embedding、色彩、语义和可选音频的连续边界分数、版本化 calibration 与全局动态规划；冻结 test 前实际 groups 保持旧贪心基线；
- 最近项目自动恢复。

### 4.2 Typed Grade Graph 与渲染

- Pydantic 严格 Grade Graph；
- 配对的 schema/renderer v1、v2 与 v3 版本；v1/v2 保持旧项目外观，v3 使用 ACEScg scene-linear、ACEScct creative 和 ACES 2 Output Transform，并拒绝版本错配；
- v3 白平衡使用 CCT+Duv/xy 与 CAT16/Bradford；ASC CDL 对齐 OCIO no-clamp 负值语义；contrast/saturation/highlight/tone 以 ACEScct 编码和 AP1 灰轴求值；
- v2 实际执行并校验 project-level Input/Output Transform，工作空间为 scene-linear Rec.709；
- CFR 流式与 VFR ffconcat 双路径；实际逐帧 PTS 驱动关键帧求值，输出帧数/PTS 误差设 0.5 ms 硬门禁；
- 16-bit RGB handoff、FP32 正式调色、10-bit master，以及独立 8-bit preview 精度预算；
- Project / Scene / Shot / Sub-shot 时间作用域；
- 节点顺序、开关、参数与轨道；
- Exposure、Temperature/Tint、标准 ASC CDL 参数；
- ACEScct encoding-aware Contrast、Saturation、Highlights 和 tone curve；
- `.cube` 1D shaper/3D/组合读取，v3 tetrahedral 与旧项目 trilinear compatibility，CLF/CTF OCIO processor，以及按摘要/device/dtype 失效的设备缓存；33³ LUT 按 scene/look 独立导出，project Post Look 明确逐 LUT 烘焙；
- hold / linear / 非均匀时间 PCHIP 关键帧；PCHIP 预计算分段系数、二分查找且单调不超调，旧 `cubic_spline` 保留 Catmull–Rom compatibility mode；
- PyTorch GPU 批量视频渲染；
- FFmpeg 编码和音频保留；
- CUDA 使用 NVENC，ROCm Windows 使用 AMF，ROCm Linux 使用 Radeon VAAPI；
  正式 AMD 门禁要求硬件 encoder 预检通过，不允许静默回退 x264。

### 4.3 本地模型与蒙版

- `openai/clip-vit-base-patch32`：场景、风险、Look、参考图和候选意图；
- `nvidia/segformer-b0-finetuned-ade-512-512`：语义分割；
- `depth-anything/Depth-Anything-V2-Small-hf`：默认深度 fallback；采用 shot 固定尺度、anchor scale/shift 对齐与时序残差不确定性，不再逐帧 2/98 或写死置信度；
- 官方 Video Depth Anything Small：Apache-only、commit/checkpoint 哈希门禁的
  可选 shadow；本机已完成真实 150 帧 CUDA 运行，但无人工 Gold 时不接管默认
  mask；
- 天空、植被、水面、山体默认语义目标；`earth/land`、`rock`、`cliff`、`sand` 与 mountain/vegetation 分离并可单独请求；
- 语义映射使用版本化 JSON 和 SHA-256；重复 alias 或跨 target 复合标签直接拒绝，checkpoint 缺少的 cliff/snow class 显式标记 `model_class_missing`；
- 近/中/远景深度目标；
- 稀疏模型锚点 + Farneback current→previous backward warp + 周期模型重锚定；元数据明确未做双向一致性；
- 每帧 PNG 和 FFV1 无损蒙版视频；frame count、尺寸、FPS、alias、双 SHA-256 和完整解码为强制门禁；
- 缺帧默认报错；只有显式 `hold_last` 才可复用前帧，不再静默生成零 mask；
- fuzzy `AND / OR / NOT` 组合 Mask Graph，例如：

```text
sky AND NOT mountain
(sky OR water) AND NOT vegetation
```

### 4.4 Agent、候选与增量预览

- 轻量 Landscape Grade Grammar；
- 中英文自然语言到节点、参数、时间段和空间目标；
- “前半段/后半段/当前镜头/指定 scene/整段”等时间定位；
- project 命令逐 shot 展开并同步关键帧，部分范围使用独立 overlay；
- “不要改变山体”等保护目标编译为组合蒙版；
- 缺失蒙版自动触发本地生成任务；
- 每项 edit 的 `affected_range` 与精确 `invalidated_ranges`；
- 自然语言命令保存精确前态，Web 工作台支持 `Ctrl/Cmd+Z` 撤销；
- 只包含当前时间生效节点的内容寻址预览缓存；
- Natural、Cool、Warm、Foggy 四种版本化共享配方与真实候选渲染；
- Scene Look 实例持久化为 `base_recipe_id + user_overrides + dirty`，支持脏状态确认、重复点击保留覆盖、显式恢复和图事务 undo/redo；
- 候选携带配方版本与 Graph 摘要；图或帧时间变化后自动过期，重新比较才可应用；
- 硬质检优先 + 意图语法 + 本地 CLIP 的成对 A/B；
- 图状态上的多轮增量修改；
- 每 scene 固定 `faithful/amplified/counterpoint` 三个闭卷方向，经 typed
  ColorStrategy、确定性 compiler、正式 renderer 与硬 QC 生成真实 Shadow 候选；
- Agent 工作台显示可审计阶段、真实预算/进度、支持与反对证据、保护项、QC、
  首选/第二名和应用 scope；可取消/恢复、无重算切换、显式确认应用和全局撤销，
  未配置模型阶段显式跳过。

### 4.5 质量、UI 与导出

- 高光、阴影、过饱和、运动补偿闪烁、结构损失；
- 运动补偿蒙版抖动、蒙版光晕和天空色带；
- 时序证据包含逐采样帧分类、曝光 stop、camera/non-rigid motion、flow 有效率、连通区域框及每个 mask 的原始/补偿后边界误差；
- 节点消融归因、显式预算的多轮局部 Verifier 修复，逐候选重新质检并按硬门禁、
  非目标副作用与意图漂移决定接受或回滚；
- 严格 Gold Set manifest、授权/拆分/哈希校验、真实来源摄取、人工 provenance/P0 配额审计和程序化冻结 bootstrap；
- 镜头、scene、mask、depth、ΔE2000/ΔEITP、排序与工程统一指标；
- 版本化统一报告记录配置、硬件和逐素材哈希；专家盲测随机化、Wilson 95% 区间和 Fleiss κ；
- React 调色工作台；
- 默认调色 Demo 由 Grade Graph 的 `metadata.demo.role = primary_grading_demo` 选择；当前为约 123.84 秒的 DJI M3 Pro Cine 4K 59.94 FPS ProRes 422 HQ 10-bit D-Log 项目。正在运行的任务和上次打开的真实用户项目优先恢复，合成/API 测试项目不会覆盖默认 Demo；
- 原片作为媒体主时钟，调色结果按 4 秒内容寻址分片双槽预载并同步播放；连续缓冲达到 2 秒即可开播，串行维持约 12 秒前向缓存，seek 会优先生成当前位置并废弃过期预取；暂停和 seek 后按 220 ms 防抖恢复后端精确单帧，播放期间不发送精确预览请求；
- 播放档位覆盖 540p/1080p/1440p/2160p H.264 与 HEVC Main10；MediaCapabilities、实际播放回退、禁止放大、自动档位解释和逐档体积/码率/首帧/丢帧/CPU/GPU/同步遥测均已落地；
- 标尺、Scene、镜头和参数轨道支持任意位置 seek；播放指针具备鼠标、触控、逐帧键盘和首尾导航；
- Exposure 关键帧默认锁定，显式解锁并先选择后才能拖动；支持 5 px 阈值、临时草稿、pointer-up 原子保存、Esc 取消、精确输入和局部 undo/redo；
- 原片/结果比较、真实镜头和真实蒙版预览；
- 节点参数修改和持久化；
- 后台 Job、轮询和 SSE；
- CLI：`doctor / analyze / render / gold-validate / gold-source-status / gold-source-inspect / gold-annotation-pack / gold-audit / evaluate / precision-gate / production-benchmark / sam2-mask-asset / tracked-mask-assets / research-watch-audit / formal-model-source-audit / shot-shadow-observe / shot-shadow-eval / vlm-shadow-calibrate / vlm-shadow-observe / semantic-shadow-observe / semantic-shadow-eval / vos-shadow-eval / vos-platform-audit / creative-provider-shadow / creative-corpus-audit / creative-review-freeze / creative-review-assemble / creative-agent-eval / creative-critic-calibrate / creative-agent-readiness`；
- ZIP 中包含成片、逐场景 LUT、Grade Graph、质量报告和蒙版资产。

## 5. 语义蒙版的真实现状

当前项目 **没有人工标注真值集，因此没有可公布的 pixel accuracy、mIoU、Dice 或 Boundary F-score**。

现有 6 秒回归片的平均模型置信度为：

| 目标 | 平均置信度 |
| --- | ---: |
| 天空 | 0.981 |
| 山体 | 0.853 |
| 植被 | 0.829 |
| 水面 | 0.782 |

这些值是阈值 `≥ 0.30` 的预测像素平均概率，不是分割准确率。不能写成“天空准确率 98.1%”。

当前 `ade20k-landscape-v2` 映射已在真实 SegFormer-B0 revision `489d5cd8…` 上审计：`earth` 只属于 land，`tree` 只属于 vegetation，mountain/hill、rock 和 sand 分别报告；class IDs/labels、模型 revision、概率阈值、映射版本及哈希随 mask 资产持久化。完整逐类表见 `output/evidence/semantic-mapping-audit.json`。

同一回归片的时序/渲染相关结果：

- `mask_jitter = 0.000287`：通过；
- `mask_halo = 0.185813`：warning，接近 `0.20` 阈值；
- `sky_banding = 0`：通过。

工程判断：

- 天空目前最稳定；
- 山体、植被可作为自动初稿；
- 水面相对最弱，倒影、雾气和天空颜色容易混淆；
- 640 边长推理对树梢、地平线和远山细边界有限；
- 1.5 秒锚点间的光流传播在快速运动、遮挡或复杂视差中可能漂移。

若下一阶段关注分割质量，优先建立 Landscape Gold Set 的人工标注子集，并报告逐类 IoU、Dice、Boundary F-score 与时序一致性，而不是继续引用置信度。

## 6. 关键目录与文件

```text
README.md                         # 启动与项目总览
docs/
  PROJECT_STATUS.md               # 本文件，新对话先读
  PROJECT_SPEC.md                 # 完整产品愿景和原始规格
  IMPLEMENTATION_AUDIT.md         # 完成/部分/未完成逐项审查
  ALGORITHM_RESEARCH.md            # 关键算法、质量风险与替代方案
  EVALUATION_PROTOCOL.md           # Gold Set、统一指标与专家盲测协议
  TODO.md                          # 轻量任务入口与当前路由
  todo/                            # 活跃任务正文与历史验收归档
  ROCM_BACKEND.md                 # AMD/ROCm 迁移与验收清单

backend/colorgraph/
  agent/
    planner.py                    # 自然语言 Landscape Grade Grammar
    scene_grouping.py             # 连续 Scene 归组
    scene_understanding.py        # 本地 CLIP 分析
  api/
    app.py
    routes/projects.py            # 上传、项目列表、Graph、原片/代表帧
    routes/operations.py          # 蒙版、命令、预览、候选、渲染、导出
  devices/                        # CUDA / ROCm / CPU 抽象
  domain/grade_graph.py           # 核心 schema
  grading/
    engine.py                     # 确定性 PyTorch 调色
    video.py                      # 视频批处理和编码
    masks.py                      # 蒙版加载与组合表达式
  evaluation/                     # manifest、统一指标/报告与盲测聚合
    keyframes.py
    looks.py
    lut.py
  media/                          # FFprobe、镜头、帧、色彩分析
  quality/                        # 质量指标与修复
  services/
    candidates.py                 # 本地候选 A/B
    graph_builder.py
    preview_cache.py              # 时间范围感知缓存
  vision/
    semantic.py                   # SegFormer 与类别映射
    depth.py                      # Depth Anything
    video_masks.py                # 时序传播与资产输出

src/
  App.tsx                         # 前后端编排和 UI 状态
  api.ts                          # API 类型与请求
  components/                     # 工作台、预览、时间线、检查器等
```

本地运行数据：

- `backend/data/`：项目、测试视频、预览和导出；
- `backend/models/`：Hugging Face 模型缓存；
- `output/playwright/`：浏览器验收截图；
- `dist/`：前端生产构建。

上述大文件目录多数已由 `.gitignore` 排除。不要在代码或文档中依赖某个历史 `project_id`；它们是本机运行产物。

## 7. 启动与操作

后端：

```powershell
.\scripts\start-backend.ps1
```

前端：

```powershell
.\scripts\start-frontend.ps1
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8010/api/health
Invoke-RestMethod http://127.0.0.1:8010/api/system/device
```

CLI：

```powershell
uv run --project backend colorgraph doctor
uv run --project backend colorgraph analyze .\input.mp4 --with-masks
uv run --project backend colorgraph render <project_id>
uv run --project backend colorgraph creative-agent-eval `
  --input .\creative-agent-expert-bundle.json `
  --output .\creative-agent-evaluation.json
```

Web UI 推荐流程：

1. 可选选择参考图；
2. 选择 Rec.709、Sony S-Log3，或 DJI Mavic 3 D-Log / D-Gamut；
3. 导入风景视频并等待媒体分析；
4. 点击“AI 分析”生成真实时序蒙版；
5. 本地 A/B 比较 Look；
6. 调整节点或关键帧；
7. 输入局部自然语言指令；
8. 导出，触发渲染、质检、必要时修复和 ZIP 下载。

## 8. 主要 API

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/health` | 健康状态 |
| GET | `/api/system/device` | 真实设备与运行时 |
| GET | `/api/system/look-recipes` | 版本化 Look 配方目录 |
| GET/POST | `/api/projects` | 项目列表 / 上传项目 |
| GET/PUT | `/api/projects/{id}/grade-graph` | 读取 / 保存调色图 |
| GET | `/api/projects/{id}/color-pipeline/migration-preview` | 只读生成 v2→ACES v3 迁移候选与风险 |
| POST | `/api/projects/{id}/color-pipeline/migrate` | 确认后备份旧图并保存 ACES v3 |
| POST | `/api/projects/{id}/masks` | 语义/深度时序蒙版 |
| POST | `/api/projects/{id}/commands` | 自然语言增量编译 |
| POST | `/api/projects/{id}/preview` | 范围感知 GPU 单帧预览 |
| POST | `/api/projects/{id}/preview-video` | 按 Grade Graph 缓存真实调色播放视频 |
| POST | `/api/projects/{id}/preview-video-segment` | 优先生成当前 4 秒真实调色分片，并按同一 Graph 缓存组预取 |
| POST | `/api/projects/{id}/preview-playback-metrics` | 持久化逐档浏览器播放与本机占用遥测 |
| POST | `/api/projects/{id}/candidates` | 本地 Look A/B |
| POST | `/api/projects/{id}/looks/apply` | 校验摘要后应用或确认切换 Look 实例 |
| POST | `/api/projects/{id}/looks/restore` | 恢复当前 Scene Look 的版本化基准 |
| GET/POST | `/api/projects/{id}/creative-agent` / `creative-agent/runs` | 读取快照 / 启动离线 Shadow run |
| POST | `/api/projects/{id}/creative-agent/control` | 取消或恢复 Agent run |
| POST | `/api/projects/{id}/creative-agent/apply` | 摘要校验与显式确认后应用候选 |
| POST | `/api/projects/{id}/render` | 视频渲染、质检和修复 |
| GET | `/api/projects/{id}/quality` | 质量报告 |
| POST | `/api/projects/{id}/export` | ZIP 交付包 |
| GET | `/api/jobs/{job_id}` | 后台任务状态 |

## 9. 已知缺口

当前 MVP 之外尚未完成：

1. 将当前 6 个真实授权候选扩充到配额，完成独立签核的人工 shot/scene/mask/depth/偏好真值；私有 DJI Log 来源在许可文本完成独立权利复核前不得公开再分发；
2. SAM 2 类文字/点/框提示式分割；
3. 几何蒙版、HSL qualifier 和画笔修正；
4. 最终视频的分段缓存与增量拼接；
5. 完整项目选择器和跨自然语言命令的统一 undo/redo 历史栈（关键帧、Look、节点参数与开关的图事务 undo/redo 已完成）；
6. 独立 CDL 文件导出；
7. OCIO GPU processor 缓存、gamut volume 与 LUT 连续性专项指标；
8. 20–45 秒策略提示与完整 1080p/4K 自动生产基准；
9. 获许可检索语料、冻结生产创意 test 和至少 3 名合格独立专家评审；
10. 可选生成式本地 VLM 和长期用户偏好；
11. 桌面应用或 DaVinci/Premiere 插件；
12. Radeon Cloud 实机设备/GUI 播放录屏与其余比赛提交材料。

## 10. 建议的下一步顺序

如果没有新的用户优先级，建议：

1. 冻结 `CG-CREATIVE-010` 的三方向肉眼可见差异与人工选择，避免把三套近似
   参数冒充不同创意方向；
2. 以已通过的统一报告和 Main10 成片录制 Radeon Cloud 设备状态、真实播放与
   操作链；代码、输入和目标环境未变化时不重复消耗云时长；
3. 建立可公开、可复现的英文仓库/README，并完成 Project Profile、Demo 视频、
   PPT/Poster；完整 20 行长片矩阵继续后置；
4. 人工 Gold、正式专家签核、候选模型替换和 shadow benchmark 均按最新 TODO
   保持 `FROZEN` / `DEFERRED`，不在本轮继续；

## 11. 不应破坏的工程原则

- 核心功能不能依赖闭源在线 API；
- 至少一个关键推理过程最终必须在 Radeon GPU 本地运行；
- Agent 做语义决策，确定性工具做像素计算、编码和质检；
- 不使用生成模型逐帧重绘来冒充稳定调色；
- 不把模型置信度写成准确率；
- 不把 CUDA 结果写成 AMD/ROCm 实测；
- 前端不得显示伪造设备、FPS、蒙版、分辨率或质量数据；
- 优先使用标准 PyTorch / Transformers 算子，避免 CUDA 专属扩展；
- 保持 Grade Graph、设备、模型和编码层的边界；
- 已有项目数据可能属于用户，修改或清理前先确认范围。

## 12. 新对话可直接使用的提示

```text
请先完整阅读 C:\pb\programs\color\docs\PROJECT_STATUS.md，
再按其中的当前状态、边界和验证命令接手 ColorGraph。
不要重新实现已经完成的链路；AMD/ROCm 只可引用 2026-08-02 Radeon Cloud
统一 `passed` 报告及其 SHA-256，不要从本地 CUDA 数字外推。
本次任务是：<在这里填写新任务>。
```

## 13. 更新本文的规则

完成重要里程碑后同步更新：

- 顶部“最后核对”日期；
- 最新测试数量与命令；
- 完成能力和已知缺口；
- 实测硬件与性能；
- 语义蒙版评测口径；
- 下一步优先级。

算法实现或默认模型发生变化时，还要同步更新：

- [ALGORITHM_RESEARCH.md](ALGORITHM_RESEARCH.md) 中的当前实现与证据；
- [TODO.md](TODO.md) 入口及 `todo/` 中的状态、验收结果和后续拆分。

如果本文与代码冲突，以重新运行测试、API 响应和实际代码为准，再修正文档。
