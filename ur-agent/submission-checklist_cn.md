# UR-Agent 参赛提交清单

> 中文工作稿。比赛仓库 README 要求最终 PR、项目说明和材料使用英文，提交前需要将本清单中的正式材料翻译为英文或补充英文版。

## 1. 基本信息

| 项目 | 内容 |
| :--- | :--- |
| 赛道 | Track 2: 私有 AI Agent 开发与本地部署 |
| 应用名称 | UR-Agent (Uni-Resource Agent) |
| 参赛者 | qiancy |
| AMD Developer Program No. | 00000657 |
| GitHub | https://github.com/qiancy/ur-agent |
| 源码 License | MIT |
| 生产环境 Demo 网站 | https://rc-e2369faa1fa45132.radeon.firstdg.ai |
| 本地服务 | http://127.0.0.1:5173 |
| 提交方式 | fork `AMD-DEV-CONTEST/Radeon-hackathon-2026-07`，在 fork 中提交材料并创建 Pull Request |
| 建议 PR 标题 | `Track 2, qiancy, UR-Agent (Uni-Resource Agent)` |
| 最终截止时间 | 2026-08-06 23:59 北京/新加坡时间 (UTC+8)，即 2026-08-07 00:59 东京时间 |

## 2. 最终提交包结构

建议在比赛 fork 中保留以下目录结构：

```text
ur-agent/
  README.md
  submission-checklist.md
  submission-checklist_cn.md
  ProjectSpecificationDocument/
    project-specification.md
    project-specification_cn.md
  ProjectSourceCode/
    README.md
  DemoVideo/
    storyboard.md
    storyboard_cn.md
    video-link.md
    video-link_cn.md
  SupplementaryMaterials/
    PPT/
      outline.md
      outline_cn.md
      UR-Agent-Hackathon-2026.pdf
```

## 3. 必交材料清单

| 状态 | 材料 | 交付物 | 检查点 |
| :--- | :--- | :--- | :--- |
| 待确认 | 参赛资格 | Luma 注册、AMD Developer Program、GitHub ID、Discord ID | 使用 qiancy 个人身份；Developer No. 00000657 |
| 进行中 | 项目源码 | GitHub 仓库 `https://github.com/qiancy/ur-agent` | 源码推送完成；README 包含环境配置、启动指南、依赖列表；根目录包含 MIT LICENSE |
| 已起草 | 项目说明文档 | `ProjectSpecificationDocument/project-specification.md` / `project-specification_cn.md` | 覆盖应用场景、Agent 架构图、核心能力、模型与本地部署、AMD Radeon GPU 推理优化 |
| 待制作 | PPT | `SupplementaryMaterials/PPT/UR-Agent-Hackathon-2026.pdf` 或 `.pptx` | 6 到 8 页；突出创意场景、业务价值、架构、ROCm 本地推理与演示结果 |
| 待录制 | 演示视频 | `DemoVideo/video-link.md` 中填写网盘/公开视频链接 | 3 到 5 分钟；腾讯会议录屏；展示命令行或 GUI；展示 AMD Radeon GPU 上实际运行表现 |
| 已起草 | 视频说明与配音稿 | `DemoVideo/storyboard.md` / `storyboard_cn.md` | 可直接交给豆包生成中文语音；录制时按分镜操作 |
| 待补充 | 性能数据 | 写入项目说明和 PPT | 至少记录模型、量化等级、显存占用、tokens/s、首 token 延迟、典型任务耗时 |
| 待确认 | PR 描述 | Pull Request body | 放入项目摘要、材料链接、源码链接、运行方式、演示视频链接 |

## 4. 赛道二要求覆盖检查

| 要求 | UR-Agent 覆盖方式 | 提交前状态 |
| :--- | :--- | :--- |
| 本地知识检索 RAG | 使用组织空间隔离的知识库，支持文档写入与检索 | 需在视频中展示一次知识检索 |
| 工具调用 | Agent 调用资源、知识、人员、财务、Seller 等工具 | 需展示至少一个多工具任务 |
| 多步骤任务规划 | LangChain Agent 将自然语言拆解为工具序列 | 需在演示中保留任务执行过程 |
| 本地多轮记忆 | 会话上下文保留，同一任务中持续追问 | 需展示连续两轮对话 |
| 权限控制与隐私保护 | JWT 携带 `puid`、`ouid`，按用户与组织空间隔离上下文 | 需展示切换空间后数据不会串线 |
| AMD Radeon GPU 本地推理 | llama.cpp ROCm 在 AMD Radeon GPU 上提供 OpenAI-compatible 本地接口 | 需展示 `rocm-smi` 或日志证明 |
| 推理速度优化 | GGUF 量化、GPU offload、上下文裁剪、向量索引和工具范围约束 | 需补充实测数字 |

## 5. 8 月 3 日到 8 月 6 日执行计划

| 日期 | 目标 | 任务 |
| :--- | :--- | :--- |
| 2026-08-03 | 材料骨架完成 | 完成中文项目说明、提交清单、视频脚本、PPT 大纲 |
| 2026-08-04 | 源码与运行闭环 | 将 `ur-agent` 推到 GitHub；补齐 README、LICENSE、启动脚本；跑通本地推理、后端、前端 |
| 2026-08-05 | 录制与性能补数 | 用腾讯会议录制 3 到 5 分钟视频；记录 AMD Radeon GPU 推理性能；将数字填入文档和 PPT |
| 2026-08-06 | 最终提交 | 翻译/整理英文版材料；导出 PPT PDF；确认视频链接可访问；创建 PR |

## 6. PR 提交前逐项检查

- [ ] `https://github.com/qiancy/ur-agent` 可公开访问，且代码为最终版本。
- [ ] GitHub 源码仓库根目录包含 `LICENSE`，内容为 MIT。
- [ ] GitHub 源码仓库 README 包含依赖、环境变量、启动命令、测试命令。
- [ ] 比赛 fork 中包含 `ur-agent/README.md`。
- [ ] 比赛 fork 中包含项目说明文档，最终版建议为英文或英文 PDF。
- [ ] 比赛 fork 中包含 PPT 或海报，建议导出 PDF。
- [ ] 比赛 fork 中包含演示视频链接，链接无需登录即可访问。
- [ ] 比赛 fork 中包含生产环境 Demo 网站：`https://rc-e2369faa1fa45132.radeon.firstdg.ai`。
- [ ] 视频中不出现私钥、token、数据库密码、内网账号等敏感信息。
- [ ] 视频中展示 AMD Radeon GPU / ROCm 运行证据。
- [ ] 视频中展示至少两个赛道要求能力，建议展示 RAG、工具调用、多步骤规划、记忆、权限隔离。
- [ ] PR 标题使用 `Track 2, qiancy, UR-Agent (Uni-Resource Agent)`。
- [ ] PR 描述中写清应用名称、个人信息、源码链接、视频链接、PPT 链接和运行说明。

## 7. 当前风险与待补项

- 最终提交规则要求英文材料：当前文档是中文工作稿，需要提交前准备英文版。
- 性能数据必须来自实际 AMD Radeon GPU + ROCm 环境：不要使用估算值替代最终数字。
- 代码仓库若仍未完整推送到 GitHub，PR 中只能作为指针，评审可能无法复现。
- 演示视频建议保留终端启动过程与 GUI 操作过程，避免只展示静态结果。
