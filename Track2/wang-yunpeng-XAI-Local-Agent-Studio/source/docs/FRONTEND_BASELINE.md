# XAI 控制台 · 前端 UI 框架基准（固化宪法）

> 状态：**已固化 / Frozen** — 2026-07-19 用户签字
> 适用范围：`xai-frontend/`（Route A 官方控制台，唯一底座）
> 效力：此后所有**新增功能模块**必须基于本基准的 UI、交互框架与逻辑扩展；任何偏离须先经用户签字。

---

## 一、技术底座（不可变）

| 维度 | 选型 | 说明 |
|------|------|------|
| 框架 | React 18 + TypeScript | 严格类型 |
| 构建 | electron-vite（Vite）；`vite.web.config.ts` 提供 Web 模式 | 双运行时（桌面 + 浏览器） |
| 样式 | Tailwind 3 + 液态玻璃设计系统 | Token 在 `styles/liquid-glass.css` |
| 图标 | lucide-react | 统一线性图标 |
| 状态 | zustand | 三大 store：workspace / xai-chat / live |
| 动效 | framer-motion | `components/ui-motion.tsx` 统一封装 |
| 画布 | @xyflow/react (ReactFlow 12) | 编排 / 计划画布 |
| API 客户端 | `lib/api.ts` | 统一收口 `http://localhost:8000` |

## 二、设计系统（液态玻璃 · macOS 26 风）

- **单一事实源**：所有颜色/圆角/模糊/阴影一律使用 `styles/liquid-glass.css` 的 CSS 自定义属性（`--color-*`），**禁止硬编码色值**（图表/SVG 特例需显式跟随主题）。
- **主题**：light / dark / system 三态，`ThemeContext` 挂载 `light`/`dark` 到 `documentElement`；新组件必须在两套主题下均可读。
- **玻璃组件族**：`btn-glass` / `input-glass` / `card-glass` / node 展示 / 滚动条 / resize-handle —— 新 UI 复用这些类，不自造样式体系。
- **中国区约定**：涉及行情/涨跌，涨=红、跌=绿；货币默认 ¥。

## 三、布局骨架（App.tsx，不可变结构）

```
┌ Sidebar(240/64px) ┬──────────────────────────────┐
│  品牌 + 模块导航   │  ConsoleTopBar(48px)          │
│  底部引擎状态点    ├──────────────────────────────┤
│                   │  主工作区 (FadeIn + Suspense)  │ [右侧 LiveStatusPanel]
│                   │                               │ (232px，默认关闭，顶栏可切)
│                   ├──────────────────────────────┤
│                   │  底部 EventStreamDrawer(可选)  │
└───────────────────┴──────────────────────────────┘
```

**关键约束（新模块必须遵守）**：
1. 每个页面根节点 `height:100%`，内部滚动区用 `flex:1 + overflow:auto + minHeight:0`。
   - `FadeIn` 已固化为 `height:100% + flex column`，是页面获得有界高度的前提，**不得移除**。
2. 页面切换统一走 `FadeIn`（0.22s ease-out 微交互）。
3. 右侧实时状态面板**默认关闭**，由顶栏 `PanelRight` 切换；状态信息已由「页面顶栏 + 侧边栏底部」承载，页面内不再重复堆叠侧边状态。
4. 紧凑模式（<1024px）：右侧面板转为绝对定位浮层。

## 四、七大模块（console-modules.ts，能力注册表驱动）

对话 / 任务 / 专家团 / 自动化 / 定时任务 / 画布(编排) / 管理（+ 设置）。
- 每个模块在 `console-modules.ts` 声明 `api` 字段，映射到后端端点。
- 新模块 = 新增一条 CONSOLE_MODULES + 一个 `pages/*.tsx`，复用本基准骨架，经 `lib/api.ts` 收口 `:8000`，**零业务逻辑落在前端**（前端是纯视图层，能力由内核能力注册表 `/api/capabilities` 驱动）。

## 五、对话台交互基准（2026-07-19 修订固化）

- **自动跟随**：仅当用户已在底部时才自动滚到最新；上翻查看历史不被打断。
- **回到最新**：上翻后右下角浮现「↓ 回到最新」玻璃按钮，一键回底。
- **双栏独立滚动**：对话区与旁挂面板（计划画布 / 侧栏）各自 `overflow:auto`，鼠标滚轮独立生效。
- **意图预判条**：输入时实时调用 `/api/intent`，展示意图 + 置信度 + 目标内核徽标（Grok Build 橙 / OpenClaw 绿 / Hermes 蓝）。

## 六、扩展规约（新增功能时的 checklist）

- [ ] 复用液态玻璃 token 与玻璃组件类，无硬编码色值
- [ ] 页面根 `height:100%`，滚动区 `flex:1 + overflow:auto + minHeight:0`
- [ ] 走 `FadeIn` 页面过渡
- [ ] 数据经 `lib/api.ts` 收口 `:8000`，不直连其他端口
- [ ] 能力项与后端 `/api/capabilities` 对齐（命名一致，见 D2 约定）
- [ ] light / dark 双主题均可读
- [ ] 新模块在 `console-modules.ts` 注册并声明 `api`

## 七、待办对齐项（D2 能力命名一致性）

前端画布节点 `conditional` 与后端能力表 `condition` 命名不一致；`general/office/research/longterm` 为前端意图标签/遗留节点，未进后端能力表。新增能力时**以后端 `/api/capabilities` 的 id 为准**，前端 SEM_NODES 命名向其对齐。
