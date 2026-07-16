# ADR 0003: Web UI 选 Gradio(不用 Streamlit / 纯 FastAPI+HTML)

- **状态**: Accepted
- **日期**: 2026-07-16
- **决策者**: AMD Radeon Studio Team

## 背景

v0.1 的 Web UI 需要满足:
1. 5 天内出可用 demo
2. 风格参考 LibLibAI(白底 + 左侧深色栏 + 瀑布流)
3. 上传图片 + 显示进度 + 展示多张结果
4. 跑在 AMD Cloud 上,Gradio 原生支持 JupyterLab 内启动

候选:
- **Gradio 4.x**
- Streamlit
- FastAPI + 自写 HTML/JS(React / Vue)

## 决策

**采用 Gradio 4.44+。**

## 后果

### ✅ 优点
- **快** — `gr.Blocks` + `gr.Tab` 1-2 天出 UI
- **LibLibAI 风格可达成** — `gr.Row` + `gr.Column` + `gr.Sidebar`(实验性)+ CSS 注入
- **原生支持图片上传/下载/进度条/Gallery** — 不用自己写
- **AMD 比赛 demo 友好** — AMD 官方 ROCm 文档示例多数用 Gradio
- **可内嵌 JupyterLab** — AMD Cloud 直接 `demo.queue().launch()`

### ❌ 缺点
- 样式定制不如自写前端灵活(需要 `css=` 参数)
- 长流程编排没有 Streamlit 直观(但我们有 FastAPI 后台)

### 🔁 为什么不用 Streamlit
- 重渲染机制对图片流不友好
- 没法像 Gradio 那样把一张张大图瀑布流布局做出来
- 社区 AI demo 多数用 Gradio(参照价值大)

### 🔁 为什么不用自写前端
- 5 天没时间
- 比赛评分看"功能完整性",UI 漂亮但功能弱会失分

## 备注

- LibLibAI 风格通过 `gr.Blocks(css=...)` + 自定义 CSS 实现
- 多页用 `gr.Tabs`(文生图/图生图/风格迁移 三个 tab)
- 模型选择用 `gr.Radio`,实时显示 GPU 占用(后端 API 拿)
