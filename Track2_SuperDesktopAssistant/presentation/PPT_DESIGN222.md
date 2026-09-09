# Super Desktop Assistant — PPT 生成文档（完善版）

> **用途**：直接投喂给 AI PPT 工具（Gamma / Beautiful.ai / 讯飞智文）生成参赛 PPT。
> **赛道**：AMD AI DevMaster Hackathon 2026-07 · Track 2: Private AI Agents
> **语言**：页面内容全英文（大赛要求）；本设计说明用中文，供生成时理解。
> **篇幅**：12 页 · 16:9
> ⚠️ **重要**：本项目运行在 **AMD Radeon PRO W7900 + ROCm 7.2.3**，**不是 NVIDIA**。任何地方出现 "NVIDIA / CUDA / TensorRT / A100" 都是错误的，必须替换为 AMD/ROCm。

---

## 🎨 全局视觉规范

| 项 | 值 |
|---|---|
| 主色 | AMD 红 `#ED1C24`，深黑 `#0D0D0D`，石墨 `#1A1A1A` |
| 强调色 | 橙 `#FF7A00`（高亮数字）、白 `#FFFFFF`（正文）|
| 背景 | 深色渐变 `#0D0D0D→#1A1A1A` + 细微电路/网格纹理 |
| 字体 | 标题：Sora / Poppins Bold；正文：Inter |
| 风格 | 大标题、大数字、图标化，少文字多图表 |

**贯穿要素**：每页右下角放 AMD Radeon logo 或 "ROCm" 字样，强化品牌。

---

# 📄 分页详细设计

---

## Page 1 — 封面

**标题（主）**：`SUPER DESKTOP ASSISTANT`

**副标题**：`One Chat Interface · All Local AI on AMD Radeon`

**底部信息**：
```
AMD AI DevMaster Hackathon 2026-07 · Track 2: Private AI Agents
Team: Yuanhao Zhang
```

**视觉**：
- 全屏深色底，中央大标题（白字），标题下橙色细线分隔
- 背景装饰：GPU 芯片/电路板轮廓线稿（半透明）
- 右下角 AMD Radeon logo

**备注**：开场 3 秒，点出三个关键词：One Interface / All Local / AMD Radeon。

---

## Page 2 — 痛点与机会

**标题**：`Why a Local Multi-Model Assistant?`

**三栏痛点（每栏 icon + 标题 + 一句）**：
```
🔒 Data Privacy     → Cloud APIs upload your screenshots, voice & documents.
💸 Cost             → Repeated API calls are expensive & need internet.
🔀 Fragmentation    → Juggling multiple tools for different AI tasks.
```

**底部结论大字**：
```
One interface. Every AI model runs locally on your AMD Radeon GPU.
```

**视觉**：三张卡片（深灰底 + 红色 icon），底部一句话用橙字放大。

**备注**：每栏讲一句，最后一句收拢到"本地 + 统一"。

---

## Page 3 — 产品概念

**标题**：`One Interface to Rule All Local AI`

**核心句（页中央大字，两行）**：
```
You speak one sentence —
the system splits it into a task DAG and schedules
LLM · Vision · Speech · Image generation in parallel,
all running on local AMD Radeon (ROCm).
```

**视觉**：中心一个聊天框图标，四角辐射四个能力 icon：
`💬 LLM` `👁️ Vision` `🎤 Speech` `🎨 Image Gen`

**备注**：强调"自动调度多模型"是核心差异点，不是单个模型。

---

## Page 3b — 核心创新（⭐ 重点页，慢讲）

**标题**：`Rewrite → Activate → Maximize`

**三张竖向卡片（从左到右，箭头连接 ①→②→③）**：

```
① ⚡ REAL-TIME PROMPT REWRITING
   "draw a silver-haired girl"
   →  anime girl, silver long hair,
       very awa, masterpiece, best quality
   每个节点执行前，系统动态重写提示词
   （Planner 结构化 + Prompt Builder 标签化
    + Executor 运行时按上游结果再调整）

② 🧠 EXPERT ACTIVATION
   任务类型 → 激活对应本地专家
   💬 LLM · 👁️ Vision · 🎤 Speech · 🎨 Image
   各节点并行执行，各司其职
   （L3 Foremen 按类型路由 + 工具链）

③ 🚀 MAXIMIZE LOCAL AI UTILIZATION
   本地优先路由 + DAG 并行 + ROCm 优化
   （+11% gen · +109% prefill · GPU 满载）
   → 最少云端依赖，最低延迟，100% 私有
```

**视觉**：三张深色卡片横向排列，每张顶部大图标 + 标题，中间示例代码块（橙色高亮），底部一句结论；卡片间用橙色箭头连接，体现"流水线"关系。页底一行大字：`One sentence in → expert-grade prompts, on your GPU.`

**备注**：全片核心卖点，慢讲。强调"不是简单调用一个模型，而是**动态重写提示词 + 激活领域专家 + 最大化本地算力**"——这是与普通聊天助手的本质区别。

---

## Page 4 — 应用场景

**标题**：`Application Scenarios`

**四个场景卡片（每个含：命令 + 实际耗时）**：

| 场景 | 用户命令 | 实测 |
|---|---|---|
| ✍️ Text | "Write a five-character quatrain about autumn." | ~18 s end-to-end |
| 👁️ Vision | "Describe this image's content and style." | ~3 s |
| 🎤 Voice | "Wake word: draw a cyberpunk cat." | STT → image in one flow |
| 🎨 Image | "Draw an anime girl with silver hair." | ~45 s (incl. model load) |

**视觉**：4 个卡片网格，每个卡片右上角放耗时徽章（橙色数字）。

**备注**：每个场景都是真实跑过的，有实际数字——"看得见的性能"。

---

## Page 5 — 系统架构（四层）

**标题**：`Agent Architecture — Four Layers`

**架构图（纵向分层，每层一个色块）**：
```
┌────────────────────────────────────────┐
│ [L1] UserAgent                          │
│  truncation · entity extraction ·       │
│  injection filter · config intercept    │
├────────────────────────────────────────┤
│ [L2] Supervisor                         │
│  Planner (LLM→JSON DAG)                 │
│  Executor (topo-sort + parallel)        │
│  Router (node type → foreman)           │
├────────────────────────────────────────┤
│ [L3] Foremen                            │
│  LLMForeman · SpeechForeman ·           │
│  ImageForeman (8 tools + fallback)      │
├────────────────────────────────────────┤
│ [L4] MCP contract + ai-coin API layer   │
└────────────────────────────────────────┘
        ▼
   [Memory] public + task memory
```

**右侧标注 2 个关键点**：
- `Planner generates a structured JSON task DAG`
- `Failure propagates: upstream fails → downstream SKIPPED`

**视觉**：四层色块（红→橙→灰→深灰渐变），右侧关键词标注，底部记忆块。

**备注**：讲清"规划→分配→执行"编排；这是与普通聊天助手的本质区别。

---

## Page 6 — 核心能力

**标题**：`Core Capabilities`

**6 宫格 icon 矩阵**：
```
💬 LLM Reasoning      👁️ Vision Analysis
   up to 8 tool rounds    multimodal understanding

🎤 STT                🔊 TTS
   faster-whisper (local)  Kokoro-82M (local)

🎨 Image Generation   🔧 8 Agent Tools
   ComfyUI + degradation  read/write/search/memory

💬 Config via Dialog
   Layer 1 only
```

**视觉**：2×3 网格（或 3×2），每个格子深灰底 + 红色 icon + 一句说明。

**备注**：快速带过，不深入；强调"语音 + 视觉 + 生图 + 工具"都在本地。

---

## Page 7 — 模型选型与本地部署

**标题**：`All Local Models on One W7900`

**模型表格（关键数据，必须准确）**：

| Role | Model | Size | Port | Framework |
|---|---|---|---|---|
| LLM + Vision | Qwen2.5-VL-32B-Instruct-AWQ | 20.7 GB | 8000 | vLLM (ROCm) |
| TTS | Kokoro-82M (zh) | 82 M params | 8766 | CPU (ONNX) |
| STT | faster-whisper-medium | ~1.5 GB | 8766 | CTranslate2 CPU int8 |
| Image Gen | MiaoMiao Anima v1.1 (Qwen-Image DiT) | 3.99 GB | 8188 | ComfyUI |

**底部强调**：
```
✅ 100% local — zero cloud API calls
✅ Speech runs on CPU, no GPU contention
```

**视觉**：表格 + 底部绿色对勾强调条。

**备注**：强调"纯本地、零云端"；语音用 CPU 是刻意的显存规划。

---

## Page 8 — AMD GPU 优化（核心页 ⭐）

**标题**：`ROCm Optimization on Radeon W7900`

**大数字对比（页中央，橙字放大）**：
```
Text Generation       12.3 → 13.7 tok/s      +11%
16k Long-Context      7.95s → 3.80s          +109%
```

**三项优化（底部小字列表）**：
```
① bfloat16 → float32 accumulation
   fixes ROCm Triton tl.dot crash
② AWQ block_size 32→128 (large N=27648)
   +10% bandwidth efficiency
③ AWQ Triton kernel tuned (block size + fp32 acc)
   default decode path reaches 13.7 tok/s
   (FP16 matmul path only on original vLLM build)
```

**视觉**：上半部分两个大数字卡片（对比箭头 + 橙色提升百分比），下半部分三条优化列表。

**备注**：**这是 40 分 GPU 优化的核心展示**，慢讲，突出 +109%。

---

## Page 9 — 硬件认知（RDNA3 Roofline）

**标题**：`Know Your GPU — RDNA3 Roofline`

**算力条形图（横向条形 + 数值）**：
```
FP16 / BF16 WMMA     ██████████████████████  123 TFLOPS
INT4 WMMA            ████████████████████████████  245 TOPS
FP8                  ✗ not supported
```
**下方关键结论**：
```
Decode (M=1) can't use WMMA → bandwidth-bound (~54 tok/s ceiling)
We reach 13.7 tok/s = 25% of ceiling (up from 23%)
```

**视觉**：横向条形图（橙/红），FP8 画红色 X，下方灰色结论框。

**备注**：展示"我们不是盲调参数，是按硬件特性定向优化"。

---

## Page 10 — 显存规划

**标题**：`48 GB VRAM Budgeting`

**分区图（堆叠条形/区块）**：
```
vLLM resident (Qwen2.5-VL-32B-AWQ):
  weights 20.7G + vision ~2G + 36k KV ~9G   ≈ 32 GB  (utilization 0.72)
ComfyUI on-demand (image gen)               ≈  8 GB
Speech (TTS/STT)                            =  CPU only
─────────────────────────────────────────────
Total resident + on-demand                  =  40 GB < 48 GB ✅
```

**视觉**：横向堆叠条（红=LLM，橙=生图，灰=CPU语音），底部总和 + 绿色 ✅。

**备注**：说明"常驻 vs 按需"的显存调度策略，合理规划避免 OOM。

---

## Page 11 — 端到端性能（Demo 用例）

**标题**：`End-to-End: One Image Generation Task`

**时间轴（横向流程 + 节点耗时）**：
```
User command → Planner DAG → LLM builds prompt → ComfyUI renders → return
                (0.5s)          (~10s)              (~35s incl. load)     total ≈ 45s
```

**右侧标注**：
```
✅ Full DAG orchestration on one W7900
✅ No cloud round-trip
✅ Graceful degradation if any backend fails
```

**视觉**：横向时间轴（橙色圆点 + 连线），节点下标注耗时，右侧三个对勾。

**备注**：用一个真实用例讲完整闭环；对比"人工在多个工具间切换"的繁琐。

---

## Page 12 — 总结 / 致谢

**标题**：`Why It Stands Out`

**要点列表（7 条）**：
```
✅ ⚡ Real-time prompt rewriting — plain commands become expert-grade prompts
✅ 🧠 Expert activation — every task activates the best local expert (LLM/Vision/Speech/Image)
✅ 🚀 Maximize local AI utilization — DAG parallel + ROCm-tuned (+11% gen, +109% prefill)
✅ Fully local & private — data never leaves the machine
✅ Four-layer agent architecture + DAG parallel orchestration
✅ 3-tier degradation (API → SD-WebUI → ComfyUI)
✅ LLM + vision + speech + image coexist in 48 GB
```

**结尾大字**：
```
Super Desktop Assistant — One Interface, All Local AI.
```

**底部**：`Thank You` + Team name / contact（占位）

**视觉**：深色收尾，左侧对勾列表，中央大字口号，右下 AMD Radeon logo。

**备注**：干净收尾，重述 6 个价值点。

---

## 📌 投喂 AI 时的提示词模板

> 用下面这段作为生成指令开头：

```
Generate a 12-slide dark-tech presentation (16:9) about a local multimodal AI agent
running on AMD Radeon PRO W7900 with ROCm. Color scheme: AMD red (#ED1C24),
dark black (#0D0D0D), orange accent (#FF7A00). Style: big headlines, big numbers,
icon-based, minimal text. IMPORTANT: the platform is AMD Radeon + ROCm, NEVER
write NVIDIA/CUDA/TensorRT. Use the exact page content below, and include
architecture diagrams and benchmark comparison charts where indicated.
[粘贴下面各页的英文内容]
```

---

## ✅ 常见错误自查清单（投喂后检查生成结果）

- [ ] 无 "NVIDIA / CUDA / TensorRT / A100" 字样
- [ ] 跑分数字正确：`+11%` 和 `+109%`（不是 32% / 2.3x）
- [ ] 硬件参数正确：`48GB / 384-bit / 864 GB/s / FP16=123T / INT4=245T / 无 FP8`
- [ ] 有架构图（第 5 页）和跑分对比（第 8 页）
- [ ] 12 页齐全，无空白页
