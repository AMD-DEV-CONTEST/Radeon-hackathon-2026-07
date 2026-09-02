# F02 Preferences Foundation & Workspace Static Prototype

## 状态与依赖

F02 基于 F01 提交继续开发，不复制 F01 工程。创建 F02 时，F01 Draft PR
仍未合入 `main`，因此 F02 必须作为 stacked change review；F01 合入后再调整
F02 的 PR 基线。

本任务没有修改 Runtime、SQLite、Python Web Adapter、现有 API 或 Docker。

## 实现边界

F02 提供：

- `zh-CN` / `en-US` 固定文案目录；
- 浏览器默认语言识别和手动覆盖；
- `system` / `light` / `dark` 主题；
- `standard` / `reduced` 动画偏好；
- `localStorage` 持久化和首屏主题预应用；
- 键盘可操作的轻量设置抽屉；
- 静态 Workspace、现场上下文、四条活动 Mock、已选事件摘要；
- 仅本地反馈的智能指令入口；
- 低干扰 Noah Pulse 胶囊与用户点击后显示的 Mock 摘要。

F02 不提供：

- Runtime 或其他网络请求；
- 真实事件流、实时分析、聊天和写操作；
- approval、critical、通知排队、去重或恢复策略；
- 行动面板、人工确认或任务推进；
- Management 页面；
- Python 静态托管与 Docker 构建变更。

## 偏好语义

偏好统一由 `PreferencesProvider` 管理，存储键为
`alphanoah.preferences.v1`。

语言在没有合法本地记录时读取浏览器语言：中文 locale 映射为 `zh-CN`，
其余映射为 `en-US`。用户选择后以本地记录为准。

主题默认 `system`。只有在 `system` 状态下才响应
`prefers-color-scheme` 的变化；手动选择浅色或深色后不会被系统变化覆盖。
`index.html` 中的最小初始化脚本会在 React 启动前验证偏好并设置
`data-theme`，避免首屏主题闪烁。

动画在没有本地记录时读取 `prefers-reduced-motion`。手动选择会持久化。
`MotionConfig`、`MotionWrapper` 和全局 CSS 使用同一偏好，不由业务组件自行
定义动画参数。

## Mock 与类型边界

`src/types/` 中的 F02 类型仅描述前端 Mock，不是新的 Runtime 状态机。
现有 `RuntimeStatus` 仍标记为前端映射，不允许直接写回后端。

`src/mock/` 的系统健康、活动、事件摘要、Pulse notice 和指令建议均包含：

```text
mockOnly: true
source: "mock"
```

界面不会在 Runtime 不可用时把这些数据当作真实回退。F02 的指令表单只更新
本地 `aria-live` 状态，不发送请求。

## Noah Pulse 的 F02 限制

F02 只定义 `idle`、`informational`、`attention` 三种展示状态。当前
Mock 为 `attention`，但不会自动展开、循环动画或抢占焦点。摘要仅在用户点击
胶囊后出现，并可由明确的关闭按钮收起。

消息优先级、队列、dismiss 恢复、`approval_required`、`critical`、
完整行动面板和 Runtime-backed notice 均留给 F03，不在本任务内预造业务
状态机。

## 后续交付建议

生产边界仍应是 Vite 的静态 `dist/` 产物。未来若需要容器构建，可另行审计
Node build stage 与 Python runtime stage 的拆分；本任务不修改 Docker，
也不让 Node.js 成为生产运行时。
