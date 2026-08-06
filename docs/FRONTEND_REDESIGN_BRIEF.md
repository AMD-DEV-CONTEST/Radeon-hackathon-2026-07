# 3DGenerateFlow 前端重新设计依据

> 本文档梳理当前已实现的后端能力、前端组件与数据流，作为重新设计 Web UI 的依据。建议参考 **LibTV 的导演台 + 故事板**、**OiiOii 的短剧画布**，把“低门槛向导”和“专业画布”两种模式同时保留。

---

## 一、产品定位

**一句话**：上传 1 张物品 / 宠物 / 人物照片，输入一句话风格需求，后端在 AMD Radeon GPU / ROCm 上本地完成图生图 → 多视角合成 → 3D 生成 / 2.5D 浮雕 → 打印检查，最终输出可直接 3D 打印的全彩 3D 或 2.5D 模型。

**两种典型用户**：
1. **普通用户**：只想上传照片、选风格、点生成，拿到模型。
2. **创作者 / 设计师**：想控制多视角、调打印参数、重做某一步、对比多个版本。

---

## 二、后端能力矩阵

### 2.1 API 路由清单

| 方法 | 路径 | 作用 | 关键输入 | 关键输出 |
|---|---|---|---|---|
| GET | `/health` | 服务存活检查 | - | `{status, app}` |
| GET | `/health/gpu` | **AMD GPU / ROCm 状态** | - | `rocm_available`, `gpu_name`, `gpu_memory_mb`, `torch_cuda_available`, `hip_version` |
| POST | `/upload` | 上传图片 | `multipart/form-data` 图片 | `job_id`, `filename`, `path`, `content_type` |
| POST | `/jobs` | 旧版直接创建任务 | `input_image_path`, `style`, `prompt` | `JobResponse` |
| GET | `/jobs/{job_id}` | 轮询任务状态 | `job_id` | `JobResponse`（含 `status`、`print_report`、`multiview_image_paths` 等） |
| GET | `/files/{file_path:path}` | 下载/预览文件 | 相对路径 | `FileResponse`（图片、GLB、STL） |
| GET | `/styles` | 获取风格目录 | - | 风格数组 |
| POST | `/agent/plan` | **AI 规划风格与流程** | `user_input`, `image_path` | `PlanResponse`（goal, style_id, output_mode, steps, reasoning） |
| POST | `/agent/execute` | **执行计划** | `plan`, `input_image_path` | `{job_id, status}` |
| POST | `/agent/chat` | 自然语言调整计划 | `message`, `plan` | `{action, params, response}` |
| GET | `/agent/memory/style` | 获取用户最近偏好风格 | - | `{last_style_id}` |

### 2.2 任务状态机

```
pending → preprocessing → generating_multiview → generating_3d → postprocessing → completed
                                         ↓
                                      failed
```

- `pending`：已提交，排队中。
- `preprocessing`：读取图片、准备输入。
- `generating_multiview`：风格迁移 + 多视角合成（2.5D 浮雕里对应深度估计）。
- `generating_3d`：3D 网格生成。
- `postprocessing`：缩放、贴图 fallback、打印检查。
- `completed`：结果可下载。
- `failed`：失败并带 `error_message`。

### 2.3 输出产物

| 输出模式 | 产物文件 | 说明 |
|---|---|---|
| `fullcolor_3d` | `results/{job_id}/model.glb` | 彩色 3D 模型（Web 预览 + 全彩打印） |
| `relief_2d5` | `results/{job_id}/relief.stl` + `relief.glb` | STL 用于单色 3D 打印，GLB 用于带贴图预览 |
| 通用 | `uploads/{job_id}/styled_preview.png` | 风格化后的参考图 |
| 通用 | `uploads/{job_id}/view_*.png` / `depth.png` | 多视角图或深度图 |

### 2.4 打印报告字段

```json
{
  "volume_cm3": 30.38,
  "dimensions_mm": [79.9, 79.9, 7.0],
  "wall_thickness_mm": 2.0,
  "target_height_mm": 80.0,
  "is_watertight": true,
  "base_thickness_mm": 3.0,
  "relief_height_mm": 4.0,
  "invert": false,
  "shape": "rectangular",
  "unit": "mm"
}
```

### 2.5 风格目录

当前 10 个风格，分为 3 大类：

| 大类 | 风格 ID | 输出模式 | 典型参数 |
|---|---|---|---|
| 3D 写实 | `realistic_3d` | `fullcolor_3d` | `target_height_mm`, `wall_thickness_mm` |
| 3D 风格化 | `cartoon_3d`, `lowpoly_3d`, `voxel_3d`, `clay_3d`, `sketch_3d` | `fullcolor_3d` | 同上，部分带 `decimate_ratio` |
| 2.5D 浮雕 | `relief_embossed`, `relief_lithophane`, `relief_coin`, `relief_silhouette` | `relief_2d5` | `base_thickness_mm`, `relief_height_mm`, `shape`（rectangular/circular）, `invert` |

---

## 三、当前前端实现概述

### 3.1 技术栈

- React + TypeScript + Vite
- Tailwind CSS
- Zustand（全局状态：`viewMode`, `currentJob`, `plan`, `styles`, `chatMessages`）
- React Three Fiber + React Three Drei（GLB 预览）
- Axios（API 客户端）

### 3.2 现有组件

| 组件 | 职责 | 当前状态 |
|---|---|---|
| `App.tsx` | 布局壳，切换 Wizard / Canvas 模式 | 已实现 |
| `UploadForm.tsx` | 上传图片、输入需求、AI 规划、风格选择、提交生成 | 已实现，但功能较密集 |
| `JobStatus.tsx` | 轮询任务状态、展示进度、下载按钮 | 已实现，较简单 |
| `WorkflowCanvas.tsx` | 6 步流程可视化 | 已实现，仅展示状态 |
| `StoryboardGrid.tsx` | 多视角 / 深度图 2×2 或 1×4 展示 | 已实现，重生成按钮为占位 |
| `ModelViewer.tsx` | Three.js 模型预览 | 已实现，只展示最终模型 |
| `ChatPanel.tsx` | 右侧 AI 聊天，快速修改风格/参数 | 已实现，但 action 映射有限 |
| `GpuStatus.tsx` | 顶部 GPU 状态徽章 | 已实现 |

### 3.3 当前两种模式

- **Wizard（向导）**：左右两栏，左上传+状态，右预览+说明。适合低门槛用户。
- **Canvas（画布）**：左上传+状态，中画布+分镜+预览，右 AI 聊天。适合创作者。

---

## 四、重新设计核心原则

### 4.1 参考 LibTV / OiiOii 的优秀体验

- **导演台（Director Console）**：顶部显示项目/镜头/角色/资产，左侧工具栏，中间画布，右侧属性/聊天。
- **故事板（Storyboard）**：把生成过程变成可拖拽、可重拍、可替换的卡片。
- **低门槛入口**：新用户直接看到“上传 + 一句话 + 生成”大按钮，无需理解画布。
- **实时反馈**：每个步骤都可视化进度、预览中间产物、允许单步重做。
- **一致性资产**：角色/风格/参数被记忆，可跨任务复用。

### 4.2 设计原则

1. **默认简单，专业可展开**：首页 3 步完成，展开后进入导演台。
2. **过程可视化**：把 pipeline 变成故事板，不只是进度条。
3. **中间产物可编辑**：多视角图可替换、风格可实时切换、参数可滑动调整。
4. **AMD GPU 状态始终可见**：顶部徽章 + 实时资源监控，强化比赛评审点。
5. **打印报告前置**：在下载前就告诉用户能不能打印、尺寸/体积/价格估算。
6. **结果可对比**：多个生成版本并排，方便选择最佳结果。

---

## 五、建议的新页面/组件结构

### 5.1 整体信息架构

```
首页（Landing）
  └─ 快速开始：上传 + 输入 + 生成
  └─ 近期项目（从 memory 读取）

导演台（Director）
  ├─ 顶部：项目名 + GPU 状态 + 导出/分享
  ├─ 左侧：素材库 / 风格库 / 参数面板
  ├─ 中间：故事板画布 + 3D 预览器
  └─ 右侧：AI 导演助手 + 任务日志

结果页（Result）
  └─ 模型预览 + 打印报告 + 下载 + 再次编辑
```

### 5.2 建议新增/重做的组件

| 组件 | 功能 | 优先级 |
|---|---|---|
| `HeroUploader` | 首页超大拖放上传 + 示例模板 | 高 |
| `StyleCarousel` | 横向风格卡片，带 hover 效果、分类筛选 | 高 |
| `StoryboardTimeline` | 时间线式 6 步故事板，每步可展开预览 | 高 |
| `MultiViewEditor` | 四宫格多视角，单张可替换/重生成 | 高 |
| `ParamDrawer` | 打印参数滑块：高度、壁厚、底座、浮雕高度、是否圆形 | 高 |
| `ModelInspector` | 3D 预览 + 线框/贴图/尺寸标注切换 | 高 |
| `PrintReportCard` | 打印报告可视化卡片（体积、尺寸、watertight、预估耗材） | 高 |
| `VersionCompare` | 多版本生成结果并排对比 | 中 |
| `AssetLibrary` | 历史图片、历史模型、风格收藏 | 中 |
| `GpuMonitor` | 实时 GPU 占用/温度/显存 mini 仪表盘 | 中 |
| `ProjectHeader` | 项目名称、保存、导出、分享 | 中 |

### 5.3 关键页面布局建议

#### 首页（Landing / Quick Start）

```
+-----------------------------------------------------------+
|  Logo          [GPU状态]    [进入导演台]  [GitHub]           |
+-----------------------------------------------------------+
|                                                           |
|          把一张照片变成可 3D 打印的全彩模型                    |
|                                                           |
|     [ 拖拽或点击上传照片 ]                                  |
|     支持：人物 / 宠物 / 物品                                |
|                                                           |
|     你想要什么风格？                                        |
|     [ 写实3D ] [ 卡通3D ] [ 浮雕纪念币 ] [ 低多边形 ] ...     |
|                                                           |
|     [ 开始生成 ]                                            |
|                                                           |
+-----------------------------------------------------------+
|  最近生成 · 示例展示                                        |
+-----------------------------------------------------------+
```

#### 导演台（Director）

```
+-----------------------------------------------------------+
|  [项目名]  [保存] [导出]          [GPU: AMD ROCm Ready]     |
+-----------------------------------------------------------+
| 左栏        |            中间画布              |  右栏     |
| 素材库      |  ┌─────────────────────────┐     | AI 助手   |
| 风格库      |  │   故事板 / 分镜          │     | 参数面板  |
| 参数面板    |  │  upload → style → views │     | 任务日志  |
|             |  │  → 3D → print → export  │     |          |
|             |  └─────────────────────────┘     |          |
|             |  ┌─────────────────────────┐     |          |
|             |  │      3D 模型预览         │     |          |
|             |  └─────────────────────────┘     |          |
+-----------------------------------------------------------+
```

---

## 六、数据流与状态管理建议

### 6.1 建议的 Zustand Store 扩展

```ts
interface AppState {
  // 全局模式
  viewMode: 'landing' | 'wizard' | 'director' | 'result'

  // 当前项目
  currentProject: Project | null
  projects: Project[]

  // 当前生成任务
  currentJob: JobResponse | null
  isPolling: boolean

  // 当前计划
  plan: PlanResponse | null

  // 素材
  uploads: UploadAsset[]
  generatedAssets: GeneratedAsset[]

  // 风格与参数
  styles: StyleTemplate[]
  selectedStyleId: string
  params: Record<string, number | boolean | string>

  // 编辑器状态
  activeStepId: string | null
  selectedViewIndex: number | null
  previewMode: 'solid' | 'wireframe' | 'texture' | 'printbed'

  // AI 聊天
  chatMessages: ChatMessage[]
}
```

### 6.2 关键交互流程

#### 流程 A：快速生成（Landing → Result）

1. 用户上传图片 → 调用 `/upload`。
2. 用户输入/选择风格 → 调用 `/agent/plan` 获取计划。
3. 点击开始生成 → 调用 `/agent/execute`。
4. 轮询 `/jobs/{job_id}` 直到 `completed` / `failed`。
5. 自动跳转到 Result 页展示模型和打印报告。

#### 流程 B：导演台精细编辑

1. 进入 Director。
2. 上传图片，AI 生成计划。
3. 在 Storyboard 中点击任意步骤：
   - **风格步骤**：可切换风格，实时重新生成 styled_preview。
   - **多视角步骤**：四宫格展示，可单张重生成或替换为本地图片。
   - **参数步骤**：滑块调整高度/壁厚/浮雕高度，实时重新后处理。
4. 右侧 AI 聊天理解自然语言指令，修改计划或参数。
5. 生成完成后保存到项目资产库。

---

## 七、需要后端配合的扩展点

当前后端已经能跑通完整流程，但如果前端要支持更灵活的导演台，需要后端新增/扩展以下接口：

| 能力 | 建议接口 | 说明 |
|---|---|---|
| 单步重生成 | `POST /agent/step/{step_id}/regenerate` | 只重做某一步（如只重新生成 back 视角） |
| 单图替换后重生成 | `POST /upload` + `POST /agent/regenerate-from-step` | 用户上传某视角替换图，从该步继续 |
| 仅后处理 | `POST /jobs/{job_id}/postprocess` | 只调整参数重新缩放/贴图/打印检查 |
| 批量风格对比 | `POST /agent/batch-plan` | 一次提交多个风格，后端串行/并行生成 |
| 项目 CRUD | `GET/POST/PUT /projects` | 保存多个生成版本、历史记录 |
| 资产库 | `GET /assets`, `POST /assets` | 风格、参考图、模型资产列表 |
| GPU 实时指标 | `GET /health/gpu/metrics` | 利用率、显存、温度，给前端仪表盘 |
| 任务日志流 | `WS /ws/jobs/{job_id}` 或 SSE | 替代轮询，实时推送步骤日志 |

**优先级建议**：
- 比赛前最高优保证现有流程稳定，先把现有 API 的 UI 做漂亮。
- 如果时间充裕，补 `单步重生成`、`仅后处理`、`GPU metrics`、`SSE 日志流`。
- 项目/资产库可先用 localStorage 或前端状态模拟，比赛后补后端。

---

## 八、视觉与交互建议

### 8.1 视觉风格

- **深色主题**：科技/创作工具感，参考 ComfyUI、LibTV、Runway。
- **强调色**：Indigo / Violet / Emerald（代表 AI、3D、成功）。
- **卡片式布局**：每个步骤、每个视角、每个参数都是一张卡片。
- **动画**：
  - 生成中步骤脉冲高亮。
  - 多视角图依次淡入。
  - 3D 模型生成后旋转入场。
  - GPU 徽章 hover 展开详细指标。

### 8.2 交互细节

- **上传区**：支持拖拽、粘贴、示例图一键载入。
- **风格选择**：不用下拉框，用网格卡片 + 缩略图/示例。
- **参数调整**：滑块 + 数值输入 + 实时预览影响。
- **多视角**：鼠标悬停显示大图，点击可替换/重生成。
- **3D 预览**：默认自动旋转，支持暂停、重置、线框、截图。
- **下载**：根据输出模式显示不同按钮（GLB / STL / 3MF / 打印报告 PDF）。
- **空状态**：每个区域在未生成时都有引导插图和文案。

---

## 九、现有前端代码可复用部分

| 文件 | 可复用内容 | 建议 |
|---|---|---|
| `api/client.ts` | API 封装、类型定义 | 保留，扩展新接口类型 |
| `store/jobStore.ts` | Zustand 状态结构 | 扩展为 `appStore` |
| `components/ModelViewer.tsx` | R3F GLB 预览 | 提取为 `ModelInspector`，增加模式切换 |
| `components/WorkflowCanvas.tsx` | 步骤可视化 | 扩展为 `StoryboardTimeline` |
| `components/StoryboardGrid.tsx` | 多视角网格 | 扩展为 `MultiViewEditor` |
| `components/ChatPanel.tsx` | AI 聊天 | 保留，增强 action 反馈 |
| `components/GpuStatus.tsx` | GPU 徽章 | 保留，扩展为 mini 仪表盘 |

---

## 十、下一步行动建议

1. **先确定设计风格**：低门槛向导为主，还是导演台为主？建议两者并存。
2. **绘制主要页面线框**：首页、导演台、结果页三张线框。
3. **先实现首页快速生成**：这是比赛演示的核心路径，确保 3 步内完成。
4. **再实现导演台增强**：作为加分项，展示过程可控性和专业性。
5. **后端配合**：若时间允许，补 `单步重生成` 和 `SSE 日志`。

---

## 附录：当前 API 调用示例

```ts
// 1. 上传
const upload = await uploadImage(file)

// 2. AI 规划
const plan = await agentPlan('写实 3D 新娘全身像', upload.path)

// 3. 执行
const { job_id } = await agentExecute(plan, upload.path)

// 4. 轮询
const job = await getJob(job_id)

// 5. 预览文件
const modelUrl = `${api.defaults.baseURL}/files/${encodeURIComponent(job.result_model_path)}`
```

更多细节参考：
- 后端路由：`services/api/routers/`
- 后端 Agent：`services/api/agents/`
- 后端 Pipeline：`services/api/pipelines/`
- 前端组件：`apps/web/src/components/`
