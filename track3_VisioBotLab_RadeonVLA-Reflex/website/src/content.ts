export type Locale = "en" | "zh";

type LocalizedText = Record<Locale, string>;

export interface Metric {
  value: string;
  label: LocalizedText;
  detail: LocalizedText;
  status?: "verified" | "pending";
}

export interface Demo {
  index: string;
  state: string;
  title: LocalizedText;
  body: LocalizedText;
  event: LocalizedText;
}

export interface CollectionClip {
  index: string;
  episode: string;
  duration: string;
  frames: LocalizedText;
  video: string;
  poster: string;
  title: LocalizedText;
  instruction: LocalizedText;
  state: LocalizedText;
  camera: LocalizedText;
}

export interface Feature {
  eyebrow: string;
  title: LocalizedText;
  body: LocalizedText;
}

export interface TaskRow {
  fruit: LocalizedText;
  targets: Array<{ label: LocalizedText; color: "white" | "blue" }>;
}

export interface TeamMember {
  name: LocalizedText;
  role: LocalizedText;
  share: string;
  focus: LocalizedText;
  lead?: boolean;
}

export const projectLinks = {
  source:
    "https://github.com/zzw-rgb/Radeon-hackathon-2026-07/tree/submission/track3-visiobotlab-radeonvla-reflex/track3_VisioBotLab_RadeonVLA-Reflex",
  pages: "https://zzw-rgb.github.io/Radeon-hackathon-2026-07/",
  bilibili: "https://www.bilibili.com/video/BV1B4M26SEZg/",
  submission: "https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/pull/110",
  contest: "https://modelscope.cn/events/299/比赛介绍",
  baseModel: "https://huggingface.co/lerobot/smolvla_base",
  technicalReport:
    "https://github.com/zzw-rgb/Radeon-hackathon-2026-07/blob/submission/track3-visiobotlab-radeonvla-reflex/track3_VisioBotLab_RadeonVLA-Reflex/reports/RadeonVLA-Reflex-Technical-Report.md",
  dataset: "https://huggingface.co/datasets/a3124371940/radeonvla_reflex_physical_2k",
  dataset1k: "https://huggingface.co/datasets/a3124371940/radeonvla_reflex_physical_1k",
  model20k: "https://huggingface.co/a3124371940/radeonvla_reflex_smolvla_1k",
  model50k: "https://huggingface.co/a3124371940/radeonvla_reflex_smolvla_1k_50k",
  finalModel: "https://huggingface.co/a3124371940/radeonvla_reflex_smolvla_2k_200k",
  evaluationVideos: "https://huggingface.co/datasets/a3124371940/radeonvla_reflex_evaluation_videos",
  walkthrough: "./videos/radeonvla-reflex-3min.mp4",
  console: "./console.html",
};

export const navItems: Array<{ href: string; label: LocalizedText }> = [
  { href: "#overview", label: { en: "Overview", zh: "概览" } },
  { href: "#demo", label: { en: "Evidence", zh: "核心演示" } },
  { href: "#runtime", label: { en: "Architecture", zh: "系统架构" } },
  { href: "#benchmark", label: { en: "Benchmark", zh: "基准" } },
  { href: "./console.html", label: { en: "Console", zh: "控制台" } },
  { href: "#reproduce", label: { en: "Reproduce", zh: "复现" } },
  { href: "#team", label: { en: "Team", zh: "团队" } },
];

export const copy = {
  pageTitle: { en: "RadeonVLA-Reflex · VisioBot Lab", zh: "RadeonVLA-Reflex · VisioBot Lab 项目展示" },
  pageDescription: {
    en: "RadeonVLA-Reflex — an interruptible and recoverable VLA runtime for language-guided robotic sorting on AMD Radeon.",
    zh: "RadeonVLA-Reflex：运行在 AMD Radeon 上、面向语言引导机器人分拣的可中断、可恢复 VLA 执行层。",
  },
  skipLink: { en: "Skip to project overview", zh: "跳到项目概览" },
  primaryNav: { en: "Primary navigation", zh: "主导航" },
  homeLabel: { en: "RadeonVLA-Reflex home", zh: "RadeonVLA-Reflex 首页" },
  brandKicker: { en: "VISIOBOT LAB · TRACK 3", zh: "VISIOBOT LAB · 赛道 3" },
  languageLabel: { en: "Language", zh: "语言" },
  heroBadge: {
    en: "Physical AI Challenge · Simulation",
    zh: "Physical AI 挑战赛 · 仿真项目",
  },
  heroTitleA: { en: "Actions that can", zh: "让机器人动作" },
  heroTitleB: { en: "change their mind.", zh: "随指令及时改变。" },
  heroBody: {
    en: "RadeonVLA-Reflex wraps a vision-language-action policy with command invalidation, safe interruption, and bounded strict-physics recovery—so stale or failed action chunks do not stay in control.",
    zh: "RadeonVLA-Reflex 在视觉语言动作策略外加入指令失效、安全中断与有界严格物理恢复，避免过期或失败的动作块继续控制机械臂。",
  },
  sourceCta: { en: "Explore the source", zh: "查看项目源码" },
  demoCta: { en: "See the core demonstration", zh: "查看核心演示" },
  consoleCta: { en: "Launch evidence console", zh: "进入可视化控制台" },
  heroAlt: {
    en: "Collaborative robot holding an apple as a stale action path stops and a safe recovery path redirects toward the blue bowl",
    zh: "协作机械臂夹持苹果，失效动作路径停止，安全恢复路径转向蓝色碗",
  },
  placeholder: { en: "Original recovery concept art", zh: "原创恢复机制概念图" },
  proofLabel: { en: "Verified snapshot", zh: "已核验快照" },
  proofNote: {
    en: "This snapshot separates completed local artifacts from formal release targets. Policy metrics are published from held-out evaluation artifacts.",
    zh: "该快照区分已完成的本地产物与正式发布目标；策略指标以独立评测产物为准。",
  },
  overviewKicker: { en: "SYSTEM OVERVIEW", zh: "系统概览" },
  overviewTitle: {
    en: "A safety layer around action-chunk VLA control.",
    zh: "为动作块 VLA 控制加上可审计的安全层。",
  },
  overviewBody: {
    en: "Fruit sorting is the Track 3 proving ground. The product idea is an interruptible, recoverable execution stack on one AMD Radeon GPU: Genesis dual-bowl simulation, LeRobot 0.6 recording, SmolVLA fine-tuning, and a Reflex monitor that can drop stale chunks when the operator changes the command.",
    zh: "水果分拣是 Track 3 的验证场景。产品形态是一张 AMD Radeon 上的可中断、可恢复执行栈：Genesis 双碗仿真、LeRobot 0.6 采集、SmolVLA 微调，以及操作员改指令时能丢弃过期动作块的 Reflex 监视器。",
  },
  overviewPoints: [
    {
      title: { en: "Language-addressable dual bowls", zh: "语言可区分的双碗布局" },
      body: {
        en: "Five YCB fruits × four fixed bowls (white/blue × left/right) yield twenty L1 tasks, plus L2–L4 spatial, sequential, and rule suites.",
        zh: "五种 YCB 水果 × 四个固定碗（白/蓝 × 左/右）构成 20 个 L1 任务，并扩展 L2–L4 空间、序列与规则套件。",
      },
    },
    {
      title: { en: "Strict physical demonstrations", zh: "严格物理的专家演示" },
      body: {
        en: "Training data forbids kinematic grasp glue and placement teleports. Each episode carries a certificate with zero intervention counts.",
        zh: "训练数据禁止运动学粘附抓取与放置瞬移；每条 episode 附带干预计数为 0 的严格物理证书。",
      },
    },
    {
      title: { en: "Single-GPU ROCm path", zh: "单卡 ROCm 全链路" },
      body: {
        en: "Record, train, evaluate, and benchmark on one visible Radeon device with immutable JSON/CSV/Markdown evidence.",
        zh: "在单张可见 Radeon 上完成采集、训练、评测与压力测试，并输出不可变 JSON/CSV/Markdown 证据。",
      },
    },
  ],
  sectionDemoKicker: { en: "CORE DEMONSTRATION", zh: "核心演示" },
  sectionDemoTitle: {
    en: "Successful runs, from collection to policy.",
    zh: "从数据采集到模型执行，全程成功回放。",
  },
  sectionDemoBody: {
    en: "Every public clip below reaches the requested bowl and keeps recording after release so the settled result is visible. The 20K checkpoint is the primary qualitative showcase; later checkpoints remain available in the download center.",
    zh: "下方每段公开视频都完成目标放置，并在释放后继续录制，让水果稳定落碗的结果清楚可见。20K 权重作为主要定性展示，后续权重仍保留在下载中心。",
  },
  videoLabel: { en: "3+ MIN POLICY WALKTHROUGH", zh: "3 分钟以上策略解说视频" },
  videoPending: { en: "Narrated project walkthrough · 3+ min", zh: "项目解说成片 · 3 分钟以上" },
  videoBody: {
    en: "A smooth 200-second English walkthrough with bilingual captions, successful Physical-2K collection examples, and successful 20K policy rollouts for banana and lemon. Every shown placement includes a visible settled ending.",
    zh: "200 秒自然英文旁白配中英双语字幕，展示成功的 Physical-2K 数据采集过程，以及 20K 权重完成香蕉和柠檬任务的成功回放；所有放置都保留稳定结尾。",
  },
  // Supporting appendix for released representative evaluation replays.
  collectionKicker: { en: "SUCCESS VIDEO LIBRARY", zh: "成功视频库" },
  collectionTitle: {
    en: "Policy evaluation and data collection.",
    zh: "模型评测与数据采集。",
  },
  collectionBody: {
    en: "Two reproducible first-attempt successes from the public 20K checkpoint are shown beside four successful strict-physics collection episodes. Scene and episode seeds are preserved with the evidence. Banana appears in both evaluation and collection.",
    zh: "两段可复现公开视频来自公开 20K 权重的首次成功评测，场景与 episode seed 均随证据保留；另有四段严格物理数据采集成功轨迹，香蕉同时出现在评测与采集中。",
  },
  videoCollectionLabel: { en: "VERIFIED SUCCESS REPLAYS", zh: "已核验成功回放" },
  videoCollectionPending: { en: "Successful evaluation and collection clips", zh: "成功评测与数据采集片段" },
  videoCollectionBody: {
    en: "Every clip was checked through its final frame: the correct fruit is released into the requested bowl and remains there during the post-success dwell.",
    zh: "每段视频都已检查至最后一帧：正确水果释放进入指定碗，并在成功后的稳定观察时间内保持在碗中。",
  },
  clipState: { en: "SUCCESS", zh: "成功" },
  clipCamera: { en: "RGB · 20 FPS", zh: "RGB · 20 FPS" },
  clipPlayLabel: { en: "Play evaluation replay", zh: "播放评测回放" },
  clipFallback: {
    en: "H.264 playback is unavailable in this browser.",
    zh: "当前浏览器无法播放此 H.264 视频。",
  },
  collectionScopeTitle: { en: "Scope", zh: "范围" },
  collectionScopeBody: {
    en: "The gallery contains only verified successful videos. Complete machine-readable evaluation results, checkpoint revisions, and checksums remain available through the public links below.",
    zh: "视频库仅展示已核验成功片段；完整机器可读评测结果、权重版本和校验和仍可通过下方公开链接获取。",
  },
  collectionStats: [
    { value: "6", label: { en: "successful clips", zh: "成功片段" } },
    { value: "2", label: { en: "20K policy runs", zh: "20K 模型回放" } },
    { value: "4", label: { en: "collection runs", zh: "数据采集回放" } },
    { value: "2.0 s", label: { en: "settled ending", zh: "稳定结尾" } },
  ],
  plannedEvidence: { en: "Core policy moments", zh: "核心策略时刻" },
  runtimeKicker: { en: "SYSTEM ARCHITECTURE", zh: "系统架构" },
  runtimeTitle: { en: "The policy proposes. The runtime decides.", zh: "策略提出动作，运行层决定是否执行。" },
  runtimeBody: {
    en: "Action chunking improves throughput, but an old chunk can outlive the instruction that created it. Reflex is the deterministic boundary between learned control and Genesis.",
    zh: "动作分块可以提升吞吐，但旧动作块可能比生成它的指令活得更久。Reflex 是学习控制与 Genesis 之间的确定性边界。",
  },
  architectureDiagramAlt: {
    en: "Detailed English RadeonVLA-Reflex architecture showing world RGB, wrist RGB, robot and gripper state, SmolVLA policy, action module, execution safety monitor, Genesis simulation, telemetry, retry, and next-observation feedback",
    zh: "RadeonVLA-Reflex 中文详细架构图，包含世界 RGB、腕部 RGB、机器人与夹爪状态、SmolVLA 策略、动作块、执行安全监视器、Genesis 仿真、遥测、重试与下一帧观测反馈",
  },
  architectureDiagramCaption: {
    en: "Closed loop — perception → SmolVLA → Reflex safety monitor → Genesis dual-bowl sim → next observation.",
    zh: "闭环：感知 → SmolVLA → Reflex 安全监视器 → Genesis 双碗仿真 → 下一帧观测。",
  },
  architectureLabel: { en: "Compact execution path", zh: "精简执行路径" },
  architectureInput: { en: "Language + RGB + state", zh: "语言 + RGB + 状态" },
  architecturePolicy: { en: "SmolVLA policy", zh: "SmolVLA 策略" },
  architectureReflex: { en: "Reflex runtime", zh: "Reflex 运行层" },
  architectureSafety: { en: "invalidate · clamp · retry", zh: "失效 · 限幅 · 重试" },
  architectureSim: { en: "Genesis + Franka", zh: "Genesis + Franka" },
  benchmarkKicker: { en: "PRIMARY BENCHMARK", zh: "主要基准" },
  benchmarkTitle: { en: "Five fruits. Four destinations. Twenty tasks.", zh: "五种水果，四个盘位，二十项任务。" },
  benchmarkBody: {
    en: "L1 crosses every fruit with every language-addressable bowl. Physical-2K contains 100 strict-physics demonstrations per task—2,000 episodes and 468,889 dual-camera frames in total.",
    zh: "L1 将每种水果与每个语言可指定盘位交叉。Physical-2K 每项任务包含 100 条严格物理演示，共 2,000 个 episode、468,889 帧双相机数据。",
  },
  targetLabel: { en: "Destination", zh: "目标盘位" },
  objectLabel: { en: "Object", zh: "物体" },
  demosLabel: { en: "100 strict demos", zh: "100 条严格演示" },
  evidenceKicker: { en: "EVALUATION STATUS", zh: "评测状态" },
  evidenceTitle: { en: "Evidence organized by completion state.", zh: "按完成状态组织评测证据。" },
  evidenceBody: {
    en: "The 20K checkpoint is used for the public success reel. Physical-1K, Physical-2K, 20K, 50K, 200K, evaluation files, and videos all remain independently downloadable.",
    zh: "公开成功视频以 20K 权重为主；Physical-1K、Physical-2K、20K、50K、200K、评测文件与视频均提供独立下载入口。",
  },
  releaseTarget: { en: "Released training dataset", zh: "已发布训练数据集" },
  releaseTargetValue: { en: "2,000 demos · 20 × 100", zh: "2,000 条演示 · 20 × 100" },
  releaseTargetBody: {
    en: "Balanced strict-physics expert set with 2,000 episode certificates, zero kinematic interventions, complete task coverage, and a fixed Hugging Face revision.",
    zh: "均衡严格物理专家集，包含 2,000 份 episode 证书、零运动学干预、完整任务覆盖和固定 Hugging Face revision。",
  },
  datasetCta: { en: "Open Physical-2K dataset", zh: "查看 Physical-2K 数据集" },
  modelLabel: { en: "Base policy", zh: "基础策略" },
  modelValue: { en: "LeRobot / SmolVLA", zh: "LeRobot / SmolVLA" },
  modelBody: {
    en: "Fine-tuned for 9-D absolute joint-position control from two RGB streams and language.",
    zh: "使用双路 RGB 与语言输入，微调为 9 维绝对关节位置控制。",
  },
  baseModelCta: { en: "Open base model", zh: "查看基础模型" },
  trainedModelCta: { en: "Open primary 20K checkpoint", zh: "查看主要 20K 权重" },
  evaluationVideosLabel: { en: "Evaluation evidence", zh: "评测证据" },
  evaluationVideosValue: { en: "Videos + JSON + checksums", zh: "视频 + JSON + 校验和" },
  evaluationVideosBody: {
    en: "A separate public Hugging Face dataset keeps representative replays, the 100-rollout bundle, interrupt evidence, and content hashes together.",
    zh: "独立公开的 Hugging Face 数据集统一保存代表性回放、100 次评测包、中断证据与内容哈希。",
  },
  evaluationVideosCta: { en: "Open evaluation videos", zh: "查看评测视频仓库" },
  reproduceKicker: { en: "REPRODUCIBLE PIPELINE", zh: "可复现链路" },
  reproduceTitle: { en: "From command to checksum.", zh: "从指令到校验和，全链路可审阅。" },
  reproduceBody: {
    en: "The repository separates source, datasets, checkpoints, and small evidence artifacts. Evaluation emits JSON, CSV, Markdown summaries, videos, and a deterministic checkpoint hash.",
    zh: "仓库将源码、数据、权重和小型证据产物分离。评测会输出 JSON、CSV、Markdown 摘要、视频与确定性 checkpoint 哈希。",
  },
  pipelineSteps: [
    { en: "Validate AMD / ROCm environment", zh: "校验 AMD / ROCm 环境" },
    { en: "Record and validate demonstrations", zh: "采集并验证专家演示" },
    { en: "Fine-tune on one visible GPU", zh: "在单张可见 GPU 上微调" },
    { en: "Run held-out and stress evaluations", zh: "运行独立评测与压力测试" },
    { en: "Publish artifacts, hashes, and video", zh: "发布产物、哈希与视频" },
  ],
  commandLabel: { en: "Reproduce checks and public inputs", zh: "复现检查与公开输入" },
  limitationLabel: { en: "Scope", zh: "适用范围" },
  limitationBody: {
    en: "Scope is limited to Genesis simulation, the registered fruit-and-bowl tasks, two RGB inputs, and 9-D joint-position control. Real-robot transfer is outside the current evaluation.",
    zh: "当前范围限于 Genesis 仿真、已注册的水果与碗任务、双路 RGB 和 9 维关节位置控制；真实机械臂迁移不在本轮评测范围内。",
  },
  teamKicker: { en: "TEAM", zh: "团队" },
  teamTitle: { en: "VisioBot Lab", zh: "VisioBot Lab" },
  teamBody: {
    en: "Nanjing University of Science and Technology · Track 3 Physical AI Challenge",
    zh: "南京理工大学 · Track 3 Physical AI 挑战赛",
  },
  teamLeadLabel: { en: "Team captain", zh: "队长" },
  teamMemberLabel: { en: "Member", zh: "队员" },
  teamShareLabel: { en: "Effort share", zh: "工作量占比" },
  contestCta: { en: "Competition page", zh: "比赛页面" },
  footer: {
    en: "RadeonVLA-Reflex · Track 3 Physical AI Challenge",
    zh: "RadeonVLA-Reflex · Track 3 Physical AI 挑战赛",
  },
  attribution: {
    en: "Project-owned RadeonVLA-Reflex hero concept. Third-party software and simulation credits are listed in THIRD_PARTY_NOTICES.md.",
    zh: "RadeonVLA-Reflex 项目自有封面概念图；第三方软件与仿真署名详见 THIRD_PARTY_NOTICES.md。",
  },
} satisfies Record<string, unknown>;

export const verifiedMetrics: Metric[] = [
  {
    value: "2,000",
    label: { en: "strict-physics demos", zh: "严格物理演示" },
    detail: { en: "Physical-2K · 20 × 100", zh: "Physical-2K · 20 × 100" },
  },
  {
    value: "468,889",
    label: { en: "dual-camera frames", zh: "双相机数据帧" },
    detail: { en: "20 Hz · validator clean", zh: "20 Hz · 严格验证通过" },
  },
  {
    value: "20K",
    label: { en: "showcase checkpoint", zh: "主要展示权重" },
    detail: { en: "SmolVLA · Physical-1K", zh: "SmolVLA · Physical-1K" },
  },
  {
    value: "1× GPU",
    label: { en: "AMD Radeon path", zh: "AMD Radeon 路径" },
    detail: { en: "ROCm sim · train · eval", zh: "ROCm 仿真 · 训练 · 评测" },
  },
];

export const evaluationMetrics: Metric[] = [
  {
    value: "abcca9f",
    label: { en: "20K public revision", zh: "20K 公开 revision" },
    detail: { en: "immutable Hugging Face checkpoint", zh: "Hugging Face 不可变权重版本" },
  },
  {
    value: "2 / 2",
    label: { en: "published policy clips", zh: "公开模型成功片段" },
    detail: { en: "banana + lemon · first attempt", zh: "香蕉 + 柠檬 · 首次执行" },
  },
  {
    value: "4 / 4",
    label: { en: "published collection clips", zh: "公开采集成功片段" },
    detail: { en: "apple + banana + orange + plum", zh: "苹果 + 香蕉 + 橙子 + 李子" },
  },
  {
    value: "5.35 ms",
    label: { en: "P95 inference latency", zh: "P95 推理延迟" },
    detail: { en: "20K probe · P50 4.72 ms", zh: "20K 抽测 · P50 4.72 ms" },
  },
];

export const teamMembers: TeamMember[] = [
  {
    name: { en: "Zhenwei Zhou", zh: "周振威" },
    role: { en: "Team captain · lead engineer", zh: "队长 · 主程" },
    share: "70%",
    lead: true,
    focus: {
      en: "Overall technical lead: architecture, Genesis and Reflex implementation, collection orchestration, SmolVLA training/evaluation, AMD deployment, website, and release engineering.",
      zh: "总体技术主导：系统架构、Genesis 与 Reflex 实现、采集总控、SmolVLA 训练评测、AMD 部署、网站和发布工程。",
    },
  },
  {
    name: { en: "Ange Liu", zh: "留安格" },
    role: { en: "Member · language & frontend QA", zh: "队员 · 语言与前端质检" },
    share: "15%",
    focus: {
      en: "Task-language schema review, collected-instruction consistency checks, website i18n QA, and bilingual documentation.",
      zh: "任务语言模式校对、采集指令一致性检查、网站国际化质检和中英文技术文档。",
    },
  },
  {
    name: { en: "Haoran Wang", zh: "王浩然" },
    role: { en: "Member · data & reproducibility QA", zh: "队员 · 数据与复现质检" },
    share: "15%",
    focus: {
      en: "Dataset certificate spot-checks, metric aggregation, reproducibility-command verification, and artifact checksum packaging.",
      zh: "数据证书抽检、评测指标汇总、复现命令核验和产物校验和打包。",
    },
  },
];

export const collectionClips: CollectionClip[] = [
  {
    index: "01",
    episode: "53001",
    duration: "10.35 s",
    frames: { en: "fixed seed 53001 · 20K", zh: "固定 seed 53001 · 20K" },
    video: "videos/eval-20k-banana-white-left-world.mp4",
    poster: "videos/eval-20k-banana-white-left-world.webp",
    title: { en: "Banana → white bowl, left", zh: "香蕉 → 左侧白碗" },
    instruction: {
      en: "Pick the banana and place it in the white bowl on the left.",
      zh: "抓取香蕉并放入左侧白碗。",
    },
    state: { en: "20K POLICY · FIRST-TRY SUCCESS", zh: "20K 模型 · 首次执行成功" },
    camera: { en: "RGB REPLAY · 20 FPS", zh: "RGB 回放 · 20 FPS" },
  },
  {
    index: "02",
    episode: "54006",
    duration: "9.45 s",
    frames: { en: "scene 54000 · episode 54006 · 20K", zh: "场景 54000 · episode 54006 · 20K" },
    video: "videos/eval-20k-lemon-blue-right-world.mp4",
    poster: "videos/eval-20k-lemon-blue-right-world.webp",
    title: { en: "Lemon → blue bowl, right", zh: "柠檬 → 右侧蓝碗" },
    instruction: {
      en: "Pick the lemon and place it in the blue bowl on the right.",
      zh: "抓取柠檬并放入右侧蓝碗。",
    },
    state: { en: "20K POLICY · FIRST-TRY SUCCESS", zh: "20K 模型 · 首次执行成功" },
    camera: { en: "RGB REPLAY · 20 FPS", zh: "RGB 回放 · 20 FPS" },
  },
  {
    index: "03",
    episode: "000",
    duration: "10.45 s",
    frames: { en: "209 frames · collection", zh: "209 帧 · 数据采集" },
    video: "videos/dataset-apple-blue-left.mp4",
    poster: "videos/dataset-apple-blue-left.webp",
    title: { en: "Apple collection → blue bowl, left", zh: "苹果采集 → 左侧蓝碗" },
    instruction: {
      en: "A successful strict-physics expert trajectory recorded into LeRobot format.",
      zh: "成功的严格物理专家轨迹，并以 LeRobot 格式记录。",
    },
    state: { en: "DATA COLLECTION · SUCCESS", zh: "数据采集 · 成功" },
    camera: { en: "RGB REPLAY · 20 FPS", zh: "RGB 回放 · 20 FPS" },
  },
  {
    index: "04",
    episode: "047",
    duration: "12.55 s",
    frames: { en: "251 frames · collection", zh: "251 帧 · 数据采集" },
    video: "videos/dataset-banana-white-right.mp4",
    poster: "videos/dataset-banana-white-right.webp",
    title: { en: "Banana collection → white bowl, right", zh: "香蕉采集 → 右侧白碗" },
    instruction: {
      en: "The full grasp, transport, release, and settled placement remain visible.",
      zh: "完整展示抓取、搬运、释放和稳定落碗过程。",
    },
    state: { en: "DATA COLLECTION · SUCCESS", zh: "数据采集 · 成功" },
    camera: { en: "RGB REPLAY · 20 FPS", zh: "RGB 回放 · 20 FPS" },
  },
  {
    index: "05",
    episode: "158",
    duration: "12.10 s",
    frames: { en: "242 frames · collection", zh: "242 帧 · 数据采集" },
    video: "videos/dataset-plum-white-left.mp4",
    poster: "videos/dataset-plum-white-left.webp",
    title: { en: "Plum collection → white bowl, left", zh: "李子采集 → 左侧白碗" },
    instruction: {
      en: "A second successful collection example with the fruit settled before the clip ends.",
      zh: "另一段成功采集样例，视频结束前水果已稳定落碗。",
    },
    state: { en: "DATA COLLECTION · SUCCESS", zh: "数据采集 · 成功" },
    camera: { en: "RGB REPLAY · 20 FPS", zh: "RGB 回放 · 20 FPS" },
  },
  {
    index: "06",
    episode: "0577",
    duration: "10.50 s",
    frames: { en: "210 frames · collection", zh: "210 帧 · 数据采集" },
    video: "videos/task-success-world/orange_blue_right.mp4",
    poster: "videos/task-success-world/orange_blue_right.webp",
    title: { en: "Orange collection → blue bowl, right", zh: "橙子采集 → 右侧蓝碗" },
    instruction: {
      en: "A certified strict-physics trajectory with the orange released and settled in the requested bowl.",
      zh: "严格物理认证成功轨迹，橙子已释放并稳定落入指定碗中。",
    },
    state: { en: "DATA COLLECTION · SUCCESS", zh: "数据采集 · 成功" },
    camera: { en: "RGB REPLAY · 20 FPS", zh: "RGB 回放 · 20 FPS" },
  },
];

export const demos: Demo[] = [
  {
    index: "01",
    state: "RUNNING",
    title: { en: "Normal execution", zh: "正常执行" },
    body: {
      en: "Language and two RGB observations condition the policy while the safety monitor checks every action.",
      zh: "语言与双路 RGB 观测共同驱动策略，安全监视器检查每一步动作。",
    },
    event: { en: "command v1 · action chunk active", zh: "指令 v1 · 动作块执行中" },
  },
  {
    index: "02",
    state: "INTERRUPTED",
    title: { en: "Mid-command change", zh: "中途改变指令" },
    body: {
      en: "A new command increments the session version. Stale actions are invalidated and the gripper enters a safe hold.",
      zh: "新指令使会话版本递增；过期动作立即失效，夹爪进入安全保持。",
    },
    event: { en: "v1 → v2 · stale chunk dropped", zh: "v1 → v2 · 丢弃过期动作块" },
  },
  {
    index: "03",
    state: "SUCCESS",
    title: { en: "Released and settled", zh: "释放并稳定落碗" },
    body: {
      en: "A video is accepted only after the gripper opens and the correct fruit remains in the requested bowl during a two-second physics dwell.",
      zh: "只有夹爪张开且正确水果在两秒物理稳定观察期间保持在指定碗中，视频才通过验收。",
    },
    event: { en: "release verified · settled · logged", zh: "释放已验证 · 稳定落碗 · 已留证" },
  },
];

export const features: Feature[] = [
  {
    eyebrow: "01 / VERSION",
    title: { en: "Invalidate stale intent", zh: "让过期意图失效" },
    body: {
      en: "Every command has a version. When it changes, queued policy actions from the previous version lose authority.",
      zh: "每条指令都有版本；版本变化后，旧版本排队动作不再具有执行权。",
    },
  },
  {
    eyebrow: "02 / SAFETY",
    title: { en: "Bound every action", zh: "约束每一步动作" },
    body: {
      en: "Joint bounds and rate limits are enforced before control reaches the Genesis Franka simulation.",
      zh: "在控制进入 Genesis Franka 仿真前，统一执行关节限幅与速率限制。",
    },
  },
  {
    eyebrow: "03 / RECOVERY",
    title: { en: "Recover visibly and honestly", zh: "可见且诚实地恢复" },
    body: {
      en: "Evidence separates the learned first attempt from strict-physics recovery contribution instead of folding both into one opaque score.",
      zh: "评测把学习策略首抓与严格物理恢复贡献分开报告，不把两者折叠成一个不透明分数。",
    },
  },
];

const destinations: TaskRow["targets"] = [
  { label: { en: "white · left", zh: "白色 · 左侧" }, color: "white" },
  { label: { en: "blue · left", zh: "蓝色 · 左侧" }, color: "blue" },
  { label: { en: "white · right", zh: "白色 · 右侧" }, color: "white" },
  { label: { en: "blue · right", zh: "蓝色 · 右侧" }, color: "blue" },
];

export const taskRows: TaskRow[] = [
  { fruit: { en: "Banana", zh: "香蕉" }, targets: destinations },
  { fruit: { en: "Lemon", zh: "柠檬" }, targets: destinations },
  { fruit: { en: "Plum", zh: "李子" }, targets: destinations },
  { fruit: { en: "Apple", zh: "苹果" }, targets: destinations },
  { fruit: { en: "Orange", zh: "橙子" }, targets: destinations },
];

export function t(text: LocalizedText, locale: Locale): string {
  return text[locale];
}
