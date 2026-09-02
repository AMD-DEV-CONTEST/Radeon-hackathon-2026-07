[English](README.md) | [中文](README_CN.md)

# AetherDB V1.31.2 - AMD Radeon Hackathon 2026-07

**Track 1：多模态内容创作工具开发**

AetherDB 是本地优先的世界观管理与长篇创作桌面系统，面向职业小说作者、连载团队、游戏叙事设计和 IP 开发团队，整合结构化设定管理、语义与全文检索、多模态素材、章节朗读和可审核 AI 工作流。

## 开发者与致谢

- **独立开发者：** 陈sir
- **演示视频制作协助：** 奶糖（有偿协助，不属于项目开发者或参赛团队成员）

## 提交材料

| 材料 | 文件 |
| --- | --- |
| 项目概况 PDF | [AetherDB_V1.31.2_Project_Profile_Bilingual.pdf](AetherDB_V1.31.2_Project_Profile_Bilingual.pdf) |
| 演示视频 | [AetherDB_V1.31.2_Demo_1080p.mp4](AetherDB_V1.31.2_Demo_1080p.mp4) |
| 补充海报 | [AetherDB_V1.31.2_Poster_Bilingual.pdf](AetherDB_V1.31.2_Poster_Bilingual.pdf) |
| 完整源码 | [source/](source/) |
| 环境与启动说明 | [source/README_CN.md](source/README_CN.md) |
| AMD ROCm 复现说明 | [source/deploy/COMPETITION_REPRODUCTION.md](source/deploy/COMPETITION_REPRODUCTION.md) |
| 模型兼容说明 | [source/deploy/ROCM_MODEL_COMPATIBILITY.md](source/deploy/ROCM_MODEL_COMPATIBILITY.md) |

演示视频时长 4 分 20.854 秒，分辨率 1920x1080，大小约 88.86 MiB。

## 技术摘要

- Vue 3 + Tauri 2 桌面创作应用。
- FastAPI 后端，约 279 个 `/api/*` method/path。
- SQLite + Alembic + FTS5 + sqlite-vec 本地数据与检索层。
- BGE-M3 多语言向量与混合 RAG 检索。
- BGE-VL 图像/文本检索与受管理的多模态素材。
- Kokoro 82M 多语言章节朗读和声音预览。
- 可选 Kandinsky 2.2 图像生成路径。
- 模型包验证、隔离 Worker、资源调度和明确的 ROCm/CUDA/CPU 后端。
- 仅请求头 API Key 认证、能力权限门和本地生成的私有运行凭据。

## AMD Radeon / ROCm

比赛模式要求真实 ROCm 平台和模型执行证据，并验证设备节点、PyTorch HIP、真实 GPU 运算、模型包完整性、兼容 AMD 后端和当前 Worker 证据。要求 ROCm 时禁止静默 CPU 回退和未验证模型。

## 源码边界

源码树有意排除模型权重、API Key、本地配置、用户数据库、日志、缓存、生成二进制、内部代理记录和私人测试证据；模型 manifest、依赖声明、验证代码、Docker 文件、Tauri 源码和测试均已保留。

## Pull Request

正式 PR 正文使用英文 [PR_DESCRIPTION.md](PR_DESCRIPTION.md)，标题为 `Track 1, 陈sir, AetherDB`。提交前完成 [SUBMISSION_CHECKLIST.md](SUBMISSION_CHECKLIST.md)。

## 许可证

AetherDB 采用 GNU Affero General Public License version 3 only（`AGPL-3.0-only`），详见 [source/LICENSE](source/LICENSE) 和 [source/NOTICE](source/NOTICE)。
