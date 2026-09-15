# UR-Agent PPT 大纲

> 中文工作稿。建议最终导出为英文 PDF：`UR-Agent-Hackathon-2026.pdf`。

## Slide 1: 标题

**UR-Agent (Uni-Resource Agent)**  
One AI. All Your Worlds.

- Track 2: 私有 AI Agent 开发与本地部署
- qiancy, AMD Developer Program No. 00000657
- GitHub: https://github.com/qiancy/ur-agent
- Demo: https://rc-e2369faa1fa45132.radeon.firstdg.ai
- License: MIT

## Slide 2: 问题与机会

标题：一个人有很多世界，通用助手很难安全地同时理解它们

- 个人、家庭、小型组织、电商经营的数据分散在不同工具中。
- 通用云端 Agent 难以处理隐私数据和权限边界。
- 传统管理软件能记录数据，但不能自然语言规划和执行。
- AMD Radeon GPU + ROCm 让本地私有 Agent 成为可落地方案。

## Slide 3: 产品定位

标题：Everything is a Resource

- 把资产、知识、人员、财务、商品、订单和任务统一抽象为资源。
- 通过“用户 + 组织空间”实现多上下文隔离。
- 同一个 Agent 可以在个人、家庭、企业和 Seller 空间中切换工作。
- 目标：本地、私有、可定制、可操作。

## Slide 4: 系统架构

标题：本地 LLM + Agent 编排 + 工具链 + 私有数据

建议配图：使用项目说明文档中的 Mermaid 架构图重绘为 PPT 图。

- Vue 3 / Gradio 作为交互入口。
- FastAPI 作为 API 服务。
- LangChain AgentExecutor 做任务拆解和工具调用。
- llama.cpp ROCm 在 AMD Radeon GPU 上运行本地模型。
- PostgreSQL、pgvector、ChromaDB 保存结构化数据和知识库。
- JWT 中的 `puid`、`ouid` 控制身份和空间边界。

## Slide 5: 核心能力

标题：赛道二 5 项能力全部覆盖

- 本地知识检索 RAG：按组织空间隔离知识集合。
- 工具调用：资源、知识、人员、财务、Seller 工具。
- 多步骤任务规划：自然语言目标自动拆解为工具序列。
- 本地多轮记忆：连续追问保持上下文。
- 权限控制与隐私保护：本地推理，JWT 空间绑定，数据不串线。

## Slide 6: AMD Radeon GPU / ROCm 适配

标题：核心推理运行在本地 AMD Radeon GPU

- 生产环境：Ubuntu 24.04.4 + ROCm 7.2.1 + AMD-SMI 26.2.2。
- 服务器：双路 AMD EPYC 9334，64 cores / 128 threads，503 GB RAM。
- GPU：AMD Radeon Graphics，49136 MB VRAM。
- 模型：Qwen3-Coder-30B-A3B GGUF Q4_K_M，经 llama.cpp ROCm 提供 OpenAI-compatible API。
- 启动参数：`-ngl -1`、`-c 524288`、`-np 2`、KV cache `q4_0`、`--flash-attn on`、`--cache-prompt`、`--op-offload`。
- CPU/NUMA：`--numa distribute`、`-t 64`、`--threads-batch 64`。
- PostgreSQL + pgvector 使用向量索引加速 RAG。

生产配置数据：

- 启动脚本提示：约 35 tok/s。
- 显存提示：约 19 GB 模型显存 + 13 GB KV cache。
- 首 token 延迟：演示视频中实测补充。

## Slide 7: 演示流程

标题：3 分钟看见一个可用的私有 Agent

- 展示 `rocm-smi` 和本地模型服务日志。
- 打开 UR-Agent 前端或 Gradio。
- 写入知识并进行 RAG 问答。
- 执行资源/财务/Seller 复合任务。
- 连续追问，展示多轮记忆。
- 切换空间，展示权限隔离。
- 展示生产 Demo 网站：https://rc-e2369faa1fa45132.radeon.firstdg.ai

## Slide 8: 价值与下一步

标题：从聊天助手到私有资源操作系统

- 对个人：统一管理生活、学习、资产和知识。
- 对家庭：共享但隔离地处理家庭事务。
- 对小型组织：低成本构建私有业务 Agent。
- 对电商经营：用自然语言查询库存、订单和经营风险。
- 下一步：补齐更多工具、强化审计日志、增加部署模板、扩展多模态输入。

## Slide 9: 提交信息

- 应用名称：UR-Agent (Uni-Resource Agent)
- 赛道：Track 2
- 参赛者：qiancy
- AMD Developer Program No.：00000657
- 源码：https://github.com/qiancy/ur-agent
- Demo：https://rc-e2369faa1fa45132.radeon.firstdg.ai
- License：MIT
- 演示视频：提交前填入链接
