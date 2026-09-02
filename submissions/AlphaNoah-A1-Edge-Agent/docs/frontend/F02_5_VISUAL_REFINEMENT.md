# F02.5 Visual Refinement & Agent Workspace Re-design

## 目标与边界

F02.5 将 F02 的静态 Workspace 从“高级 SaaS 工作台”调整为现场优先的
Agent 工作空间。它保留 React、TypeScript、Vite、现有路由、偏好系统、
typed i18n、Design Token、Mock 边界和基础组件，不新增依赖。

本次没有修改 Runtime、API、SQLite、Python Web Adapter 或 Docker，也没有
新增网络请求、WebSocket、聊天、3D 或真实业务写操作。行动面板和
Noah Pulse 都是只读视觉原型，不代表 F03 的完整业务状态机。

## 参考研究

研究只覆盖公开文档、README、目录组织与交互思想，没有复制或引入任何参考
项目代码。

| 参考 | 研究范围 | 许可证判断 | 吸收内容 | 明确拒绝 |
| --- | --- | --- | --- | --- |
| React Live Island | compact / expanded 结构、尺寸变形、Motion 布局过渡 | MIT | 单一稳定入口在紧凑态与上下文态之间变化 | 相机黑岛造型、实现代码 |
| Dynamic Island Notifications | 通知上下文、可见数量、展开方式、存在性动画 | README 声明 MIT，但仓库未检测到 license 文件 | 有限、用户驱动的上下文呈现 | 代码、无限脉冲、音频波形、提前实现队列 |
| Glass UI React | token 分层、语义表面、透明层级和 motion 原则 | AGPL-3.0 | 原始色板 → 语义表面 → 功能 token 的设计思路 | 所有代码、霓虹/全息视觉、Admin 布局 |
| shadcn-admin | Drawer、Dialog、Command 与可访问性结构 | MIT | 明确触发器、标题/描述、Escape、焦点恢复 | 侧栏、Dashboard 结构、实现代码 |
| Motion 官方文档 | layout transition、AnimatePresence、spring | 官方文档 | 统一的 morph、presence 和 reduced-motion 边界 | 组件内散落动画参数 |

参考链接：

- <https://github.com/nanxiaobei/react-live-island>
- <https://github.com/nithinpjohn/Dynamic-island-notifications>
- <https://github.com/sam70361/glass-ui-react>
- <https://github.com/satnaing/shadcn-admin>
- <https://motion.dev/docs/react-layout-animations>
- <https://motion.dev/docs/react-animate-presence>
- <https://ui.shadcn.com/docs/components/aria/sheet>

## 吸收的设计原则

1. **稳定入口**：Noah Pulse 保持同一空间锚点，只在用户请求更多上下文时
   从胶囊变为摘要，而不是弹出无关通知卡。
2. **先显示整理后的现实**：首屏首先回答现场位置、关注事件、活动分析和节点
   健康；品牌口号不再占用操作空间。
3. **透明度表达层级**：普通现场表面、命令入口、Pulse 和行动面板使用不同
   透明度、边界、阴影与有限 blur；毛玻璃不重复堆叠。
4. **颜色是信号**：冷灰/蓝是基础语义，黄色和橙色表示注意与警告，绿色只
   表示 online / success。
5. **按需细节**：结构化行动面板默认不存在，只由事件或 Noah Pulse 打开。
6. **运动服务状态理解**：morph、overlay 和 presence 参数集中管理；没有
   无限动画，`reduced` 偏好会使用零时长过渡。
7. **无障碍保留上下文**：行动面板有 dialog 语义、标题/描述、Escape、
   焦点约束和关闭后的触发点恢复。

## 删除或调整的问题

- 删除营销式 Hero、宣传语和大面积首屏留白；
- 删除长期占用右栏的 Selected Event 卡片；
- 将五项 Dashboard 指标改为现场名称与三个高价值状态信号；
- 将多张独立 Event Card 合并成连续的实时事件表面；
- 将大面积绿色从主题、按钮和信息状态中移除；
- 将 Noah Pulse 从普通 Badge 改为 Agent 的渐进式入口；
- 将智能指令从大型卡片缩为底部低干扰 dock。

## 新 Workspace 结构

```text
App Shell
├── Header
│   ├── AlphaNoah identity
│   ├── mock boundary / preferences
│   └── Noah Pulse
├── Site context
│   ├── North assembly · Line 3
│   └── attention / analysis / edge health
├── Time-ordered event field
│   └── event rows + RuntimeStatus lifecycle projection
├── Smart instruction dock (local-only)
└── Agent action context (on demand)
```

事件生命周期只将已有 `RuntimeStatus` 前端映射投影到：

```text
Detected → Analyzing → Human review → Task → Evidence → Closed
```

这是展示映射，不改变后端状态，不允许写回 Runtime。

## Noah Pulse 原型

- **Idle**：没有 notice 时显示 `Noah Pulse / Online`。
- **Attention**：静态黄色注意标记和 `Review needed`，不闪烁、不自动展开。
- **Expanded**：用户点击后在同一锚点显示事件标题、Facts、AI、Next 与
  “打开行动上下文”入口。

F02.5 不实现消息队列、优先级、去重、dismiss 恢复、
`approval_required`、`critical` 或自动展开。以上仍属于 F03。

## 视觉验证

截图输出到被 Git 忽略的 `tmp/f02.5-visual/`：

- `dark-workspace.png`：1440×900，中文深色；
- `light-workspace.png`：1440×900，中文浅色；
- `pulse-attention.png`：1366×768，Pulse 紧凑注意态；
- `pulse-expanded.png`：1366×768，Pulse 展开态；
- `english-1366.png`：英文辅助验证；
- `compact-1024.png`：窄屏辅助验证。

检查结果：必需的四张截图无水平滚动；1366×768 首屏可见现场上下文、四条
事件和智能指令入口；中英文没有截断核心事件信息；浅色和深色均保持冷灰、
低饱和的工业语义。
