# NodeFlow 前端 UI 需求规格（喂给 Tree Design 执行）

> 你正在接手 NodeFlow 的前端 UI 完善工作。NodeFlow 是一个运行在 AMD GPU（ROCm）上的"节点式 AI 画布"应用：用户像流程图一样在画布上摆放节点、连接节点，每个节点生成一张图。后端（FastAPI）已就绪，接口契约见文末。**你的任务是设计并实现与后端完全对齐的前端 UI，不要改动后端接口，不要自行发明不存在的字段或参数。**
>
> 本文是唯一权威需求来源。所有页面、交互、字段都必须与本文描述一致。若某处与后端返回不符，以本文为准，并把问题记录下来反馈给项目负责人，不要擅自改。

---

## 1. 产品定位与核心体验

- **一句话**：在无限画布上，通过拖拽节点、连线成图，把"文生图"和"草图生图"变成可组合、可迭代的工作流。
- **核心交互**：画布是主体，节点是生成单元，节点之间可连线形成"一个节点输出作为下一个节点输入"的流程。
- **视觉基调**：保持现有 `NodeFlow` monochrome 极简风格（黑/白/灰，无渐变彩色点缀，玻璃拟态面板）。**保留现有页面的 `--nf-*` CSS 变量体系与 Tailwind 配置，不要推倒重来。**

### 1.1 两种模式（顶层概念，必须替换现有 Sketch/Text）

后端只有两种模式：`fast`（快速版）和 `expert`（专家版）。**这是全局唯一的模式开关，位于顶栏中央。**

| 模式 | 定位 | 模型 | 参数控制 | LoRA |
| --- | --- | --- | --- | --- |
| Fast 快速版 | 快速出图、预览、迭代 | 蒸馏模型（SDXL Lightning 4/8 步） | 固定，只暴露风格、比例、简单强度 | 自动应用默认，不暴露权重调节 |
| Expert 专家版 | 高质量、精细控制 | 完整模型（FLUX.2-klein、NoobAI、Animagine、Illustrious） | 步数、CFG、种子、负向提示、强度、比例全部可调 | 可逐条加载/卸载、调节权重 |

**关键决策：Sketch 不是一种模式，而是画布内的一个"节点类型"。** 原设计的 Sketch / Text 顶栏切换要删除，替换为 Fast / Expert 切换。Sketch 能力（画草图 → 图生图）作为节点本身的可选输入形态存在，见 §3.3。

---

## 2. 页面与面板清单

| 编号 | 页面/面板 | 说明 | 状态 |
| --- | --- | --- | --- |
| P1 | 主画布（含空态） | 无限画布 + 节点图 + 顶栏 + 底部控制坞 | 已有①，需改造 |
| P2 | 生成中 | 节点内显示加载/进度 | 已有②，需改造 |
| P3 | 单节点结果展示 | 节点宽高、图、参数、重生成 | 已有③⑤，需改造 |
| P4 | 多节点画布 | 节点连线、布局、选择 | 已有④⑥，需改造 |
| P5 | 风格选择面板 | 8 风格网格，选中态 | 已有⑦⑧，需对齐 |
| P6 | 模型选择面板 | 按模式列出模型，含切换 | 新增 |
| P7 | 参数面板（Expert） | 步数/CFG/种子/负向/比例 | 新增 |
| P8 | LoRA 管理面板 | 加载/卸载/权重滑杆 | 新增 |
| P9 | 模型商店 | 浏览热门模型/LoRA、下载、许可标注 | 新增 |
| P10 | 历史记录 | 最近生成列表 | 新增（顶栏图标占位已有） |

---

## 3. 主画布（P1）详细规格

### 3.1 顶栏（改造现有）

- 左侧：品牌 `NodeFlow` + `AI CANVAS` 标签（保留）。
- 中央：**模式切换**，两个胶囊按钮 `Fast` / `Expert`。选中态白底黑字（沿用现有 `.mode-btn.is-active`）。**删除 `Sketch` / `Text`**。
  - 切换模式时，底部控制坞与节点内的参数面板随之切换（Fast 隐藏/hide 专家参数）。
- 右侧：`History`（历史）、`Settings`（设置）、`Store`（模型商店）三个图标按钮。`Store` 为新增，打开 P9。

### 3.2 画布区

- 沿用现有点阵画布（`#excalidraw-canvas-region`）与 Excalidraw 内核（保留 `canvas-runtime.js`）。
- 空态提示：保留现有"画点什么，开始创作"，但文案改为中性引导，可同时适用文生图与草图节点。
- 画布工具栏（左下）与缩放工具栏（右下）：保留现有工具按钮（选择/画笔/裁剪/抓手、缩放/适应）。

### 3.3 节点（核心）

画布上的每个生成单元是一个**节点卡片**。节点有两种输入形态：

1. **文生图节点**：仅含提示词输入框 + 生成按钮。
2. **草图节点**：含一个可绘制的小画布（或上传图片）+ 强度滑杆 + 生成按钮。

两种节点在添加时二选一（通过画布上的"添加节点"入口，或右键菜单）。节点卡片统一结构：

- 顶部：节点图标 + 类型标签（`Text` / `Sketch`）+ 删除按钮。
- 中部：提示词输入框（文生图），或草图绘制区 + `强度` 滑杆（草图）。提示词输入框回车即生成。
- 底部：**风格选择**（当前风格徽标，点击展开 P5）+ **生成按钮**（沿用现有 `Generate` 样式）。
- 生成中：节点内显示加载动画 + 进度（P2）。
- 生成后：S3 展示结果图，支持单图重生成。

**连线规则**：节点输出端口可连线到另一节点的输入端口，组成流程。当前 MVP 可先实现"连线后把结果作为下一节点的参考图"（即下一个节点自动变为草图型并以该图作为输入），具体数据流由前端与后端协商，UI 只需呈现连线与端口。

### 3.4 底部控制坞（改造现有）

现有 `#floating-control-dock` 保留，但内容按模式动态变化：

- **Fast 模式**：`风格选择` + 分隔线 + `比例选择`（胶囊 chip）+ 分隔线 + `Generate`。
- **Expert 模式**：`风格选择` + 分隔线 + `比例选择` + 分隔线 + `参数`按钮（展开 P7）+ 分隔线 + `LoRA`按钮（展开 P8）+ 分隔线 + `Generate`。

> 图生图（草图节点）的强度滑杆放在节点内部，不放底部控制坞。

---

## 4. 风格选择（P5，改造现有 ⑦⑧）

- 沿用现有 8 风格网格与选中态（`.style-card.is-selected` 白描边+光晕）。
- 风格列表必须以 `GET /api/styles` 返回为准（当前为 `cyberpunk, anime, watercolor, oil_painting, 3d_render, pixel_art, concept_art, minimalist`）。
- 每个风格卡片显示风格名即可（色块可保留为装饰，但**不要**用色块暗示风格，因当前主题为黑白单色）。
- 全屏面板（⑦）与轻量弹窗（⑧）两种形态都保留：全屏用于画布内大范围选择，轻量弹窗用于控制坞内快捷选择。

---

## 5. 模型选择（P6，新增）

- 入口：Expert 模式控制坞内"模型"按钮（或参数面板内）。
- 数据来源：`GET /api/models?mode=fast|expert`，按当前模式过滤。
- 列表项展示：模型名 + 架构标签（SDXL / FLUX）+ 显存占用（`vram_gb`）+ 许可证徽标（`commercial_use`：可商用 / 仅非商用）。
- 点击某项 → 调 `POST /api/models/switch` 切换，切换成功后该项标为"当前"，并刷新当前模型的参数范围与比例选项。
- 切换中显示加载态；切换失败提示错误并保留原选中。

**当前模型注册表（供 UI 预置，最终以接口为准）：**

| 模式 | 模型 ID | 名称 | 架构 | 许可 | 可商用 |
| --- | --- | --- | --- | --- | --- |
| fast | `sdxl_lightning_4step` | SDXL Lightning 4-Step | SDXL | OpenRAIL++M | 是 |
| fast | `sdxl_lightning_8step` | SDXL Lightning 8-Step | SDXL | OpenRAIL++M | 是 |
| expert | `flux2klein_base` | FLUX.2 Klein Base | FLUX | Apache 2.0 | 是 |
| expert | `flux2klein_distilled` | FLUX.2 Klein Distilled | FLUX | Apache 2.0 | 是 |
| expert | `noobai_xl` | NoobAI XL 1.0 | SDXL | Fair AI | 否 |
| expert | `animagine_xl` | Animagine XL 4.0 | SDXL | SDXL License | 是 |
| expert | `illustrious_xl` | Illustrious XL | SDXL | Fair AI | 否 |

---

## 6. 参数面板（P7，Expert，新增）

数据来源：`GET /api/models/{model_id}/config` 返回 `param_ranges`、`recommended_aspect_ratios`、`ratio_details`。**所有滑杆/输入框的 min/max/step 必须按该模型配置渲染，禁用字段（`locked: true`）置灰不可改。**

| 控件 | 字段 | 说明 |
| --- | --- | --- |
| 步数滑杆 | `num_inference_steps` | 按 `param_ranges` 渲染；`locked` 时固定 |
| CFG 滑杆 | `guidance_scale` | 同上 |
| 种子输入 | `seed` | 数字输入；留空为随机 |
| 负向提示 | `negative_prompt` | 文本域（Expert 专属） |
| 比例选择 | `aspect_ratio` | 胶囊 chip，按 `ratio_details` 渲染；非推荐比例标注"可能效果不佳" |

**比例说明**：不同模型推荐比例不同（SDXL 系 1:1/3:4/4:3/3:2/16:9；FLUX 系 1:1/3:4/4:3/16:9/9:16）。UI 只需展示当前模型 `supported_ratios` 内的比例，超出部分自动隐藏。若用户强制选了非推荐比例，生成后展示后端返回的 `warnings`。

---

## 7. LoRA 管理（P8，Expert，新增）

- 数据来源：`GET /api/loras` 列出已加载 LoRA；`GET /api/store/loras` 浏览可下载。
- 面板结构：
  - **已加载**：列表，每项含名称 + 权重滑杆（0–2，默认按模型）+ 卸载按钮 → `POST /api/loras/unload`。
  - **加载新 LoRA**：文件路径输入或从商店选择 → `POST /api/loras/load`（`path` + `weight`）。
- 每个 LoRA 显示类别徽标（通用优化 / 风格化）与架构（SDXL / FLUX），不匹配当前模型的 LoRA 置灰并提示。
- **Fast 模式不展示此面板**（自动应用默认 LoRA）。

---

## 8. 模型商店（P9，新增）

- 两个 Tab：`Checkpoint`（模型）与 `LoRA`。
- Checkpoint 数据：`GET /api/store/models?source=hf|limit`；LoRA 数据：`GET /api/store/loras?source=civitai&base_model=SDXL 1.0|limit`。
- 列表项：缩略图（如有）+ 名称 + 来源（HuggingFace / Civitai）+ 下载数/热度 + **许可证徽标**（开源 / 是否可商用，版权提示必须显著，避免版权纠纷）。
- 操作：`下载` 按钮 → `POST /api/store/download`（`url` + `target_path` + `type`），下载中显示进度，完成后可"加载到当前模型"。
- 空态/加载失败：展示友好提示与重试。

---

## 9. 历史记录（P10，新增）

- 顶栏 `History` 打开。
- 列出最近生成的图片（缩略图 + 提示词 + 模式 + 模型 + 时间戳）。
- 点击缩略图 → 回到画布并定位到对应节点；支持"重新生成"。

---

## 10. 生成与反馈

- 生成请求：文生图 `POST /api/generate/text2img`（JSON），草图/图生图 `POST /api/generate/img2img`（multipart，含 `file` + `strength`）。
- 请求体字段（text2img）：`prompt, mode, model(可选), style, aspect_ratio, width/height(可选), num_inference_steps, guidance_scale, seed, negative_prompt, loras`。
- img2img 字段：`file, mode, model, style, aspect_ratio, strength, width/height, num_inference_steps, guidance_scale, seed, negative_prompt, loras`。
- **Fast 模式**：只传 `prompt/mode/style/aspect_ratio`，专家参数一律不传（后端会忽略并返回 warning）。
- 响应含 `image`（base64 data URL）、`width/height`、`generation_time_sec`、`warnings`。生成后把 `warnings` 以非阻断的 toast 展示（如"该比例非当前模型推荐"）。
- 生成中：节点内 loading，按钮禁用；失败展示错误信息。

---

## 11. 状态与数据流

- 全局状态：`当前模式(fast/expert)`、`当前模型(model_id)`、`当前风格`、`已加载LoRA`、`节点列表`。
- 应用启动时 `GET /api/info` 与 `GET /api/health` 拉取当前模型与 GPU 状态。
- 切换模式 → 拉取该模式模型列表 → 若当前模型不属于该模式则切到该模式默认模型。
- 切换模型 → 拉取该模型 `config`（参数范围 + 比例）→ 刷新参数面板。
- 所有 API 调用统一 baseURL，前端可配置。

---

## 12. 需修改的现有设计点（对照清单）

1. 顶栏模式：`Sketch/Text` → `Fast/Expert`（删除 Sketch 作为模式的入口）。
2. Sketch 降级为节点类型：从顶栏移除，改为添加节点时二选一（Text 节点 / Sketch 节点）。
3. 底部控制坞：新增比例选择（Fast）；Expert 增加参数/LoRA 入口。
4. 新增：模型选择面板、参数面板、LoRA 面板、模型商店、历史记录。
5. 风格选择：8 风格保持，但数据源改为接口，色块仅作装饰。
6. 保留：monochrome 视觉体系、`--nf-*` 变量、Excalidraw 画布、动效（诚实地保留现有 `prefers-reduced-motion` 降级）。

---

## 13. 后端 API 契约（供你对齐，勿改）

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/info` | 服务信息、当前模型、GPU 描述 |
| GET | `/api/health` | 健康检查、GPU 状态、当前模型、可用风格 |
| GET | `/api/styles` | 风格列表 `{styles:[{key,label,prompt_prefix}]}` |
| GET | `/api/models?mode=` | 按模式返回模型列表 |
| GET | `/api/models/current` | 当前加载模型 |
| GET | `/api/models/{model_id}/config` | 模型参数范围 + 比例详情 |
| POST | `/api/models/switch` | 切换模型，body `{model_id}` |
| GET | `/api/loras` | 已加载 LoRA |
| POST | `/api/loras/load` | 加载 LoRA，body `{path, weight}` |
| POST | `/api/loras/unload` | 卸载 LoRA，body `{lora_id}` |
| GET | `/api/store/models?source=&limit=` | 商店热门模型 |
| GET | `/api/store/loras?source=&base_model=&limit=` | 商店热门 LoRA |
| POST | `/api/store/download` | 下载模型/LoRA，body `{url, target_path, type}` |
| GET | `/api/gpu/status` | GPU 显存状态 |
| POST | `/api/generate/text2img` | 文生图（JSON） |
| POST | `/api/generate/img2img` | 图生图（multipart） |

**渲染约束**：所有滑杆 min/max/step、比例选项、模型列表、风格列表均以接口返回为准，禁止硬编码。许可证徽标（`commercial_use`）必须在模型与商店条目上显著展示。

---

## 14. 交付要求

- 用现有 `NodeFlow` 的 monochrome 视觉体系与 `--nf-*` 变量，保证风格统一。
- 每个页面/面板输出可直接运行的 HTML（含交互 JS），与现有 8 个页面同版式。
- 完成后，将每个页面与后端接口的对应关系、以及任何你发现需要在后端配合的改动点，整理成一份简短说明返回给项目负责人。