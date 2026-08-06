# Pull Request 标题

```text
Track 2, d-robotics agent, RDK Agent
```

## 赛道 2 提交项目：RDK Agent

- **赛道：** Track 2 - Development and Local Deployment of Private AI Agents
- **团队 / 参赛者：** `d-robotics agent`
- **应用名称：** RDK Agent
- **演示视频（主地址）：** https://www.bilibili.com/video/BV1t3up6iEhy/
- **演示视频（备用地址）：** https://dagent-platform.bj.bcebos.com/amd-hackathon/amd-hackathon-2026-07.mp4?authorization=bce-auth-v1/ALTAKYR0nFJFHMGlFjuontyVVP/2026-08-06T12%3A43%3A01Z/-1/host/1a12970cc4c9439caa28199256b028f90e82ba41ac92c68fb921b271be0b0acd
- **源码：** `https://github.com/cowhorseming/rdk-sophon`

## 项目概述

RDK Agent 是一个私有化部署的多智能体平台，用于在 RDK X5 上开发、验证、部署和运行机器人能力。本次提交的动作包实现目前仅支持面向 MagicBox 舵机运行时、不带参数的 `rdk-servo-action/v1` 动作。

开发板侧子系统 `rdk-sophon` 的名称借鉴了《三体》中的“智子”（sophon）这一文学意象：一个被派往遥远世界、承担观察并维持通信任务的信使。在本项目中，`probe-daemon` 被部署到开发板上，用于观察硬件状态，并作为 `rdk-agent` 与设备能力之间受治理的通信桥梁。与虚构作品中的观察者不同，它由设备所有者控制、可审计且受权限边界约束。本独立项目未使用任何官方美术素材，也未获得该作品作者、出版方、权利方或影视改编方的认可，与其不存在隶属或合作关系。

用户使用自然语言描述机器人需求。在机器人开发模式（Robot Development Mode）下，多个专业智能体依次完成测试设计、最小化实现、独立可执行验证、确定性发布构建、开发板原子部署、Skill 安装，以及 CLI 和自然语言两条验收路径，将需求转化为自包含的动作包。在机器人应用模式（Robot Application Mode）下，一个受约束的智能体会针对只读查询或用户明确要求执行的一次机器人动作，选择已交付的 Skill。

项目由两个可独立部署的子系统组成：

- **`rdk-agent`** - TypeScript TUI/headless 应用，负责意图路由、多智能体 TDD、受限工具、Skill 选择、部署和 human-in-the-loop 恢复。
- **`rdk-sophon`** - 面向 RDK X5 的 Rust 平台，包含 `probe-daemon`、`sophonctl`、硬件状态采集、JSON-RPC、遥测、告警、命令策略/审计、多种传输方式及动态插件。

## 赛道 2 能力

- 通过按阶段限定范围的工具实现工具调用。
- 通过有序领域工作流实现多步骤规划与执行。
- 通过工具/Skill/写入路径 allowlist、离线测试以及动作/查询分离，在智能体层和工具层实现权限与隐私控制。
- 采用有界修订循环并支持人工跟进。
- 支持私有 OpenAI-compatible 模型路由，并提供专用的 Radeon Cloud/vLLM 目标部署路径。

本项目不声明已实现 Local RAG 或跨运行持久化记忆。

## 架构

```text
开发主机                                             RDK X5

用户 -> RDK Agent TUI / headless runner
          |-- 意图门控
          |-- 动作包 TDD
          |-- 离线 Podman 测试
          |-- 确定性构建/部署
          `-- 生成的 Skills
                    |
                 sophonctl ---- TCP 7777 ----> probe-daemon
                                                   |-- 硬件遥测
                                                   `-- 舵机插件/动作包

RDK Agent -> 私有 OpenAI-compatible vLLM -> ROCm -> AMD Radeon GPU
```

## AMD Radeon 与 ROCm

私有运行时通过 OpenAI-compatible Chat Completions 选择提供方 `amd` 和模型 `Qwen3-Next-80B-A3B-Instruct`。公开提交材料不包含真实端点和 API key，仅提供经过脱敏的配置。

应用层推理控制已经减少不必要的模型工作：确定性问候绕过、无工具的短时意图会话、按阶段聚焦的会话、严格的 Skill 加载、6,000 字符的交接上限，以及位于模型之外的确定性验证器。

团队已经实际跑通 `Qwen3-Next-80B-A3B-Instruct` 与经过 SFT 的 `Qwen3-32B-Agentic-SFT-r1-v3`。80B 路径封存了单张 Radeon 上的 `llama.cpp` 服务、兼容性与性能记录；32B SFT 路径还完成了有记录的五节点 `rdk-agent` 实机运行。单独的私有 vLLM 端点目前仅在客户端路由层得到佐证，因此公开性能结论不依赖该端点的服务器信息。

## 验证

证据采集于 2026-08-05：

- TypeScript 静态检查通过。
- `rdk-agent`：134/134 项测试通过。
- `rdk-sophon`：62/62 项测试通过。
- Rust Clippy 在拒绝所有警告的配置下通过。
- Rust workspace release 构建通过。
- RDK X5 实机 `ping` 和状态查询成功。
- 成功发现动态 `servo` 插件。

`cargo fmt --all -- --check` 仍报告现有格式差异，证据日志中已如实披露。

## 已提交材料

- Markdown 和 PDF 格式的项目说明书。
- 完整源代码仓库和英文根 README。
- 详细的复现与部署指南。
- B 站主视频地址与百度云 MP4 备用地址。
- 补充 PowerPoint 演示文稿。
- 架构图、工作流图和证据图。
- 经过脱敏的 AMD 模型配置与基准测试脚本。
- 验证证据、PR 文案和提交检查清单。

## 证据完整性

本提交不暴露凭据，不会把开发主机上的 Mach-O 二进制文件描述为 RDK X5 交付物，不会把命令成功等同于实体动作质量得到证明，也不会把估算的 AMD 性能数据当作实测数据报告。
